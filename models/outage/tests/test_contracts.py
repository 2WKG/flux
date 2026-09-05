"""Behavioural checks for the 2WKG-120 contracts.

Each test pins one clause of the issue's "Done when" list.
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from models.outage.contracts import (
    CountyOutageRow,
    Driver,
    EvaluationRef,
    FeatureRow,
    FeatureStatus,
    FeatureValue,
    FixtureLabel,
    HeuristicPrediction,
    HeuristicPredictionProvenance,
    LightGBMPredictionProvenance,
    ModelArtifact,
    ObservedLabel,
    Partition,
    PredictionRecord,
    SplitAssignment,
    SplitManifest,
    TrainedModelPrediction,
    UnavailablePrediction,
    UncoveredLabel,
    WindowKey,
)

H = "a" * 64
KEY = WindowKey(county_fips="48453", scenario_id="uri_2021",
                window_start=datetime(2021, 2, 15, 6, tzinfo=UTC))


def _artifact(split_id: str = "split-1") -> ModelArtifact:
    return ModelArtifact(artifact_sha256=H, model_version="lgbm-1",
                         trained_at=datetime(2026, 9, 5, tzinfo=UTC),
                         split_id=split_id, feature_set_version="fs-1")


# --- identity, units, provenance -------------------------------------------

def test_window_start_must_be_utc_and_aligned():
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        WindowKey(county_fips="48453", scenario_id="s",
                  window_start=datetime.fromisoformat("2021-02-15T06:00:00"))
    with pytest.raises(ValidationError, match="aligned"):
        WindowKey(county_fips="48453", scenario_id="s",
                  window_start=datetime(2021, 2, 15, 7, tzinfo=UTC))


def test_county_fips_keeps_leading_zeros_and_rejects_ints():
    with pytest.raises(ValidationError):
        WindowKey(county_fips="4845", scenario_id="s", window_start=KEY.window_start)


# --- fixtures are never validated labels -----------------------------------

def test_fixture_cannot_masquerade_as_an_observed_label():
    fixture = FixtureLabel(customers_out_max=10, total_customers=100, reason="pre-ingest")
    row = CountyOutageRow(key=KEY, label=fixture)
    assert row.is_trainable is False
    # No provenance surface exists to forge.
    assert not hasattr(fixture, "source_file_sha256")
    assert not hasattr(fixture, "fraction_out")


def test_observed_label_requires_provenance():
    with pytest.raises(ValidationError):
        ObservedLabel(customers_out_max=10, total_customers=100)  # no hash / dataset / time


def test_uncovered_label_carries_no_counts_and_is_excluded_from_training():
    uncovered = UncoveredLabel(reason="no EAGLE-I sample in window")
    row = CountyOutageRow(key=KEY, label=uncovered)
    assert row.is_trainable is False
    assert not hasattr(uncovered, "customers_out_max")
    with pytest.raises(ValidationError):
        CountyOutageRow.model_validate({
            "key": KEY.model_dump(),
            "label": {"kind": "uncovered", "reason": "gap", "customers_out_max": 0},
        })


def test_observed_label_rejects_impossible_counts():
    with pytest.raises(ValidationError, match="exceeds total_customers"):
        ObservedLabel(customers_out_max=101, total_customers=100,
                      source_dataset_id="eaglei-2021", source_file_sha256=H,
                      retrieved_at=datetime(2026, 9, 5, tzinfo=UTC))


def test_discriminator_rejects_a_fixture_with_forged_provenance():
    with pytest.raises(ValidationError):
        CountyOutageRow.model_validate({
            "key": KEY.model_dump(),
            "label": {"kind": "fixture", "customers_out_max": 1, "total_customers": 2,
                      "reason": "x", "source_file_sha256": H},
        })


# --- feature availability ---------------------------------------------------

def test_missing_feature_must_not_carry_a_value():
    with pytest.raises(ValidationError, match="must not carry a value"):
        FeatureValue(value=3.0, status=FeatureStatus.MISSING_SOURCE, unit="m_s")
    with pytest.raises(ValidationError, match="requires a value"):
        FeatureValue(status=FeatureStatus.PRESENT, unit="m_s")


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_frozen_models_reject_non_finite_floats(non_finite: float):
    with pytest.raises(ValidationError):
        FeatureValue(value=non_finite, status=FeatureStatus.PRESENT, unit="m_s")


def test_feature_row_reports_what_is_missing():
    row = FeatureRow(
        key=KEY, feature_set_version="fs-1", source_input_sha256=H,
        features=(
            ("gust_max", FeatureValue(value=22.5, status=FeatureStatus.PRESENT, unit="m_s")),
            ("ice_sum_48h", FeatureValue(status=FeatureStatus.MISSING_SOURCE, unit="mm")),
        ),
    )
    assert row.missing == ("ice_sum_48h",)
    assert hash(row)
    with pytest.raises(TypeError):
        row.features[0] = ("gust_max", FeatureValue(value=0, status=FeatureStatus.PRESENT, unit="m_s"))


def test_feature_row_rejects_duplicate_feature_names():
    feature = FeatureValue(value=22.5, status=FeatureStatus.PRESENT, unit="m_s")
    with pytest.raises(ValidationError, match="duplicate names"):
        FeatureRow(
            key=KEY,
            feature_set_version="fs-1",
            source_input_sha256=H,
            features=(("gust_max", feature), ("gust_max", feature)),
        )


# --- predictions ------------------------------------------------------------

def test_trained_prediction_requires_an_artifact():
    with pytest.raises(ValidationError):
        TrainedModelPrediction(p_out=0.4, customers_at_risk=100, driver=Driver.ICE)


def test_trained_prediction_is_unevaluated_until_an_evaluation_exists():
    p = TrainedModelPrediction(p_out=0.4, customers_at_risk=100,
                               driver=Driver.ICE, artifact=_artifact())
    assert p.is_evaluated is False
    assert p.model_kind == "lightgbm"


def test_evaluation_must_match_the_models_split():
    with pytest.raises(ValidationError, match="split_id"):
        TrainedModelPrediction(
            p_out=0.4, customers_at_risk=100, driver=Driver.ICE,
            artifact=_artifact("split-1"),
            evaluation=EvaluationRef(evaluation_sha256=H, split_id="split-2"),
        )


def test_heuristic_cannot_claim_an_evaluation_or_artifact():
    with pytest.raises(ValidationError):
        HeuristicPrediction(p_out=0.4, customers_at_risk=1, driver=Driver.WIND,
                            rule_id="r", rule_version="1",
                            evaluation=EvaluationRef(evaluation_sha256=H, split_id="s"))


def test_unavailable_has_no_probability_to_fabricate():
    with pytest.raises(ValidationError):
        UnavailablePrediction(reason="no weather", p_out=0.0)
    assert UnavailablePrediction(reason="no weather").reason


def test_probability_is_bounded():
    with pytest.raises(ValidationError):
        TrainedModelPrediction(p_out=1.4, customers_at_risk=1,
                               driver=Driver.ICE, artifact=_artifact())


# --- persistence boundary ---------------------------------------------------

def test_unavailable_never_reaches_the_predictions_table():
    rec = PredictionRecord(key=KEY, prediction=UnavailablePrediction(reason="no model"))
    assert rec.to_outage_predictions_row() is None


def test_row_matches_the_six_pinned_columns():
    rec = PredictionRecord(
        key=KEY,
        prediction=TrainedModelPrediction(p_out=0.42, customers_at_risk=1234,
                                          driver=Driver.ICE, artifact=_artifact()),
    )
    table_row = rec.to_outage_predictions_row()
    assert table_row is not None
    assert set(table_row) == {
        "scenario_id", "county_fips", "ts", "p_out", "customers_at_risk", "driver"
    }
    assert table_row["driver"] == "ice"


def test_persistence_keeps_lightgbm_provenance_outside_the_six_pinned_columns():
    rec = PredictionRecord(
        key=KEY,
        prediction=TrainedModelPrediction(p_out=0.42, customers_at_risk=1234,
                                          driver=Driver.ICE, artifact=_artifact()),
    )
    persisted = rec.to_persistence()
    assert persisted is not None
    assert isinstance(persisted.provenance, LightGBMPredictionProvenance)
    assert persisted.provenance.model_kind == "lightgbm"
    assert persisted.provenance.model_version == "lgbm-1"
    assert persisted.provenance.artifact_sha256 == H
    assert set(persisted.row.model_dump()) == {
        "scenario_id", "county_fips", "ts", "p_out", "customers_at_risk", "driver"
    }


def test_persistence_keeps_heuristic_rule_provenance():
    rec = PredictionRecord(
        key=KEY,
        prediction=HeuristicPrediction(p_out=0.42, customers_at_risk=1234,
                                      driver=Driver.WIND, rule_id="cold-front", rule_version="2"),
    )
    persisted = rec.to_persistence()
    assert persisted is not None
    assert isinstance(persisted.provenance, HeuristicPredictionProvenance)
    assert persisted.provenance.model_kind == "heuristic"
    assert persisted.provenance.rule_id == "cold-front"


def test_prediction_record_rejects_another_contract_version():
    with pytest.raises(ValidationError):
        PredictionRecord(
            key=KEY,
            prediction=UnavailablePrediction(reason="no model"),
            contract_version="0.0.0",
        )


# --- split ------------------------------------------------------------------

def test_split_manifest_counts_partitions():
    m = SplitManifest(
        split_id="split-1", seed=7, input_artifact_sha256=H,
        assignments=(
            SplitAssignment(key=KEY, partition=Partition.TRAIN),
            SplitAssignment(
                key=WindowKey(
                    county_fips="48453",
                    scenario_id="uri_2021",
                    window_start=KEY.window_start + timedelta(hours=6),
                ),
                partition=Partition.HOLDOUT,
            ),
            SplitAssignment(
                key=WindowKey(
                    county_fips="48453",
                    scenario_id="uri_2021",
                    window_start=KEY.window_start + timedelta(hours=12),
                ),
                partition=Partition.HOLDOUT,
            ),
        ),
    )
    assert m.counts()[Partition.TRAIN] == 1
    assert m.counts()[Partition.CALIBRATION] == 0
    assert m.counts()[Partition.HOLDOUT] == 2


def test_split_manifest_rejects_duplicate_window_key_assignments():
    with pytest.raises(ValidationError, match="duplicate WindowKey"):
        SplitManifest(
            split_id="split-1",
            seed=7,
            input_artifact_sha256=H,
            assignments=(
                SplitAssignment(key=KEY, partition=Partition.TRAIN),
                SplitAssignment(key=KEY, partition=Partition.TRAIN),
            ),
        )


def test_split_manifest_rejects_a_window_key_across_partitions():
    with pytest.raises(ValidationError, match="duplicate WindowKey"):
        SplitManifest(
            split_id="split-1",
            seed=7,
            input_artifact_sha256=H,
            assignments=(
                SplitAssignment(key=KEY, partition=Partition.TRAIN),
                SplitAssignment(key=KEY, partition=Partition.HOLDOUT),
            ),
        )

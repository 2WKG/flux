import importlib
from datetime import UTC, datetime
from typing import get_args

import pytest
from pydantic import ValidationError

from copilot.tools.schemas import Unavailable, UnavailableCode
from models.outage.contracts import (
    Driver,
    EvaluationRef,
    FeatureRow,
    FeatureStatus,
    FeatureValue,
    HeuristicPrediction,
    ModelArtifact,
    TrainedModelPrediction,
    UnavailablePrediction,
    WindowKey,
)
from models.outage.prediction_paths import (
    UNAVAILABLE_CODES,
    UnavailableReason,
    heuristic_prediction,
    to_unavailable,
    trained_prediction,
    unavailable_prediction,
)

H = "a" * 64
KEY = WindowKey(
    county_fips="48453",
    scenario_id="summer-peak",
    window_start=datetime(2024, 7, 1, tzinfo=UTC),
)
ARTIFACT = ModelArtifact(
    artifact_sha256=H,
    model_version="lgbm-1",
    trained_at=datetime(2024, 1, 1, tzinfo=UTC),
    split_id="split-1",
    feature_set_version="features-1",
)
EVALUATION = EvaluationRef(
    evaluation_sha256="b" * 64, split_id="split-1", calibration_method="isotonic"
)


def row(
    *entries: tuple[str, FeatureValue], feature_set_version: str = "features-1"
) -> FeatureRow:
    return FeatureRow(
        key=KEY,
        feature_set_version=feature_set_version,
        source_input_sha256=H,
        features=entries,
    )


PRESENT_ROW = row(
    ("gust_max", FeatureValue(value=20.0, status=FeatureStatus.PRESENT, unit="m_s"))
)
ALL_MISSING_ROW = row(
    ("gust_max", FeatureValue(status=FeatureStatus.MISSING_SOURCE, unit="m_s"))
)
PARTLY_MISSING_ROW = row(
    ("gust_max", FeatureValue(value=20.0, status=FeatureStatus.PRESENT, unit="m_s")),
    ("ice_mm", FeatureValue(status=FeatureStatus.OUT_OF_COVERAGE, unit="mm")),
)


def trained(**overrides):
    kwargs = {
        "features": PRESENT_ROW,
        "artifact": ARTIFACT,
        "scorer": lambda values: values["gust_max"] / 100,
        "customers_at_risk": 120,
        "driver": Driver.WIND,
        "evaluation": EVALUATION,
    }
    kwargs.update(overrides)
    return trained_prediction(**kwargs)


def heuristic(**overrides):
    kwargs = {
        "features": PRESENT_ROW,
        "rule": lambda _: 0.3,
        "rule_id": "wind-threshold",
        "rule_version": "2",
        "customers_at_risk": 120,
        "driver": Driver.WIND,
    }
    kwargs.update(overrides)
    return heuristic_prediction(**kwargs)


def assert_unavailable(record, reason: UnavailableReason) -> None:
    assert isinstance(record.prediction, UnavailablePrediction)
    assert record.prediction.reason == reason.value
    assert record.to_persistence() is None


# ---------------------------------------------------------------------------
# Trained path
# ---------------------------------------------------------------------------


def test_trained_path_preserves_artifact_evaluation_and_identity():
    record = trained()

    assert isinstance(record.prediction, TrainedModelPrediction)
    assert record.key == KEY
    assert record.prediction.p_out == 0.2
    assert record.prediction.artifact == ARTIFACT
    assert record.prediction.evaluation == EVALUATION
    assert record.prediction.customers_at_risk == 120
    assert record.prediction.driver == Driver.WIND

    persisted = record.to_persistence()
    assert persisted is not None
    assert persisted.row.customers_at_risk == 120
    assert persisted.provenance.model_kind == "lightgbm"
    assert persisted.provenance.artifact_sha256 == ARTIFACT.artifact_sha256
    assert persisted.provenance.feature_set_version == "features-1"
    assert persisted.provenance.evaluation_sha256 == EVALUATION.evaluation_sha256


def test_trained_path_scorer_receives_only_present_values():
    seen = {}

    def scorer(values):
        seen.update(values)
        return 0.5

    trained(scorer=scorer)
    assert seen == {"gust_max": 20.0}


def test_missing_trained_model_never_falls_back_to_heuristic():
    record = trained(artifact=None)

    assert_unavailable(record, UnavailableReason.MISSING_MODEL_ARTIFACT)
    assert not isinstance(record.prediction, HeuristicPrediction)


def test_missing_scorer_is_unavailable():
    assert_unavailable(trained(scorer=None), UnavailableReason.MISSING_MODEL_SCORER)


def test_feature_set_version_mismatch_is_unavailable_and_scorer_not_called():
    calls = []
    record = trained(
        features=row(
            (
                "gust_max",
                FeatureValue(value=20.0, status=FeatureStatus.PRESENT, unit="m_s"),
            ),
            feature_set_version="features-9",
        ),
        scorer=lambda values: calls.append(values) or 0.2,
    )

    assert_unavailable(record, UnavailableReason.FEATURE_SET_VERSION_MISMATCH)
    assert calls == []


@pytest.mark.parametrize(
    "features",
    [ALL_MISSING_ROW, PARTLY_MISSING_ROW],
    ids=["all_missing", "partly_missing"],
)
def test_trained_path_missing_features_are_unavailable_not_scored(features):
    calls = []
    record = trained(
        features=features, scorer=lambda values: calls.append(values) or 0.2
    )

    assert_unavailable(record, UnavailableReason.MISSING_PREDICTION_FEATURES)
    assert calls == []


def test_trained_path_guard_order_artifact_before_scorer_before_version_before_features():
    # Each guard is reached only when the earlier ones pass.
    assert (
        trained(artifact=None, scorer=None).prediction.reason
        == "missing_model_artifact"
    )
    assert (
        trained(scorer=None, features=ALL_MISSING_ROW).prediction.reason
        == "missing_model_scorer"
    )
    mismatched_missing = row(
        ("gust_max", FeatureValue(status=FeatureStatus.MISSING_SOURCE, unit="m_s")),
        feature_set_version="features-9",
    )
    assert (
        trained(features=mismatched_missing).prediction.reason
        == "feature_set_version_mismatch"
    )


def test_trained_path_out_of_range_score_raises_rather_than_clamps():
    with pytest.raises(ValidationError):
        trained(scorer=lambda _: 1.5)
    with pytest.raises(ValidationError):
        trained(scorer=lambda _: float("nan"))


# ---------------------------------------------------------------------------
# Heuristic path
# ---------------------------------------------------------------------------


def test_heuristic_path_carries_rule_provenance():
    record = heuristic()

    assert isinstance(record.prediction, HeuristicPrediction)
    assert record.prediction.model_kind == "heuristic"
    assert record.prediction.rule_id == "wind-threshold"
    assert record.prediction.rule_version == "2"
    assert record.prediction.customers_at_risk == 120
    assert record.prediction.driver == Driver.WIND
    assert record.prediction.p_out == 0.3

    persisted = record.to_persistence()
    assert persisted is not None
    assert persisted.row.customers_at_risk == 120
    assert persisted.provenance.model_kind == "heuristic"
    assert persisted.provenance.rule_id == "wind-threshold"
    assert persisted.provenance.rule_version == "2"


def test_missing_heuristic_rule_is_unavailable():
    assert_unavailable(heuristic(rule=None), UnavailableReason.MISSING_HEURISTIC_RULE)


@pytest.mark.parametrize(
    "features",
    [ALL_MISSING_ROW, PARTLY_MISSING_ROW],
    ids=["all_missing", "partly_missing"],
)
def test_heuristic_on_missing_features_is_unavailable_not_a_default_probability(
    features,
):
    calls = []
    record = heuristic(features=features, rule=lambda f: calls.append(f) or 0.3)

    assert_unavailable(record, UnavailableReason.MISSING_PREDICTION_FEATURES)
    assert not hasattr(record.prediction, "p_out")
    assert calls == []


def test_heuristic_out_of_range_rule_raises_rather_than_clamps():
    with pytest.raises(ValidationError):
        heuristic(rule=lambda _: 2.0)


# ---------------------------------------------------------------------------
# Unavailable vocabulary
# ---------------------------------------------------------------------------


def test_unavailable_reason_rejects_free_text():
    with pytest.raises(ValueError):
        unavailable_prediction(key=KEY, reason="whatever the caller typed")


def test_unavailable_reason_accepts_member_and_its_exact_value():
    by_member = unavailable_prediction(
        key=KEY, reason=UnavailableReason.MISSING_MODEL_ARTIFACT
    )
    by_value = unavailable_prediction(key=KEY, reason="missing_model_artifact")
    assert by_member == by_value
    assert by_member.prediction.reason == "missing_model_artifact"


def test_every_reason_maps_onto_the_shared_unavailable_code_vocabulary():
    # ``UnavailableCode`` is a PEP 695 ``type`` alias; its Literal lives in ``__value__``.
    shared_codes = set(get_args(UnavailableCode.__value__))
    assert (
        shared_codes
    )  # the vocabulary itself must be non-empty for this check to mean anything
    assert set(UNAVAILABLE_CODES) == set(UnavailableReason)
    assert set(UNAVAILABLE_CODES.values()) <= shared_codes


def test_shared_envelope_rejects_a_code_outside_the_vocabulary():
    with pytest.raises(ValidationError):
        Unavailable(code="not_a_shared_code", reason="missing_model_artifact")


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        (UnavailableReason.MISSING_MODEL_ARTIFACT, "artifact_unavailable"),
        (UnavailableReason.MISSING_MODEL_SCORER, "artifact_unavailable"),
        (UnavailableReason.MISSING_HEURISTIC_RULE, "artifact_unavailable"),
        (UnavailableReason.MISSING_PREDICTION_FEATURES, "insufficient_evidence"),
        (UnavailableReason.FEATURE_SET_VERSION_MISMATCH, "invalid_prerequisite"),
    ],
)
def test_to_unavailable_carries_code_and_specific_reason(reason, code):
    record = unavailable_prediction(key=KEY, reason=reason)
    envelope = to_unavailable(record.prediction)

    assert isinstance(envelope, Unavailable)
    assert envelope.code == code
    assert envelope.reason == reason.value
    assert envelope.retryable is False


def test_to_unavailable_rejects_unknown_reason_in_a_hand_built_prediction():
    with pytest.raises(ValueError):
        to_unavailable(UnavailablePrediction(reason="not_in_vocabulary"))


# ---------------------------------------------------------------------------
# Module path
# ---------------------------------------------------------------------------


def test_spec_02_predict_module_path_is_left_free_for_the_scenario_runner():
    # Spec 02 pins ``models.outage.predict`` for ``predict_scenario``/``driver_of``; this PR
    # must not squat on it. Importing it must fail loudly, not succeed as a silent no-op.
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("models.outage.predict")

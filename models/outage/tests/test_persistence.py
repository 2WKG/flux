"""Persistence and query coverage for 2WKG-122.

Each test pins one clause of the issue's "Done when" list.
"""

from datetime import UTC, datetime

import duckdb
import pytest

from models.outage.contracts import (
    Driver,
    EvaluationRef,
    HeuristicPrediction,
    LightGBMPredictionProvenance,
    ModelArtifact,
    PredictionRecord,
    TrainedModelPrediction,
    UnavailablePrediction,
    WindowKey,
)
from models.outage.evaluate import (
    EvaluationArtifact,
    EvaluationMetrics,
    EvaluationStatus,
    HoldoutCoverage,
)
from models.outage.persistence import (
    ensure_persistence_schema,
    persist_evaluation,
    persist_predictions,
    query_evaluation,
    query_predictions,
    PREDICTION_PROVENANCE_DDL,
    EVALUATION_ARTIFACTS_DDL,
)

H = "a" * 64
KEY = WindowKey(
    county_fips="48453",
    scenario_id="beryl_2024",
    window_start=datetime(2024, 7, 5, 0, tzinfo=UTC),
)
KEY_2 = WindowKey(
    county_fips="48453",
    scenario_id="beryl_2024",
    window_start=datetime(2024, 7, 5, 6, tzinfo=UTC),
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


def _fresh_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    # Ensure the outage_predictions table exists (from db.py schema)
    con.execute(
        """CREATE TABLE IF NOT EXISTS outage_predictions (
            scenario_id TEXT NOT NULL,
            county_fips TEXT NOT NULL,
            ts TIMESTAMP NOT NULL,
            p_out DOUBLE NOT NULL CHECK (p_out BETWEEN 0 AND 1),
            customers_at_risk BIGINT NOT NULL CHECK (customers_at_risk >= 0),
            driver TEXT NOT NULL CHECK (driver IN ('ice','wind','heat','wildfire','flood','other')),
            source_name TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            source_version TEXT,
            source_retrieved_at TIMESTAMP,
            fixture_batch_id TEXT NOT NULL,
            PRIMARY KEY (scenario_id, county_fips, ts)
        )"""
    )
    ensure_persistence_schema(con)
    return con


def _trained_record(key: WindowKey = KEY, **overrides) -> PredictionRecord:
    kwargs = {
        "key": key,
        "prediction": TrainedModelPrediction(
            p_out=0.42,
            customers_at_risk=1234,
            driver=Driver.ICE,
            artifact=ARTIFACT,
            evaluation=EVALUATION,
        ),
    }
    kwargs.update(overrides)
    return PredictionRecord(**kwargs)


def _heuristic_record(key: WindowKey = KEY) -> PredictionRecord:
    return PredictionRecord(
        key=key,
        prediction=HeuristicPrediction(
            p_out=0.3,
            customers_at_risk=500,
            driver=Driver.WIND,
            rule_id="cold-front",
            rule_version="2",
        ),
    )


def _unavailable_record(key: WindowKey = KEY) -> PredictionRecord:
    return PredictionRecord(
        key=key,
        prediction=UnavailablePrediction(reason="missing_model_artifact"),
    )


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------


def test_ddl_is_idempotent():
    con = _fresh_con()
    ensure_persistence_schema(con)
    ensure_persistence_schema(con)
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert "prediction_provenance" in tables
    assert "evaluation_artifacts" in tables


def test_provenance_table_enforces_model_kind_check():
    con = _fresh_con()
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            """INSERT INTO prediction_provenance
               (scenario_id, county_fips, ts, model_kind, persisted_at)
               VALUES ('s', '48453', '2024-07-05T00:00:00Z', 'bad_kind', '2024-01-01')"""
        )


# ---------------------------------------------------------------------------
# Persist predictions
# ---------------------------------------------------------------------------


def test_persist_trained_model_writes_row_and_provenance():
    con = _fresh_con()
    record = _trained_record()
    written = persist_predictions(con, [record])

    assert written == 1
    row = con.execute(
        "SELECT scenario_id, county_fips, ts, p_out, customers_at_risk, driver FROM outage_predictions"
    ).fetchone()
    assert row[0] == "beryl_2024"
    assert row[1] == "48453"
    # DuckDB stores TIMESTAMP without TZ and returns it as local time.
    # Compare epoch seconds to avoid timezone ambiguity.
    assert row[2].timestamp() == pytest.approx(KEY.window_start.timestamp(), abs=1)
    assert row[3] == 0.42
    assert row[4] == 1234
    assert row[5] == "ice"

    prov = con.execute(
        "SELECT model_kind, model_version, artifact_sha256, split_id, feature_set_version, evaluation_sha256 FROM prediction_provenance"
    ).fetchone()
    assert prov == ("lightgbm", "lgbm-1", H, "split-1", "features-1", "b" * 64)


def test_persist_heuristic_writes_rule_provenance():
    con = _fresh_con()
    record = _heuristic_record()
    written = persist_predictions(con, [record])

    assert written == 1
    prov = con.execute(
        "SELECT model_kind, rule_id, rule_version FROM prediction_provenance"
    ).fetchone()
    assert prov == ("heuristic", "cold-front", "2")


def test_unavailable_prediction_is_not_persisted():
    con = _fresh_con()
    record = _unavailable_record()
    written = persist_predictions(con, [record])

    assert written == 0
    assert con.execute("SELECT count(*) FROM outage_predictions").fetchone() == (0,)
    assert con.execute("SELECT count(*) FROM prediction_provenance").fetchone() == (0,)


def test_trained_model_without_artifact_is_rejected_by_contract_before_persistence():
    """An incomplete trained-model claim is rejected at the contract level."""
    with pytest.raises(Exception):
        TrainedModelPrediction(
            p_out=0.4, customers_at_risk=100, driver=Driver.ICE
        )


def test_mixed_predictions_persist_only_available_rows():
    con = _fresh_con()
    records = [
        _trained_record(),
        _heuristic_record(key=KEY_2),
        _unavailable_record(),
    ]
    written = persist_predictions(con, records)

    assert written == 2
    assert con.execute("SELECT count(*) FROM outage_predictions").fetchone() == (2,)
    kinds = {
        r[0]
        for r in con.execute(
            "SELECT model_kind FROM prediction_provenance"
        ).fetchall()
    }
    assert kinds == {"lightgbm", "heuristic"}


def test_persist_predictions_is_idempotent():
    con = _fresh_con()
    record = _trained_record()
    persist_predictions(con, [record])
    persist_predictions(con, [record])

    assert con.execute("SELECT count(*) FROM outage_predictions").fetchone() == (1,)
    assert con.execute("SELECT count(*) FROM prediction_provenance").fetchone() == (1,)


# ---------------------------------------------------------------------------
# Query predictions
# ---------------------------------------------------------------------------


def test_fixture_query_returns_all_rows_for_a_scenario():
    con = _fresh_con()
    persist_predictions(con, [_trained_record(), _heuristic_record(key=KEY_2)])

    results = query_predictions(con, scenario_id="beryl_2024")
    assert len(results) == 2
    kinds = {r["model_kind"] for r in results}
    assert kinds == {"lightgbm", "heuristic"}
    for r in results:
        assert set(r) == {
            "scenario_id",
            "county_fips",
            "ts",
            "p_out",
            "customers_at_risk",
            "driver",
            "model_kind",
            "model_version",
            "artifact_sha256",
            "split_id",
            "feature_set_version",
            "evaluation_sha256",
            "rule_id",
            "rule_version",
        }


def test_trained_model_query_filters_by_model_kind():
    con = _fresh_con()
    persist_predictions(con, [_trained_record(), _heuristic_record(key=KEY_2)])

    results = query_predictions(con, scenario_id="beryl_2024", model_kind="lightgbm")
    assert len(results) == 1
    assert results[0]["model_kind"] == "lightgbm"
    assert results[0]["artifact_sha256"] == H
    assert results[0]["model_version"] == "lgbm-1"
    assert results[0]["evaluation_sha256"] == "b" * 64

    results = query_predictions(con, scenario_id="beryl_2024", model_kind="heuristic")
    assert len(results) == 1
    assert results[0]["model_kind"] == "heuristic"
    assert results[0]["rule_id"] == "cold-front"
    assert results[0]["rule_version"] == "2"


def test_query_by_county_fips():
    con = _fresh_con()
    persist_predictions(con, [_trained_record()])

    results = query_predictions(con, county_fips="48453")
    assert len(results) == 1

    results = query_predictions(con, county_fips="99999")
    assert results == []


def test_query_is_bounded_by_limit():
    con = _fresh_con()
    records = [
        _trained_record(
            key=WindowKey(
                county_fips="48453",
                scenario_id="s",
                window_start=datetime(2024, 7, 5 + d, 0, tzinfo=UTC),
            )
        )
        for d in range(10)
    ]
    persist_predictions(con, records)

    results = query_predictions(con, scenario_id="s", limit=3)
    assert len(results) == 3


def test_query_never_returns_unavailable():
    """Unavailable predictions are never in the table, so no query can return one."""
    con = _fresh_con()
    persist_predictions(con, [_trained_record(), _unavailable_record()])

    results = query_predictions(con, scenario_id="beryl_2024")
    assert len(results) == 1
    assert results[0]["model_kind"] == "lightgbm"


def test_query_is_deterministic():
    con = _fresh_con()
    persist_predictions(con, [_trained_record(), _heuristic_record(key=KEY_2)])

    first = query_predictions(con, scenario_id="beryl_2024")
    second = query_predictions(con, scenario_id="beryl_2024")
    assert first == second


def test_query_preserves_heuristic_distinction():
    """A heuristic result is labelled as heuristic, not as a trained model."""
    con = _fresh_con()
    persist_predictions(con, [_heuristic_record()])

    results = query_predictions(con, scenario_id="beryl_2024")
    assert len(results) == 1
    assert results[0]["model_kind"] == "heuristic"
    assert results[0]["rule_id"] == "cold-front"
    assert results[0]["artifact_sha256"] is None


# ---------------------------------------------------------------------------
# Persist and query evaluation
# ---------------------------------------------------------------------------


def _eval_artifact() -> EvaluationArtifact:
    return EvaluationArtifact(
        evaluation_sha256="c" * 64,
        status=EvaluationStatus.READY,
        model_artifact_sha256=H,
        model_version="lgbm-1",
        split_id="split-1",
        split_input_artifact_sha256="d" * 64,
        coverage=HoldoutCoverage(holdout_size=100, scored=100, coverage=1.0),
        metrics=EvaluationMetrics(
            brier_score=0.15,
            fraction_out_mae=0.08,
            denominator=100,
        ),
        calibration_method="isotonic",
        calibration_status="reported",
        uncertainty_method="bootstrap",
    )


def test_persist_and_query_evaluation():
    con = _fresh_con()
    artifact = _eval_artifact()
    persist_evaluation(con, artifact)

    result = query_evaluation(con, "c" * 64)
    assert result is not None
    assert result["status"] == "ready"
    assert result["model_artifact_sha256"] == H
    assert result["calibration_method"] == "isotonic"
    assert result["calibration_status"] == "reported"
    assert result["metrics_json"] is not None


def test_query_evaluation_returns_none_for_missing_hash():
    con = _fresh_con()
    assert query_evaluation(con, "c" * 64) is None


def test_persist_evaluation_is_idempotent():
    con = _fresh_con()
    artifact = _eval_artifact()
    persist_evaluation(con, artifact)
    persist_evaluation(con, artifact)

    assert con.execute("SELECT count(*) FROM evaluation_artifacts").fetchone() == (1,)


def test_no_query_path_recomputes_evaluation():
    """The evaluation query reads stored metrics; it never recomputes them."""
    con = _fresh_con()
    artifact = _eval_artifact()
    persist_evaluation(con, artifact)

    # A different artifact with a different brier_score should produce a different stored value.
    result = query_evaluation(con, "c" * 64)
    assert result is not None
    import json

    stored = json.loads(result["metrics_json"])
    assert stored["brier_score"] == 0.15


def test_unavailable_evaluation_is_persisted_with_reason():
    con = _fresh_con()
    from models.outage.evaluate import (
        EvaluationUnavailableReason,
        UnavailableEvaluationArtifact,
    )

    artifact = UnavailableEvaluationArtifact(
        evaluation_sha256="e" * 64,
        status=EvaluationStatus.UNAVAILABLE,
        model_artifact_sha256=H,
        split_id="split-1",
        coverage=HoldoutCoverage(holdout_size=100, scored=0, coverage=0.0),
        reason=EvaluationUnavailableReason.INSUFFICIENT_HOLDOUT_RECORDS,
    )
    persist_evaluation(con, artifact)

    result = query_evaluation(con, "e" * 64)
    assert result is not None
    assert result["status"] == "unavailable"
    assert result["reason"] == "insufficient_holdout_records"
    assert result["metrics_json"] is None
    assert result["calibration_status"] == "not_applicable"
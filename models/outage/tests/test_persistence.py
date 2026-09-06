"""Persistence and query coverage for 2WKG-122.

Each test pins one clause of the issue's "Done when" list against the real
``pipelines.db`` DDL (contract 2.0.0, with the ``scenarios``/``counties``
foreign keys) on a temporary database file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
from pydantic import ValidationError

from models.outage.contracts import (
    CountyOutageRow,
    Driver,
    HeuristicPrediction,
    ModelArtifact,
    ObservedLabel,
    PredictionRecord,
    TrainedModelPrediction,
    UnavailablePrediction,
    WindowKey,
)
from models.outage.evaluate import (
    EvaluationArtifact,
    EvaluationStatus,
    HeldoutPrediction,
    UnavailableEvaluationArtifact,
    evaluate_holdout_predictions,
)
from models.outage.persistence import (
    BRIER_ACCEPTANCE,
    MAX_QUERY_LIMIT,
    EvaluationEvidence,
    PersistenceContractError,
    PersistenceError,
    UnqualifiedEvaluationError,
    ensure_persistence_schema,
    persist_evaluation,
    persist_predictions,
    qualify_evaluation,
    query_evaluation,
    query_predictions,
)
from models.outage.split import build_split_manifest
from pipelines.db import (
    SCHEMA_VERSION,
    connect,
    stored_contract_version,
    validate_schema,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

H = "a" * 64
SOURCE_H = "b" * 64
BATCH = "batch-2wkg-122-test"


def _key(when: datetime, scenario_id: str = "beryl_2024") -> WindowKey:
    return WindowKey(county_fips="48453", scenario_id=scenario_id, window_start=when)


def _label(customers_out_max: int, total_customers: int = 100) -> ObservedLabel:
    return ObservedLabel(
        customers_out_max=customers_out_max,
        total_customers=total_customers,
        source_dataset_id="eaglei",
        source_file_sha256=SOURCE_H,
        retrieved_at=datetime(2024, 7, 20, tzinfo=UTC),
    )


# Beryl window (2024-07-04..07-14, TX) -> HOLDOUT; 2023 TX -> CALIBRATION; 2022 TX -> TRAIN.
KEY = _key(datetime(2024, 7, 5, 0, tzinfo=UTC))
KEY_2 = _key(datetime(2024, 7, 5, 6, tzinfo=UTC))
KEY_3 = _key(datetime(2024, 7, 5, 12, tzinfo=UTC))
HOLDOUT_KEYS = (KEY, KEY_2, KEY_3)
SPLIT = build_split_manifest(
    tuple(
        CountyOutageRow(key=key, label=_label(20))
        for key in (
            *HOLDOUT_KEYS,
            _key(datetime(2023, 3, 1, tzinfo=UTC)),
            _key(datetime(2022, 3, 1, tzinfo=UTC)),
        )
    ),
    states_by_county={"48453": "TX"},
    input_artifact_sha256=H,
)
ARTIFACT = ModelArtifact(
    artifact_sha256=H,
    model_version="lgbm-1",
    trained_at=datetime(2024, 1, 1, tzinfo=UTC),
    split_id=SPLIT.split_id,
    feature_set_version="features-1",
)
OTHER_ARTIFACT = ARTIFACT.model_copy(update={"artifact_sha256": "f" * 64})
LABELS = (
    _label(20),
    _label(100),
    _label(2),
)  # frac 0.20 -> y=1, 1.00 -> y=1, 0.02 -> y=0


def _predictions(*p_outs: float) -> tuple[HeldoutPrediction, ...]:
    return tuple(
        HeldoutPrediction(key=key, p_out=p, label=label)
        for key, p, label in zip(HOLDOUT_KEYS, p_outs, LABELS, strict=True)
    )


# Brier = mean((p - y)^2): (0.05^2 * 3) / 3 = 0.0025 <= 0.12 -> qualified.
GOOD_PREDICTIONS = _predictions(0.95, 0.95, 0.05)
# Brier = (0.49 + 0.01 + 0.01) / 3 = 0.17 > 0.12 -> READY but unqualified.
BAD_PREDICTIONS = _predictions(0.3, 0.9, 0.1)

QUALIFIED_EVAL = evaluate_holdout_predictions(
    model=ARTIFACT,
    split=SPLIT,
    predictions=GOOD_PREDICTIONS,
    calibration_method="isotonic",
    uncertainty_method="bootstrap",
)
QUALIFIED_EVIDENCE = EvaluationEvidence(ARTIFACT, SPLIT, GOOD_PREDICTIONS)
FAILING_EVAL = evaluate_holdout_predictions(
    model=ARTIFACT, split=SPLIT, predictions=BAD_PREDICTIONS
)
FAILING_EVIDENCE = EvaluationEvidence(ARTIFACT, SPLIT, BAD_PREDICTIONS)
UNAVAILABLE_EVAL = evaluate_holdout_predictions(
    model=ARTIFACT, split=SPLIT, predictions=()
)
UNAVAILABLE_EVIDENCE = EvaluationEvidence(ARTIFACT, SPLIT, ())
OTHER_MODEL_EVAL = evaluate_holdout_predictions(
    model=OTHER_ARTIFACT, split=SPLIT, predictions=GOOD_PREDICTIONS
)
OTHER_MODEL_EVIDENCE = EvaluationEvidence(OTHER_ARTIFACT, SPLIT, GOOD_PREDICTIONS)
QUALIFIED_REF = QUALIFIED_EVAL.to_ref()

assert isinstance(QUALIFIED_EVAL, EvaluationArtifact)
assert isinstance(FAILING_EVAL, EvaluationArtifact)
assert isinstance(UNAVAILABLE_EVAL, UnavailableEvaluationArtifact)
assert isinstance(OTHER_MODEL_EVAL, EvaluationArtifact)

PROVENANCE_SQL = "'test', 'test-ref', NULL, NULL, 'test-batch'"


def _seed_parents(con: duckdb.DuckDBPyConnection) -> None:
    """Insert the ``scenarios``/``counties`` rows the real FKs require."""
    for scenario_id in ("beryl_2024", "s"):
        con.execute(
            f"""INSERT INTO scenarios VALUES (?, 'Test', 'historical',
                '2024-07-01', '2024-07-31', {PROVENANCE_SQL})""",
            [scenario_id],
        )
    con.execute(
        f"""INSERT INTO counties VALUES ('48453', 'Travis', 'TX', 1000000,
            '\\x00'::BLOB, {PROVENANCE_SQL})"""
    )


@pytest.fixture
def con(tmp_path: Path):
    """A real contract-2.0.0 database file with the companion tables and FK parents."""
    connection = connect(tmp_path / "grid.duckdb")
    ensure_persistence_schema(connection)
    _seed_parents(connection)
    yield connection
    connection.close()


def _seed_qualified(con: duckdb.DuckDBPyConnection) -> None:
    persist_evaluation(con, QUALIFIED_EVAL, evidence=QUALIFIED_EVIDENCE)


def _trained_record(
    key: WindowKey = KEY,
    *,
    evaluation=QUALIFIED_REF,
    artifact: ModelArtifact = ARTIFACT,
    p_out: float = 0.42,
) -> PredictionRecord:
    return PredictionRecord(
        key=key,
        prediction=TrainedModelPrediction(
            p_out=p_out,
            customers_at_risk=1234,
            driver=Driver.ICE,
            artifact=artifact,
            evaluation=evaluation,
        ),
    )


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


def _count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# ---------------------------------------------------------------------------
# Schema: through the shared contract
# ---------------------------------------------------------------------------


def test_ddl_is_idempotent(con):
    ensure_persistence_schema(con)
    ensure_persistence_schema(con)
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert {
        "prediction_provenance",
        "evaluation_artifacts",
        "outage_predictions",
    } <= tables


def test_schema_goes_through_the_shared_contract():
    con = duckdb.connect(":memory:")
    ensure_persistence_schema(con)
    assert stored_contract_version(con) == SCHEMA_VERSION == "2.0.0"
    validate_schema(con)
    # The real outage_predictions DDL: FKs to scenarios/counties are enforced.
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            f"""INSERT INTO outage_predictions VALUES ('nope', '48453', '2024-07-05',
                0.1, 1, 'ice', {PROVENANCE_SQL})"""
        )


def test_schema_refuses_a_foreign_contract_version():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute("INSERT INTO schema_meta VALUES ('contract_version', '0.9.0')")
    with pytest.raises(PersistenceContractError, match="0.9.0"):
        ensure_persistence_schema(con)
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert "prediction_provenance" not in tables


def test_provenance_table_enforces_model_kind_check(con):
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            """INSERT INTO prediction_provenance
               (scenario_id, county_fips, ts, model_kind, persisted_at)
               VALUES ('s', '48453', '2024-07-05T00:00:00Z', 'bad_kind', '2024-01-01')"""
        )


def test_provenance_row_requires_its_prediction_row(con):
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            """INSERT INTO prediction_provenance
               (scenario_id, county_fips, ts, model_kind, rule_id, rule_version, persisted_at)
               VALUES ('beryl_2024', '48453', '2030-01-01', 'heuristic', 'r', '1', '2024-01-01')"""
        )


# ---------------------------------------------------------------------------
# Persist predictions
# ---------------------------------------------------------------------------


def test_persist_trained_model_writes_row_and_provenance(con):
    _seed_qualified(con)
    written = persist_predictions(con, [_trained_record()], fixture_batch_id=BATCH)

    assert written == 1
    row = con.execute(
        """SELECT scenario_id, county_fips, ts, p_out, customers_at_risk, driver,
                  source_name, source_ref, source_version, fixture_batch_id
           FROM outage_predictions"""
    ).fetchone()
    assert row[:2] == ("beryl_2024", "48453")
    # Stored as naive UTC: the spec-02 window key, not the host's wall time.
    assert row[2] == KEY.window_start.replace(tzinfo=None)  # naive UTC, 00:00
    assert row[3:6] == (0.42, 1234, "ice")
    assert row[6:] == ("models.outage", H, "lgbm-1", BATCH)

    prov = con.execute(
        """SELECT model_kind, model_version, artifact_sha256, split_id,
                  feature_set_version, evaluation_sha256 FROM prediction_provenance"""
    ).fetchone()
    assert prov == (
        "lightgbm",
        "lgbm-1",
        H,
        SPLIT.split_id,
        "features-1",
        QUALIFIED_EVAL.evaluation_sha256,
    )


def test_persisted_at_is_utc(con):
    _seed_qualified(con)
    before = datetime.now(UTC)
    persist_predictions(con, [_trained_record()], fixture_batch_id=BATCH)
    stored = con.execute("SELECT persisted_at FROM prediction_provenance").fetchone()[0]
    assert stored.tzinfo is None
    assert abs(stored.replace(tzinfo=UTC) - before) < timedelta(minutes=1)
    queried = query_predictions(con, scenario_id="beryl_2024")[0]["persisted_at"]
    assert queried.tzinfo is UTC


_TZ_SCRIPT = textwrap.dedent(
    """
    import json, tempfile, time
    from pathlib import Path
    time.tzset()
    from models.outage.tests import test_persistence as t
    from pipelines.db import connect
    con = connect(Path(tempfile.mkdtemp()) / "grid.duckdb")
    t.ensure_persistence_schema(con)
    t._seed_parents(con)
    t._seed_qualified(con)
    t.persist_predictions(con, [t._trained_record()], fixture_batch_id=t.BATCH)
    raw_ts, = con.execute("SELECT ts FROM outage_predictions").fetchone()
    queried = t.query_predictions(con, scenario_id="beryl_2024")[0]["ts"]
    print(json.dumps({"raw_ts": str(raw_ts), "queried": queried.isoformat()}))
    """
)


def _stored_ts_under(tz: str) -> dict[str, str]:
    env = {
        **os.environ,
        "TZ": tz,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(REPO_ROOT),
    }
    result = subprocess.run(
        [sys.executable, "-B", "-c", _TZ_SCRIPT],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("tz", ["America/New_York", "UTC", "Asia/Tokyo"])
def test_ts_is_stored_as_utc_regardless_of_host_timezone(tz):
    """The 00:00Z window key is stored as 00:00 under every host TZ, not 20:00/09:00."""
    stored = _stored_ts_under(tz)
    assert stored["raw_ts"] == "2024-07-05 00:00:00"
    assert stored["queried"] == "2024-07-05T00:00:00+00:00"


def test_persist_heuristic_writes_rule_provenance(con):
    written = persist_predictions(con, [_heuristic_record()], fixture_batch_id=BATCH)

    assert written == 1
    prov = con.execute(
        "SELECT model_kind, rule_id, rule_version FROM prediction_provenance"
    ).fetchone()
    assert prov == ("heuristic", "cold-front", "2")
    row = con.execute(
        "SELECT source_name, source_ref, source_version FROM outage_predictions"
    ).fetchone()
    assert row == ("models.outage", "heuristic:cold-front", "2")


def test_unavailable_prediction_is_not_persisted(con):
    written = persist_predictions(con, [_unavailable_record()], fixture_batch_id=BATCH)

    assert written == 0
    assert _count(con, "outage_predictions") == 0
    assert _count(con, "prediction_provenance") == 0


def test_trained_model_without_artifact_is_rejected_by_contract_before_persistence():
    """An incomplete trained-model claim is rejected at the contract level."""
    with pytest.raises(ValidationError):
        TrainedModelPrediction(p_out=0.4, customers_at_risk=100, driver=Driver.ICE)


def test_fixture_batch_id_is_required(con):
    _seed_qualified(con)
    with pytest.raises(PersistenceError, match="fixture_batch_id"):
        persist_predictions(con, [_trained_record()], fixture_batch_id="  ")
    assert _count(con, "outage_predictions") == 0


# --- qualification gate ------------------------------------------------------


def test_trained_prediction_without_evaluation_is_refused(con):
    with pytest.raises(UnqualifiedEvaluationError, match="cites no evaluation"):
        persist_predictions(
            con, [_trained_record(evaluation=None)], fixture_batch_id=BATCH
        )
    assert _count(con, "outage_predictions") == 0


def test_trained_prediction_citing_unpersisted_evaluation_is_refused(con):
    """P5c: the cited evaluation hash was never persisted."""
    with pytest.raises(UnqualifiedEvaluationError, match="not persisted"):
        persist_predictions(con, [_trained_record()], fixture_batch_id=BATCH)
    assert _count(con, "outage_predictions") == 0


def test_trained_prediction_citing_unavailable_evaluation_is_refused(con):
    """P5d: an UNAVAILABLE evaluation cannot back a trained-model row."""
    persist_evaluation(con, UNAVAILABLE_EVAL, evidence=UNAVAILABLE_EVIDENCE)
    record = _trained_record(
        evaluation=QUALIFIED_REF.model_copy(
            update={"evaluation_sha256": UNAVAILABLE_EVAL.evaluation_sha256}
        )
    )
    with pytest.raises(UnqualifiedEvaluationError, match="evaluation_unavailable"):
        persist_predictions(con, [record], fixture_batch_id=BATCH)
    assert _count(con, "outage_predictions") == 0


def test_trained_prediction_citing_failing_brier_evaluation_is_refused(con):
    """P5e: READY but Brier 0.17 > spec-02 acceptance 0.12."""
    persist_evaluation(con, FAILING_EVAL, evidence=FAILING_EVIDENCE)
    record = _trained_record(evaluation=FAILING_EVAL.to_ref())
    with pytest.raises(UnqualifiedEvaluationError, match="brier_above_acceptance"):
        persist_predictions(con, [record], fixture_batch_id=BATCH)
    assert _count(con, "outage_predictions") == 0


def test_trained_prediction_citing_another_models_evaluation_is_refused(con):
    """A qualified evaluation of model F cannot back a prediction from model A."""
    persist_evaluation(con, OTHER_MODEL_EVAL, evidence=OTHER_MODEL_EVIDENCE)
    record = _trained_record(evaluation=OTHER_MODEL_EVAL.to_ref())
    with pytest.raises(UnqualifiedEvaluationError, match="different model artifact"):
        persist_predictions(con, [record], fixture_batch_id=BATCH)
    assert _count(con, "outage_predictions") == 0


def test_qualified_prediction_persists_and_is_queryable_as_qualified(con):
    _seed_qualified(con)
    assert persist_predictions(con, [_trained_record()], fixture_batch_id=BATCH) == 1
    (row,) = query_predictions(con, scenario_id="beryl_2024")
    assert row["qualified"] is True
    assert row["qualification_reason"] is None
    assert row["evaluation_status"] == "ready"


# --- batches -----------------------------------------------------------------


def test_batch_is_all_or_nothing(con):
    """P4: a constraint failure on the second record leaves nothing behind."""
    _seed_qualified(con)
    bad_scenario = _trained_record(
        key=WindowKey(
            county_fips="48453",
            scenario_id="nope",
            window_start=datetime(2024, 7, 5, 12, tzinfo=UTC),
        )
    )
    with pytest.raises(PersistenceError, match="rolled back"):
        persist_predictions(
            con, [_trained_record(), bad_scenario], fixture_batch_id=BATCH
        )
    assert _count(con, "outage_predictions") == 0
    assert _count(con, "prediction_provenance") == 0
    # The connection is usable afterwards.
    assert persist_predictions(con, [_trained_record()], fixture_batch_id=BATCH) == 1


def test_persist_requires_scenario_and_county_parents(con):
    """P2: the real DDL's foreign keys are enforced, not bypassed."""
    _seed_qualified(con)
    unknown_county = _trained_record(
        key=WindowKey(
            county_fips="99999",
            scenario_id="beryl_2024",
            window_start=datetime(2024, 7, 5, 0, tzinfo=UTC),
        )
    )
    with pytest.raises(PersistenceError, match="rolled back"):
        persist_predictions(con, [unknown_county], fixture_batch_id=BATCH)
    assert _count(con, "outage_predictions") == 0


def test_duplicate_key_in_batch_is_refused(con):
    """P8: two records for one key in a batch is a named error, not last-wins."""
    _seed_qualified(con)
    with pytest.raises(PersistenceError, match="duplicate prediction key"):
        persist_predictions(
            con,
            [_trained_record(p_out=0.1), _trained_record(p_out=0.9)],
            fixture_batch_id=BATCH,
        )
    assert _count(con, "outage_predictions") == 0


def test_mixed_predictions_persist_only_available_rows(con):
    _seed_qualified(con)
    records = [
        _trained_record(),
        _heuristic_record(key=KEY_2),
        _unavailable_record(KEY_3),
    ]
    written = persist_predictions(con, records, fixture_batch_id=BATCH)

    assert written == 2
    assert _count(con, "outage_predictions") == 2
    kinds = {
        r[0]
        for r in con.execute("SELECT model_kind FROM prediction_provenance").fetchall()
    }
    assert kinds == {"lightgbm", "heuristic"}


def test_persist_predictions_is_idempotent(con):
    _seed_qualified(con)
    persist_predictions(con, [_trained_record()], fixture_batch_id=BATCH)
    persist_predictions(con, [_trained_record()], fixture_batch_id=BATCH)

    assert _count(con, "outage_predictions") == 1
    assert _count(con, "prediction_provenance") == 1


# ---------------------------------------------------------------------------
# Query predictions
# ---------------------------------------------------------------------------


def test_fixture_query_returns_all_rows_for_a_scenario(con):
    _seed_qualified(con)
    persist_predictions(
        con, [_trained_record(), _heuristic_record(key=KEY_2)], fixture_batch_id=BATCH
    )

    results = query_predictions(con, scenario_id="beryl_2024")
    assert len(results) == 2
    assert {r["model_kind"] for r in results} == {"lightgbm", "heuristic"}
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
            "persisted_at",
            "evaluation_status",
            "qualified",
            "qualification_reason",
        }


def test_query_returns_each_rows_driver_and_utc_aware_ts(con):
    _seed_qualified(con)
    persist_predictions(
        con, [_trained_record(), _heuristic_record(key=KEY_2)], fixture_batch_id=BATCH
    )
    by_ts = {r["ts"]: r for r in query_predictions(con, scenario_id="beryl_2024")}
    assert set(by_ts) == {KEY.window_start, KEY_2.window_start}
    assert by_ts[KEY.window_start]["driver"] == "ice"
    assert by_ts[KEY_2.window_start]["driver"] == "wind"
    assert all(ts.tzinfo is UTC for ts in by_ts)


def test_trained_model_query_filters_by_model_kind(con):
    _seed_qualified(con)
    persist_predictions(
        con, [_trained_record(), _heuristic_record(key=KEY_2)], fixture_batch_id=BATCH
    )

    results = query_predictions(con, scenario_id="beryl_2024", model_kind="lightgbm")
    assert len(results) == 1
    assert results[0]["model_kind"] == "lightgbm"
    assert results[0]["artifact_sha256"] == H
    assert results[0]["model_version"] == "lgbm-1"
    assert results[0]["evaluation_sha256"] == QUALIFIED_EVAL.evaluation_sha256

    results = query_predictions(con, scenario_id="beryl_2024", model_kind="heuristic")
    assert len(results) == 1
    assert results[0]["model_kind"] == "heuristic"
    assert results[0]["rule_id"] == "cold-front"
    assert results[0]["rule_version"] == "2"
    assert results[0]["qualified"] is None
    assert results[0]["evaluation_status"] is None


def test_query_by_county_fips(con):
    _seed_qualified(con)
    persist_predictions(con, [_trained_record()], fixture_batch_id=BATCH)

    assert len(query_predictions(con, county_fips="48453")) == 1
    assert query_predictions(con, county_fips="99999") == []


def _ten_windows() -> list[PredictionRecord]:
    return [
        _trained_record(
            key=WindowKey(
                county_fips="48453",
                scenario_id="s",
                window_start=datetime(2024, 7, 5 + d, 0, tzinfo=UTC),
            )
        )
        for d in range(10)
    ]


def test_query_is_bounded_by_limit(con):
    _seed_qualified(con)
    persist_predictions(con, _ten_windows(), fixture_batch_id=BATCH)

    assert len(query_predictions(con, scenario_id="s", limit=3)) == 3


@pytest.mark.parametrize("limit", [0, -1, MAX_QUERY_LIMIT + 1])
def test_query_rejects_out_of_range_limit(con, limit):
    with pytest.raises(PersistenceError, match="limit"):
        query_predictions(con, limit=limit)


def test_query_rejects_unknown_model_kind(con):
    with pytest.raises(PersistenceError, match="model_kind"):
        query_predictions(con, model_kind="bogus")


def test_query_never_returns_unavailable(con):
    """Unavailable predictions are never in the table, so no query can return one."""
    _seed_qualified(con)
    persist_predictions(
        con, [_trained_record(), _unavailable_record(KEY_2)], fixture_batch_id=BATCH
    )

    results = query_predictions(con, scenario_id="beryl_2024")
    assert len(results) == 1
    assert results[0]["model_kind"] == "lightgbm"


def test_query_is_ordered_by_key_not_insertion(con):
    """Rows inserted out of order come back ordered by (scenario_id, county_fips, ts)."""
    _seed_qualified(con)
    windows = _ten_windows()
    persist_predictions(con, list(reversed(windows)), fixture_batch_id=BATCH)
    persist_predictions(
        con, [_trained_record()], fixture_batch_id=BATCH
    )  # 'beryl_2024' < 's'

    results = query_predictions(con)
    assert [r["scenario_id"] for r in results] == ["beryl_2024"] + ["s"] * 10
    assert [r["ts"] for r in results[1:]] == [w.key.window_start for w in windows]
    assert results == query_predictions(con)


def test_query_preserves_heuristic_distinction(con):
    """A heuristic result is labelled as heuristic, not as a trained model."""
    persist_predictions(con, [_heuristic_record()], fixture_batch_id=BATCH)

    results = query_predictions(con, scenario_id="beryl_2024")
    assert len(results) == 1
    assert results[0]["model_kind"] == "heuristic"
    assert results[0]["rule_id"] == "cold-front"
    assert results[0]["artifact_sha256"] is None


# ---------------------------------------------------------------------------
# Persist and query evaluation
# ---------------------------------------------------------------------------


def test_qualification_follows_spec_02_acceptance():
    assert BRIER_ACCEPTANCE == 0.12
    assert qualify_evaluation(QUALIFIED_EVAL).qualified is True
    failing = qualify_evaluation(FAILING_EVAL)
    assert failing.qualified is False
    assert failing.reason.startswith("brier_above_acceptance:")
    unavailable = qualify_evaluation(UNAVAILABLE_EVAL)
    assert unavailable.qualified is False
    assert unavailable.reason == "evaluation_unavailable:insufficient_holdout_records"
    partial = QUALIFIED_EVAL.model_copy(
        update={"coverage": QUALIFIED_EVAL.coverage.model_copy(update={"scored": 2})}
    )
    assert qualify_evaluation(partial).reason == "incomplete_holdout_coverage:2/3"


def test_persist_and_query_evaluation(con):
    qualification = persist_evaluation(con, QUALIFIED_EVAL, evidence=QUALIFIED_EVIDENCE)
    assert qualification.qualified is True

    result = query_evaluation(con, QUALIFIED_EVAL.evaluation_sha256)
    assert result is not None
    assert result["status"] == "ready"
    assert result["qualified"] is True
    assert result["qualification_reason"] is None
    assert result["reason"] is None
    assert result["model_artifact_sha256"] == H
    assert result["model_version"] == "lgbm-1"
    assert result["split_input_artifact_sha256"] == H
    assert result["calibration_method"] == "isotonic"
    assert result["calibration_status"] == "reported"
    assert result["uncertainty_method"] == "bootstrap"
    assert json.loads(result["coverage_json"]) == QUALIFIED_EVAL.coverage.model_dump(
        mode="json"
    )
    assert json.loads(result["metrics_json"]) == QUALIFIED_EVAL.metrics.model_dump(
        mode="json"
    )
    assert result["persisted_at"].tzinfo is UTC


def test_persist_evaluation_rejects_hash_that_does_not_match_content(con):
    tampered_hash = QUALIFIED_EVAL.model_copy(update={"evaluation_sha256": "c" * 64})
    with pytest.raises(PersistenceError, match="evaluation_sha256 does not match"):
        persist_evaluation(con, tampered_hash, evidence=QUALIFIED_EVIDENCE)

    better_brier = QUALIFIED_EVAL.model_copy(
        update={
            "metrics": QUALIFIED_EVAL.metrics.model_copy(update={"brier_score": 0.001})
        }
    )
    with pytest.raises(PersistenceError, match="evaluation_sha256 does not match"):
        persist_evaluation(con, better_brier, evidence=QUALIFIED_EVIDENCE)

    with pytest.raises(PersistenceError, match="evaluation_sha256 does not match"):
        persist_evaluation(con, QUALIFIED_EVAL, evidence=FAILING_EVIDENCE)
    assert _count(con, "evaluation_artifacts") == 0


def test_persist_evaluation_rejects_evidence_for_another_model_or_split(con):
    with pytest.raises(PersistenceError, match="model_artifact_sha256"):
        persist_evaluation(con, QUALIFIED_EVAL, evidence=OTHER_MODEL_EVIDENCE)
    other_split = SPLIT.model_copy(update={"split_id": "0" * 64})
    with pytest.raises(PersistenceError, match="split_id"):
        persist_evaluation(
            con,
            QUALIFIED_EVAL,
            evidence=EvaluationEvidence(ARTIFACT, other_split, GOOD_PREDICTIONS),
        )
    assert _count(con, "evaluation_artifacts") == 0


def test_failing_ready_evaluation_is_recorded_as_unqualified(con):
    """P5a: a READY evaluation above the Brier acceptance is stored, flagged, and cannot qualify."""
    qualification = persist_evaluation(con, FAILING_EVAL, evidence=FAILING_EVIDENCE)
    assert qualification.qualified is False
    result = query_evaluation(con, FAILING_EVAL.evaluation_sha256)
    assert result["status"] == "ready"
    assert result["qualified"] is False
    assert result["qualification_reason"] == "brier_above_acceptance:0.1700 > 0.12"


def test_query_evaluation_returns_none_for_missing_hash(con):
    assert query_evaluation(con, "c" * 64) is None


def test_query_evaluation_rejects_malformed_hash(con):
    with pytest.raises(PersistenceError, match="not a SHA-256"):
        query_evaluation(con, "not-a-hash")


def test_persist_evaluation_is_idempotent(con):
    persist_evaluation(con, QUALIFIED_EVAL, evidence=QUALIFIED_EVIDENCE)
    persist_evaluation(con, QUALIFIED_EVAL, evidence=QUALIFIED_EVIDENCE)

    assert _count(con, "evaluation_artifacts") == 1


def test_no_query_path_recomputes_evaluation(con):
    """The evaluation query reads stored metrics verbatim; it never recomputes them."""
    persist_evaluation(con, QUALIFIED_EVAL, evidence=QUALIFIED_EVIDENCE)
    con.execute(
        "UPDATE evaluation_artifacts SET metrics_json = ?::JSON WHERE evaluation_sha256 = ?",
        [
            json.dumps({"brier_score": 0.99, "tampered": True}),
            QUALIFIED_EVAL.evaluation_sha256,
        ],
    )

    result = query_evaluation(con, QUALIFIED_EVAL.evaluation_sha256)
    assert json.loads(result["metrics_json"]) == {"brier_score": 0.99, "tampered": True}


def test_unavailable_evaluation_is_persisted_with_reason(con):
    """P5b: an UNAVAILABLE evaluation is a stored fact, flagged unqualified, with NULL metrics."""
    qualification = persist_evaluation(
        con, UNAVAILABLE_EVAL, evidence=UNAVAILABLE_EVIDENCE
    )
    assert qualification.qualified is False

    result = query_evaluation(con, UNAVAILABLE_EVAL.evaluation_sha256)
    assert result is not None
    assert result["status"] == "unavailable"
    assert result["qualified"] is False
    assert (
        result["qualification_reason"]
        == "evaluation_unavailable:insufficient_holdout_records"
    )
    assert result["reason"] == "insufficient_holdout_records"
    assert result["metrics_json"] is None
    assert result["model_version"] is None
    assert result["split_input_artifact_sha256"] is None
    assert result["calibration_status"] == "not_applicable"
    assert json.loads(result["coverage_json"]) == {
        "holdout_size": 3,
        "scored": 0,
        "coverage": 0.0,
    }
    assert EvaluationStatus(result["status"]) is EvaluationStatus.UNAVAILABLE

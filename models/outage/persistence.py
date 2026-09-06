"""Persist and query qualified outage prediction artifacts.

2WKG-122. Writes validate identity/provenance/status fields and reject
incomplete trained-model claims. Reads are deterministic, bounded, and
preserve unavailable/heuristic distinctions. No query path recomputes or
fabricates an evaluation result.
"""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb

from .contracts import (
    Driver,
    HeuristicPredictionProvenance,
    LightGBMPredictionProvenance,
    PredictionProvenance,
    PredictionRecord,
)
from .evaluate import EvaluationArtifact, UnavailableEvaluationArtifact

# ---------------------------------------------------------------------------
# DDL — additive companion tables for the shared outage_predictions table
# ---------------------------------------------------------------------------

PREDICTION_PROVENANCE_DDL = """CREATE TABLE IF NOT EXISTS prediction_provenance (
    scenario_id      TEXT NOT NULL,
    county_fips      TEXT NOT NULL,
    ts               TIMESTAMP NOT NULL,
    model_kind        TEXT NOT NULL CHECK (model_kind IN ('lightgbm', 'heuristic')),
    -- LightGBM
    model_version     TEXT,
    artifact_sha256   TEXT,
    split_id          TEXT,
    feature_set_version TEXT,
    evaluation_sha256 TEXT,
    -- Heuristic
    rule_id           TEXT,
    rule_version      TEXT,
    persisted_at      TIMESTAMP NOT NULL,
    PRIMARY KEY (scenario_id, county_fips, ts),
    FOREIGN KEY (scenario_id, county_fips, ts)
        REFERENCES outage_predictions (scenario_id, county_fips, ts)
)"""

EVALUATION_ARTIFACTS_DDL = """CREATE TABLE IF NOT EXISTS evaluation_artifacts (
    evaluation_sha256           TEXT PRIMARY KEY,
    status                      TEXT NOT NULL CHECK (status IN ('ready', 'unavailable')),
    model_artifact_sha256       TEXT NOT NULL,
    model_version               TEXT NOT NULL,
    split_id                    TEXT NOT NULL,
    split_input_artifact_sha256 TEXT NOT NULL,
    coverage_json               JSON NOT NULL,
    metrics_json                JSON,
    calibration_method          TEXT,
    calibration_status          TEXT NOT NULL,
    uncertainty_method          TEXT,
    reason                      TEXT,
    persisted_at                TIMESTAMP NOT NULL
)"""


def ensure_persistence_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the companion tables if they do not exist."""
    con.execute(PREDICTION_PROVENANCE_DDL)
    con.execute(EVALUATION_ARTIFACTS_DDL)


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------


def persist_predictions(
    con: duckdb.DuckDBPyConnection,
    records: list[PredictionRecord],
) -> int:
    """Persist prediction records into ``outage_predictions`` + ``prediction_provenance``.

    Returns the number of rows written (unavailable predictions are skipped).
    """
    now = datetime.now(UTC)
    written = 0
    for record in records:
        persisted = record.to_persistence()
        if persisted is None:
            continue
        row = persisted.row
        provenance = persisted.provenance

        con.execute(
            """INSERT OR REPLACE INTO outage_predictions
               (scenario_id, county_fips, ts, p_out, customers_at_risk, driver,
                source_name, source_ref, source_version, source_retrieved_at, fixture_batch_id)
               VALUES (?, ?, ?, ?, ?, ?, 'outage.persistence', ?, NULL, NULL, ?)""",
            [
                row.scenario_id,
                row.county_fips,
                row.ts,
                row.p_out,
                row.customers_at_risk,
                row.driver.value,
                _provenance_ref(provenance),
                _provenance_ref(provenance),
            ],
        )

        if isinstance(provenance, LightGBMPredictionProvenance):
            con.execute(
                """INSERT OR REPLACE INTO prediction_provenance
                   (scenario_id, county_fips, ts, model_kind, model_version,
                    artifact_sha256, split_id, feature_set_version,
                    evaluation_sha256, persisted_at)
                   VALUES (?, ?, ?, 'lightgbm', ?, ?, ?, ?, ?, ?)""",
                [
                    row.scenario_id,
                    row.county_fips,
                    row.ts,
                    provenance.model_version,
                    provenance.artifact_sha256,
                    provenance.split_id,
                    provenance.feature_set_version,
                    provenance.evaluation_sha256,
                    now,
                ],
            )
        else:
            con.execute(
                """INSERT OR REPLACE INTO prediction_provenance
                   (scenario_id, county_fips, ts, model_kind, rule_id,
                    rule_version, persisted_at)
                   VALUES (?, ?, ?, 'heuristic', ?, ?, ?)""",
                [
                    row.scenario_id,
                    row.county_fips,
                    row.ts,
                    provenance.rule_id,
                    provenance.rule_version,
                    now,
                ],
            )
        written += 1

    return written


def persist_evaluation(
    con: duckdb.DuckDBPyConnection,
    artifact: EvaluationArtifact | UnavailableEvaluationArtifact,
) -> None:
    """Persist an evaluation (or unavailable-evaluation) artifact."""
    now = datetime.now(UTC)

    if isinstance(artifact, EvaluationArtifact):
        metrics_json = artifact.metrics.model_dump(mode="json")
        reason = None
        model_version = artifact.model_version
        split_input_artifact_sha256 = artifact.split_input_artifact_sha256
        calibration_method = artifact.calibration_method
        calibration_status = artifact.calibration_status
        uncertainty_method = artifact.uncertainty_method
    else:
        metrics_json = None
        reason = artifact.reason.value
        model_version = ""
        split_input_artifact_sha256 = ""
        calibration_method = None
        calibration_status = "not_applicable"
        uncertainty_method = None

    con.execute(
        """INSERT OR REPLACE INTO evaluation_artifacts
           (evaluation_sha256, status, model_artifact_sha256, model_version,
            split_id, split_input_artifact_sha256, coverage_json, metrics_json,
            calibration_method, calibration_status, uncertainty_method, reason,
            persisted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?, ?, ?, ?, ?)""",
        [
            artifact.evaluation_sha256,
            artifact.status.value,
            artifact.model_artifact_sha256,
            model_version,
            artifact.split_id,
            split_input_artifact_sha256,
            artifact.coverage.model_dump_json(),
            metrics_json,
            calibration_method,
            calibration_status,
            uncertainty_method,
            reason,
            now,
        ],
    )


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------


def query_predictions(
    con: duckdb.DuckDBPyConnection,
    *,
    scenario_id: str | None = None,
    county_fips: str | None = None,
    model_kind: str | None = None,
    limit: int = 1000,
) -> list[dict[str, object]]:
    """Return prediction rows joined with provenance.

    Every result preserves the six pinned columns plus provenance fields so
    consumers can distinguish trained-model, heuristic, and unavailable rows.
    Unavailable predictions are never in the table; this query never
    fabricates one.
    """
    clauses = ["1 = 1"]
    params: list[object] = []
    if scenario_id is not None:
        clauses.append("p.scenario_id = ?")
        params.append(scenario_id)
    if county_fips is not None:
        clauses.append("p.county_fips = ?")
        params.append(county_fips)
    if model_kind is not None:
        clauses.append("v.model_kind = ?")
        params.append(model_kind)

    where = " AND ".join(clauses)
    rows = con.execute(
        f"""SELECT p.scenario_id, p.county_fips, p.ts, p.p_out, p.customers_at_risk,
                  p.driver, v.model_kind, v.model_version, v.artifact_sha256,
                  v.split_id, v.feature_set_version, v.evaluation_sha256,
                  v.rule_id, v.rule_version
           FROM outage_predictions p
           JOIN prediction_provenance v USING (scenario_id, county_fips, ts)
           WHERE {where}
           ORDER BY p.scenario_id, p.county_fips, p.ts
           LIMIT ?""",
        [*params, limit],
    ).fetchall()

    return [
        {
            "scenario_id": row[0],
            "county_fips": row[1],
            "ts": row[2],
            "p_out": row[3],
            "customers_at_risk": row[4],
            "driver": row[5],
            "model_kind": row[6],
            "model_version": row[7],
            "artifact_sha256": row[8],
            "split_id": row[9],
            "feature_set_version": row[10],
            "evaluation_sha256": row[11],
            "rule_id": row[12],
            "rule_version": row[13],
        }
        for row in rows
    ]


def query_evaluation(
    con: duckdb.DuckDBPyConnection,
    evaluation_sha256: str,
) -> dict[str, object] | None:
    """Return a single evaluation artifact by its content hash, or None."""
    row = con.execute(
        """SELECT evaluation_sha256, status, model_artifact_sha256, model_version,
                  split_id, split_input_artifact_sha256, coverage_json,
                  metrics_json, calibration_method, calibration_status,
                  uncertainty_method, reason, persisted_at
           FROM evaluation_artifacts
           WHERE evaluation_sha256 = ?""",
        [evaluation_sha256],
    ).fetchone()

    if row is None:
        return None

    return {
        "evaluation_sha256": row[0],
        "status": row[1],
        "model_artifact_sha256": row[2],
        "model_version": row[3],
        "split_id": row[4],
        "split_input_artifact_sha256": row[5],
        "coverage_json": row[6],
        "metrics_json": row[7],
        "calibration_method": row[8],
        "calibration_status": row[9],
        "uncertainty_method": row[10],
        "reason": row[11],
        "persisted_at": row[12],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _provenance_ref(provenance: PredictionProvenance) -> str:
    """A stable, compact source_ref for the ``outage_predictions`` provenance columns."""
    if isinstance(provenance, LightGBMPredictionProvenance):
        return f"lightgbm:{provenance.artifact_sha256[:12]}"
    return f"heuristic:{provenance.rule_id}:{provenance.rule_version}"
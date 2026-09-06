"""Persist and query qualified outage prediction artifacts.

2WKG-122. The write path only stores a trained-model prediction when it cites an
evaluation artifact that is already persisted, whose ``evaluation_sha256`` was
re-derived from its evidence at persist time, and which is *qualified*: status
READY, complete holdout coverage, and ``brier_score <= BRIER_ACCEPTANCE`` (spec
02, acceptance criterion 5: "``brier ≤ 0.12``"). Anything else raises a named
error; nothing is written. Batches are all-or-nothing. Timestamps are stored as
naive UTC in the shared ``TIMESTAMP`` columns and returned UTC-aware, so the
spec-02 "6-h aligned UTC" window key never depends on the host timezone. Reads
are deterministic (ordered by key), bounded (``1 <= limit <= MAX_QUERY_LIMIT``)
and preserve the trained/heuristic distinction. No query path recomputes or
fabricates an evaluation result.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

import duckdb

from pipelines.db import SCHEMA_VERSION, ensure_schema, stored_contract_version

from .contracts import (
    LightGBMPredictionProvenance,
    ModelArtifact,
    PredictionProvenance,
    PredictionRecord,
    SplitManifest,
)
from .evaluate import (
    EvaluationArtifact,
    EvaluationStatus,
    HeldoutPrediction,
    UnavailableEvaluationArtifact,
    _evaluation_sha256,
)

BRIER_ACCEPTANCE: Final = 0.12
"""docs/specs/02-outage-model.md, acceptance criterion 5: ``brier <= 0.12``."""

MAX_QUERY_LIMIT: Final = 10_000
"""Upper bound on ``query_predictions(limit=...)``; larger reads must page."""

SOURCE_NAME: Final = "models.outage"
"""``outage_predictions.source_name`` for rows written by this module."""

MODEL_KINDS: Final = ("lightgbm", "heuristic")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PersistenceError(ValueError):
    """The write or read cannot be performed honestly; nothing was persisted."""


class PersistenceContractError(PersistenceError):
    """The database is on a different shared-contract version."""


class UnqualifiedEvaluationError(PersistenceError):
    """A trained-model prediction cites no qualified, persisted evaluation."""


class QualificationReason(StrEnum):
    EVALUATION_UNAVAILABLE = "evaluation_unavailable"
    INCOMPLETE_HOLDOUT_COVERAGE = "incomplete_holdout_coverage"
    BRIER_ABOVE_ACCEPTANCE = "brier_above_acceptance"


@dataclass(frozen=True)
class Qualification:
    """Whether an evaluation artifact may back a persisted trained-model prediction."""

    qualified: bool
    reason: str | None


@dataclass(frozen=True)
class EvaluationEvidence:
    """The inputs an evaluation digest was derived from; required to persist it."""

    model: ModelArtifact
    split: SplitManifest
    predictions: tuple[HeldoutPrediction, ...]


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
    evaluation_sha256           TEXT PRIMARY KEY
        CHECK (regexp_full_match(evaluation_sha256, '[0-9a-f]{64}')),
    status                      TEXT NOT NULL CHECK (status IN ('ready', 'unavailable')),
    qualified                   BOOLEAN NOT NULL,
    qualification_reason        TEXT,
    model_artifact_sha256       TEXT NOT NULL,
    model_version               TEXT,
    split_id                    TEXT NOT NULL,
    split_input_artifact_sha256 TEXT,
    coverage_json               JSON NOT NULL,
    metrics_json                JSON,
    calibration_method          TEXT,
    calibration_status          TEXT NOT NULL,
    uncertainty_method          TEXT,
    reason                      TEXT,
    persisted_at                TIMESTAMP NOT NULL,
    CHECK ((status = 'unavailable') = (metrics_json IS NULL)),
    CHECK ((status = 'unavailable') = (model_version IS NULL)),
    CHECK (qualified = (qualification_reason IS NULL))
)"""


def ensure_persistence_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the companion tables on top of the shared ``pipelines.db`` contract.

    Goes through :func:`pipelines.db.ensure_schema` so ``outage_predictions`` has
    its real ``scenarios``/``counties`` foreign keys, and refuses a database whose
    ``schema_meta.contract_version`` is not :data:`pipelines.db.SCHEMA_VERSION`.
    """
    existing = stored_contract_version(con)
    if existing is not None and existing != SCHEMA_VERSION:
        raise PersistenceContractError(
            f"DuckDB contract version is {existing!r}, expected {SCHEMA_VERSION!r}; "
            "outage persistence refuses to write to a foreign contract"
        )
    ensure_schema(con)
    con.execute(PREDICTION_PROVENANCE_DDL)
    con.execute(EVALUATION_ARTIFACTS_DDL)


# ---------------------------------------------------------------------------
# Qualification
# ---------------------------------------------------------------------------


def qualify_evaluation(
    artifact: EvaluationArtifact | UnavailableEvaluationArtifact,
) -> Qualification:
    """Decide whether ``artifact`` meets spec 02's acceptance for a trained model."""
    if isinstance(artifact, UnavailableEvaluationArtifact):
        return Qualification(
            False, f"{QualificationReason.EVALUATION_UNAVAILABLE}:{artifact.reason}"
        )
    if artifact.status is not EvaluationStatus.READY:
        return Qualification(
            False, f"{QualificationReason.EVALUATION_UNAVAILABLE}:{artifact.status}"
        )
    if not artifact.coverage.is_complete:
        return Qualification(
            False,
            f"{QualificationReason.INCOMPLETE_HOLDOUT_COVERAGE}:"
            f"{artifact.coverage.scored}/{artifact.coverage.holdout_size}",
        )
    if artifact.metrics.brier_score > BRIER_ACCEPTANCE:
        return Qualification(
            False,
            f"{QualificationReason.BRIER_ABOVE_ACCEPTANCE}:"
            f"{artifact.metrics.brier_score:.4f} > {BRIER_ACCEPTANCE}",
        )
    return Qualification(True, None)


def verify_evaluation_content(
    artifact: EvaluationArtifact | UnavailableEvaluationArtifact,
    evidence: EvaluationEvidence,
) -> None:
    """Re-derive ``evaluation_sha256`` from the evidence; raise on any mismatch."""
    if artifact.model_artifact_sha256 != evidence.model.artifact_sha256:
        raise PersistenceError(
            "evaluation model_artifact_sha256 does not match the evidence model"
        )
    if artifact.split_id != evidence.split.split_id:
        raise PersistenceError("evaluation split_id does not match the evidence split")
    if isinstance(artifact, EvaluationArtifact):
        if artifact.model_version != evidence.model.model_version:
            raise PersistenceError(
                "evaluation model_version does not match the evidence model"
            )
        if artifact.split_input_artifact_sha256 != evidence.split.input_artifact_sha256:
            raise PersistenceError(
                "evaluation split_input_artifact_sha256 does not match the evidence split"
            )
        expected = _evaluation_sha256(
            evidence.model,
            evidence.split,
            evidence.predictions,
            artifact.coverage,
            artifact.calibration_method,
            artifact.uncertainty_method,
            artifact.metrics,
            None,
        )
    else:
        expected = _evaluation_sha256(
            evidence.model,
            evidence.split,
            evidence.predictions,
            artifact.coverage,
            None,
            None,
            None,
            artifact.reason,
        )
    if expected != artifact.evaluation_sha256:
        raise PersistenceError(
            "evaluation_sha256 does not match the evaluation content and evidence"
        )


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------


def persist_predictions(
    con: duckdb.DuckDBPyConnection,
    records: list[PredictionRecord],
    *,
    fixture_batch_id: str,
) -> int:
    """Persist prediction records into ``outage_predictions`` + ``prediction_provenance``.

    Unavailable predictions are skipped (a row means "the model produced a
    number"). Every trained-model record must cite a persisted, qualified
    evaluation for its own model artifact and split, otherwise
    :class:`UnqualifiedEvaluationError` is raised before anything is written.
    The batch is one transaction: a constraint failure on any record rolls back
    the whole batch and raises :class:`PersistenceError`. Returns the number of
    prediction rows written.
    """
    if not fixture_batch_id.strip():
        raise PersistenceError("fixture_batch_id must not be empty")
    now = _to_utc_naive(datetime.now(UTC), "persisted_at")

    planned: list[tuple[tuple[str, str, datetime], object, PredictionProvenance]] = []
    seen: set[tuple[str, str, datetime]] = set()
    for record in records:
        persisted = record.to_persistence()
        if persisted is None:
            continue
        row = persisted.row
        ts = _to_utc_naive(row.ts, "ts")
        key = (row.scenario_id, row.county_fips, ts)
        if key in seen:
            raise PersistenceError(f"duplicate prediction key in batch: {key!r}")
        seen.add(key)
        if isinstance(persisted.provenance, LightGBMPredictionProvenance):
            _require_qualified_evaluation(con, persisted.provenance)
        planned.append((key, row, persisted.provenance))

    if not planned:
        return 0

    con.begin()
    try:
        for (scenario_id, county_fips, ts), row, provenance in planned:
            con.execute(
                """INSERT OR REPLACE INTO outage_predictions
                   (scenario_id, county_fips, ts, p_out, customers_at_risk, driver,
                    source_name, source_ref, source_version, source_retrieved_at,
                    fixture_batch_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                [
                    scenario_id,
                    county_fips,
                    ts,
                    row.p_out,
                    row.customers_at_risk,
                    row.driver.value,
                    SOURCE_NAME,
                    _source_ref(provenance),
                    _source_version(provenance),
                    fixture_batch_id,
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
                        scenario_id,
                        county_fips,
                        ts,
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
                        scenario_id,
                        county_fips,
                        ts,
                        provenance.rule_id,
                        provenance.rule_version,
                        now,
                    ],
                )
        con.commit()
    except duckdb.Error as error:
        con.rollback()
        raise PersistenceError(
            f"prediction batch rolled back, nothing written: {error}"
        ) from error
    return len(planned)


def persist_evaluation(
    con: duckdb.DuckDBPyConnection,
    artifact: EvaluationArtifact | UnavailableEvaluationArtifact,
    *,
    evidence: EvaluationEvidence,
) -> Qualification:
    """Persist an evaluation (or unavailable-evaluation) artifact with its qualification.

    The artifact's ``evaluation_sha256`` is re-derived from ``evidence`` first; a
    mismatch raises :class:`PersistenceError`. Unqualified artifacts *are*
    recorded (with ``qualified = FALSE`` and a reason) so the fact is queryable,
    but no trained-model prediction may cite them.
    """
    verify_evaluation_content(artifact, evidence)
    qualification = qualify_evaluation(artifact)
    now = _to_utc_naive(datetime.now(UTC), "persisted_at")

    if isinstance(artifact, EvaluationArtifact):
        metrics_json = artifact.metrics.model_dump_json()
        reason = None
        model_version = artifact.model_version
        split_input_artifact_sha256 = artifact.split_input_artifact_sha256
        calibration_method = artifact.calibration_method
        calibration_status = artifact.calibration_status
        uncertainty_method = artifact.uncertainty_method
    else:
        metrics_json = None
        reason = artifact.reason.value
        model_version = None
        split_input_artifact_sha256 = None
        calibration_method = None
        calibration_status = "not_applicable"
        uncertainty_method = None

    con.execute(
        """INSERT OR REPLACE INTO evaluation_artifacts
           (evaluation_sha256, status, qualified, qualification_reason,
            model_artifact_sha256, model_version, split_id,
            split_input_artifact_sha256, coverage_json, metrics_json,
            calibration_method, calibration_status, uncertainty_method, reason,
            persisted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?, ?, ?, ?, ?)""",
        [
            artifact.evaluation_sha256,
            artifact.status.value,
            qualification.qualified,
            qualification.reason,
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
    return qualification


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
    """Return prediction rows joined with provenance and evaluation qualification.

    Rows are ordered by ``(scenario_id, county_fips, ts)``; ``ts`` and
    ``persisted_at`` are UTC-aware. ``limit`` must be in
    ``[1, MAX_QUERY_LIMIT]`` and ``model_kind`` one of :data:`MODEL_KINDS`.
    Unavailable predictions are never in the table; this query never fabricates
    one, and ``qualified`` is read from ``evaluation_artifacts``, never derived.
    """
    if not 1 <= limit <= MAX_QUERY_LIMIT:
        raise PersistenceError(f"limit must be in [1, {MAX_QUERY_LIMIT}], got {limit}")
    if model_kind is not None and model_kind not in MODEL_KINDS:
        raise PersistenceError(
            f"model_kind must be one of {MODEL_KINDS}, got {model_kind!r}"
        )

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
                  v.rule_id, v.rule_version, v.persisted_at,
                  e.status, e.qualified, e.qualification_reason
           FROM outage_predictions p
           JOIN prediction_provenance v USING (scenario_id, county_fips, ts)
           LEFT JOIN evaluation_artifacts e ON e.evaluation_sha256 = v.evaluation_sha256
           WHERE {where}
           ORDER BY p.scenario_id, p.county_fips, p.ts
           LIMIT ?""",
        [*params, limit],
    ).fetchall()

    return [
        {
            "scenario_id": row[0],
            "county_fips": row[1],
            "ts": _to_utc_aware(row[2]),
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
            "persisted_at": _to_utc_aware(row[14]),
            "evaluation_status": row[15],
            "qualified": row[16],
            "qualification_reason": row[17],
        }
        for row in rows
    ]


def query_evaluation(
    con: duckdb.DuckDBPyConnection,
    evaluation_sha256: str,
) -> dict[str, object] | None:
    """Return a stored evaluation artifact by content hash, or None when not persisted.

    A malformed id raises :class:`PersistenceError` rather than reading as "missing".
    """
    if not _SHA256.fullmatch(evaluation_sha256):
        raise PersistenceError(
            f"evaluation_sha256 is not a SHA-256 digest: {evaluation_sha256!r}"
        )
    row = con.execute(
        """SELECT evaluation_sha256, status, qualified, qualification_reason,
                  model_artifact_sha256, model_version, split_id,
                  split_input_artifact_sha256, coverage_json, metrics_json,
                  calibration_method, calibration_status, uncertainty_method,
                  reason, persisted_at
           FROM evaluation_artifacts
           WHERE evaluation_sha256 = ?""",
        [evaluation_sha256],
    ).fetchone()

    if row is None:
        return None

    return {
        "evaluation_sha256": row[0],
        "status": row[1],
        "qualified": row[2],
        "qualification_reason": row[3],
        "model_artifact_sha256": row[4],
        "model_version": row[5],
        "split_id": row[6],
        "split_input_artifact_sha256": row[7],
        "coverage_json": row[8],
        "metrics_json": row[9],
        "calibration_method": row[10],
        "calibration_status": row[11],
        "uncertainty_method": row[12],
        "reason": row[13],
        "persisted_at": _to_utc_aware(row[14]),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_qualified_evaluation(
    con: duckdb.DuckDBPyConnection, provenance: LightGBMPredictionProvenance
) -> None:
    if provenance.evaluation_sha256 is None:
        raise UnqualifiedEvaluationError(
            "trained-model prediction cites no evaluation artifact"
        )
    row = con.execute(
        """SELECT qualified, qualification_reason, model_artifact_sha256, split_id
           FROM evaluation_artifacts WHERE evaluation_sha256 = ?""",
        [provenance.evaluation_sha256],
    ).fetchone()
    if row is None:
        raise UnqualifiedEvaluationError(
            f"trained-model prediction cites evaluation {provenance.evaluation_sha256} "
            "which is not persisted"
        )
    qualified, reason, model_artifact_sha256, split_id = row
    if not qualified:
        raise UnqualifiedEvaluationError(
            f"trained-model prediction cites an unqualified evaluation: {reason}"
        )
    if model_artifact_sha256 != provenance.artifact_sha256:
        raise UnqualifiedEvaluationError(
            "trained-model prediction cites an evaluation of a different model artifact"
        )
    if split_id != provenance.split_id:
        raise UnqualifiedEvaluationError(
            "trained-model prediction cites an evaluation of a different split"
        )


def _to_utc_naive(value: datetime, field: str) -> datetime:
    """Normalise an aware datetime to naive UTC for the shared ``TIMESTAMP`` columns.

    DuckDB's Python client converts an *aware* datetime to the host's local wall
    time before storing it in a ``TIMESTAMP`` column; normalising here keeps the
    stored value host-independent.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise PersistenceError(f"{field} must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _to_utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC)


def _source_ref(provenance: PredictionProvenance) -> str:
    """``outage_predictions.source_ref``: the full artifact hash or the rule id."""
    if isinstance(provenance, LightGBMPredictionProvenance):
        return provenance.artifact_sha256
    return f"heuristic:{provenance.rule_id}"


def _source_version(provenance: PredictionProvenance) -> str:
    """``outage_predictions.source_version``: the model or rule version."""
    if isinstance(provenance, LightGBMPredictionProvenance):
        return provenance.model_version
    return provenance.rule_version

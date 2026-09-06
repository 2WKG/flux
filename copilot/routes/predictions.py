from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

import duckdb
from fastapi import APIRouter, Query, Request

from copilot.api import UnavailableError
from models.outage.persistence import PersistenceError, query_predictions

router = APIRouter(tags=["predictions"])


def _unavailable(reason: str) -> UnavailableError:
    return UnavailableError(
        "The qualified outage prediction artifact is unavailable.",
        details={"artifact": "outage_predictions", "reason": reason},
    )


def _cascade_unavailable(reason: str) -> UnavailableError:
    return UnavailableError(
        "A qualified topology cascade artifact is unavailable.",
        details={"artifact": "cascade_runs", "reason": reason},
    )


def _utc_timestamp(value: object) -> datetime:
    """Return a persisted timestamp as UTC or fail closed on schema drift."""
    if not isinstance(value, datetime):
        raise TypeError("provenance timestamp is not a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@router.get("/predictions")
def predictions(
    request: Request,
    scenario_id: str | None = None,
    county_fips: str | None = None,
    model_kind: Literal["lightgbm", "heuristic"] | None = None,
    limit: int = Query(1000, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        con = duckdb.connect(
            str(request.app.state.settings.duckdb_path), read_only=True
        )
    except duckdb.Error as exc:
        raise _unavailable("database_missing") from exc
    try:
        rows = query_predictions(
            con,
            scenario_id=scenario_id,
            county_fips=county_fips,
            model_kind=model_kind,
            limit=limit,
        )
        rows = [r for r in rows if r["qualified"] is True]
        if not rows:
            raise _unavailable("no_qualified_prediction")
        return {"status": "available", "predictions": rows}
    except PersistenceError as exc:
        raise _unavailable("invalid_request") from exc
    except duckdb.Error as exc:
        raise _unavailable("schema_mismatch") from exc
    finally:
        con.close()


@router.get("/cascade")
def cascade(request: Request, scenario_id: str) -> dict[str, Any]:
    """Read only a persisted cascade with an accepted topology artifact."""
    try:
        con = duckdb.connect(
            str(request.app.state.settings.duckdb_path), read_only=True
        )
    except duckdb.Error as exc:
        raise _cascade_unavailable("database_missing") from exc
    try:
        row = con.execute(
            """SELECT c.run_id, c.scenario_id, m.artifact_id, m.model_mode,
                      m.limitations_json
               FROM cascade_runs AS c
               JOIN mn_model_results AS r ON r.model_run_id = c.run_id
               JOIN mn_artifact_manifests AS m ON m.artifact_id = r.artifact_id
               WHERE c.scenario_id = ?
                 AND m.availability = 'available'
                 AND m.model_mode = 'topology'
                 AND r.validation_status = 'validated'
                 AND EXISTS (
                     SELECT 1 FROM mn_artifact_provenance AS p
                     WHERE p.artifact_id = m.artifact_id
                 )
               ORDER BY c.run_id DESC
               LIMIT 1""",
            [scenario_id],
        ).fetchone()
        if not row:
            raise _cascade_unavailable("topology_cascade_unsupported_or_absent")
        limitations = json.loads(row[4])
        if (
            not isinstance(limitations, list)
            or not limitations
            or not all(isinstance(item, str) and item for item in limitations)
        ):
            raise _cascade_unavailable("invalid_topology_artifact")
        provenance = []
        for provenance_row in con.execute(
            """SELECT source_name, source_ref, source_version, retrieved_at,
                      license_or_terms, source_record_id, content_sha256, is_derived
               FROM mn_artifact_provenance
               WHERE artifact_id = ?
               ORDER BY provenance_ordinal""",
            [row[2]],
        ).fetchall():
            (
                source_name,
                source_ref,
                source_version,
                retrieved_at,
                license_or_terms,
                source_record_id,
                content_sha256,
                is_derived,
            ) = provenance_row
            required_strings = (
                source_name,
                source_ref,
                source_version,
                license_or_terms,
                content_sha256,
            )
            if not all(isinstance(value, str) and value for value in required_strings):
                raise ValueError("provenance has a missing required field")
            if source_record_id is not None and not isinstance(source_record_id, str):
                raise TypeError("source_record_id is not a string")
            if not isinstance(is_derived, bool):
                raise TypeError("is_derived is not a boolean")
            provenance.append(
                {
                    "source_name": source_name,
                    "source_ref": source_ref,
                    "source_version": source_version,
                    "retrieved_at": _utc_timestamp(retrieved_at),
                    "license_or_terms": license_or_terms,
                    "source_record_id": source_record_id,
                    "content_sha256": content_sha256,
                    "is_derived": is_derived,
                }
            )
        if not provenance:
            raise _cascade_unavailable("invalid_topology_artifact")
        return {
            "status": "available",
            "run_id": row[0],
            "scenario_id": row[1],
            "artifact_id": row[2],
            "model_mode": row[3],
            "provenance": provenance,
            "limitations": limitations,
        }
    except (duckdb.Error, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _cascade_unavailable("topology_cascade_unsupported_or_absent") from exc
    finally:
        con.close()

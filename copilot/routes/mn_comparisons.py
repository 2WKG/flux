"""Server-owned Minnesota aggregate-context comparisons.

Only persisted aggregate model results are compared here.  The route never
creates a topology, flow, outage time series, or a client-side delta.
"""

from __future__ import annotations

import json
import math
from typing import Any

import duckdb
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from copilot.api import UnavailableError
from copilot.config import Settings

router = APIRouter(prefix="/mn", tags=["minnesota-comparisons"])


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_context_id: str = Field(min_length=1, max_length=128)
    candidate_context_id: str = Field(min_length=1, max_length=128)


def _unavailable(reason: str, **extra: str) -> UnavailableError:
    return UnavailableError(
        "The Minnesota comparison artifact is unavailable.",
        details={"artifact": "mn_comparison", "reason": reason, **extra},
    )


def _json(value: object, label: str) -> dict[str, Any]:
    try:
        result = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise _unavailable("invalid_persisted_result", field=label) from exc
    if not isinstance(result, dict):
        raise _unavailable("invalid_persisted_result", field=label)
    return result


def _context(con: duckdb.DuckDBPyConnection, context_id: str) -> dict[str, Any]:
    rows = con.execute(
        """SELECT m.artifact_id, m.identity_json, m.limitations_json,
                  r.metric_name, r.metric_value, r.metric_unit
             FROM mn_artifact_manifests AS m
             JOIN mn_model_results AS r USING (artifact_id)
            WHERE m.artifact_kind='model' AND m.geography_id='mn'
              AND m.availability='available' AND m.model_mode='aggregate'
              AND json_extract_string(m.identity_json, '$.source_identity.context_id')=?
            ORDER BY m.artifact_id""",
        [context_id],
    ).fetchall()
    if not rows:
        raise _unavailable("no_qualified_result", context_id=context_id)
    if len(rows) != 1:
        raise _unavailable("ambiguous_identity", context_id=context_id)
    artifact_id, identity_json, limitations_json, metric, value, unit = rows[0]
    if (
        not isinstance(metric, str)
        or not metric
        or not isinstance(unit, str)
        or not unit
    ):
        raise _unavailable("invalid_persisted_result", context_id=context_id)
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise _unavailable("invalid_persisted_result", context_id=context_id)
    identity = _json(identity_json, "identity_json")
    source = _json(identity.get("source_identity"), "source_identity")
    if source.get("context_id") != context_id:
        raise _unavailable("invalid_persisted_result", context_id=context_id)
    highlights = source.get("highlight_ids")
    if (
        not isinstance(highlights, list)
        or not highlights
        or not all(isinstance(item, str) and item for item in highlights)
    ):
        raise _unavailable("highlight_ids_unavailable", context_id=context_id)
    limitations = json.loads(limitations_json)
    if not isinstance(limitations, list) or not all(
        isinstance(item, str) for item in limitations
    ):
        raise _unavailable("invalid_persisted_result", context_id=context_id)
    provenance = con.execute(
        """SELECT source_name, source_ref, source_version, source_record_id
             FROM mn_artifact_provenance WHERE artifact_id=? ORDER BY provenance_ordinal""",
        [artifact_id],
    ).fetchall()
    if not provenance:
        raise _unavailable("provenance_missing", context_id=context_id)
    return {
        "context_id": context_id,
        "artifact_id": str(artifact_id),
        "label": source.get("label", context_id),
        "metric": metric,
        "value": float(value),
        "unit": unit,
        "highlight_ids": highlights,
        "limitations": limitations,
        "provenance": [
            {
                "source_id": record_id or name,
                "artifact_id": str(artifact_id),
                "version": version,
                "kind": "persisted_aggregate_model",
            }
            for name, _ref, version, record_id in provenance
        ],
    }


@router.post("/comparisons")
def compare(payload: ComparisonRequest, request: Request) -> dict[str, Any]:
    if payload.baseline_context_id == payload.candidate_context_id:
        raise _unavailable("identical_contexts")
    settings: Settings = request.app.state.settings
    try:
        con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    except duckdb.Error as exc:
        raise _unavailable("database_missing") from exc
    try:
        baseline = _context(con, payload.baseline_context_id)
        candidate = _context(con, payload.candidate_context_id)
        if (
            baseline["metric"] != candidate["metric"]
            or baseline["unit"] != candidate["unit"]
        ):
            raise _unavailable("metric_mismatch")
        return {
            "status": "ready",
            "comparison_id": f"{baseline['artifact_id']}..{candidate['artifact_id']}",
            "baseline": {key: baseline[key] for key in ("context_id", "label")},
            "candidate": {key: candidate[key] for key in ("context_id", "label")},
            "metrics": [
                {
                    "metric_id": baseline["metric"],
                    "label": baseline["metric"],
                    "baseline_value": baseline["value"],
                    "candidate_value": candidate["value"],
                    "delta_signed": candidate["value"] - baseline["value"],
                    "unit": baseline["unit"],
                    "provenance": baseline["provenance"] + candidate["provenance"],
                }
            ],
            "highlight_ids": list(
                dict.fromkeys(baseline["highlight_ids"] + candidate["highlight_ids"])
            ),
            "limitations": list(
                dict.fromkeys(baseline["limitations"] + candidate["limitations"])
            ),
        }
    except duckdb.CatalogException as exc:
        raise _unavailable("missing") from exc
    except duckdb.BinderException as exc:
        raise _unavailable("schema_mismatch") from exc
    finally:
        con.close()

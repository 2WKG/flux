"""Read-only persisted site-score and intervention comparison routes."""

from __future__ import annotations

import json
import math
from typing import Annotated, Any, Literal

import duckdb
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from copilot.api import UnavailableError
from copilot.routes.scenarios import _derive_labels

router = APIRouter(tags=["interventions"])


class SiteScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_id: str = Field(min_length=1, max_length=128)
    unit_mw: Literal[300, 1000]
    scenario_id: str = Field(min_length=1, max_length=128)


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(min_length=1, max_length=128)
    intervention_ids: list[
        Annotated[str, Field(pattern=r"^(site:[^@:\s]+(?:@(300|1000))?|line:[^:\s]+)$")]
    ] = Field(min_length=1, max_length=5)


def unavailable(reason: str, artifact: str = "site_scores") -> UnavailableError:
    return UnavailableError(
        f"The {artifact} artifact is unavailable.",
        details={"artifact": artifact, "reason": reason},
    )


_SITE_COLUMNS = (
    "site_id",
    "name",
    "kind",
    "county_fips",
    "source_name",
    "source_ref",
    "source_version",
    "source_retrieved_at",
    "fixture_batch_id",
)
_SCORE_COLUMNS = (
    "safety_score",
    "safety_flags_json",
    "grid_value_score",
    "lol_reduction_mwh",
    "congestion_relief_pct",
    "blackstart_reach_mw",
    "model_mode",
    "limitations_json",
    "source_name",
    "source_ref",
    "source_version",
    "source_retrieved_at",
    "fixture_batch_id",
)


def _provenance(row: dict[str, Any], prefix: str) -> dict[str, Any]:
    provenance = {
        key: row.pop(f"{prefix}_{key}")
        for key in (
            "source_name",
            "source_ref",
            "source_version",
            "source_retrieved_at",
            "fixture_batch_id",
        )
    }
    if not all(
        isinstance(provenance[key], str) and provenance[key]
        for key in ("source_name", "source_ref", "fixture_batch_id")
    ):
        raise unavailable("provenance_missing")
    return provenance


def _json_string_list(value: object, field: str) -> list[str]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise unavailable("invalid_persisted_outcome") from exc
    if not isinstance(decoded, list) or not all(
        isinstance(item, str) and item for item in decoded
    ):
        raise unavailable("invalid_persisted_outcome")
    return decoded


def _normalise_site_outcome(
    row: tuple[Any, ...], request: SiteScoreRequest
) -> dict[str, Any]:
    keys = tuple(f"site_{column}" for column in _SITE_COLUMNS) + tuple(
        f"score_{column}" for column in _SCORE_COLUMNS
    )
    result = dict(zip(keys, row, strict=True))
    model_mode = result.pop("score_model_mode")
    if model_mode != "topology":
        raise unavailable("unsupported_model_mode")
    limitations = _json_string_list(result.pop("score_limitations_json"), "limitations")
    if not limitations:
        raise unavailable("invalid_persisted_outcome")
    result["site_id"] = str(result.pop("site_site_id"))
    result["name"] = result.pop("site_name")
    result["kind"] = result.pop("site_kind")
    result["county_fips"] = result.pop("site_county_fips")
    for metric in (
        "safety_score",
        "grid_value_score",
        "lol_reduction_mwh",
        "congestion_relief_pct",
        "blackstart_reach_mw",
    ):
        value = result.pop(f"score_{metric}")
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise unavailable("invalid_persisted_outcome")
        result[metric] = float(value)
    result["safety_flags"] = _json_string_list(
        result.pop("score_safety_flags_json"), "safety_flags"
    )
    result["scenario_id"] = request.scenario_id
    result["unit_mw"] = request.unit_mw
    result["model_mode"] = model_mode
    result["limitations"] = limitations
    provenance = {
        "site_candidate": _provenance(result, "site"),
        "site_score": _provenance(result, "score"),
    }
    labels = [
        _derive_labels(item["source_name"], item["source_ref"])
        for item in provenance.values()
    ]
    result["source_kind"] = next(
        (source_kind for source_kind, _ in labels if source_kind is not None), None
    )
    result["topology"] = next(
        (topology for _, topology in labels if topology is not None), None
    )
    result["provenance"] = provenance
    return result


def read_site(path: str, request: SiteScoreRequest) -> dict[str, Any]:
    try:
        con = duckdb.connect(path, read_only=True)
    except duckdb.Error as exc:
        raise unavailable("missing", "database") from exc
    try:
        try:
            row = con.execute(
                """SELECT c.site_id,c.name,c.kind,c.county_fips,
                          c.source_name,c.source_ref,c.source_version,c.source_retrieved_at,c.fixture_batch_id,
                          s.safety_score,s.safety_flags_json,s.grid_value_score,s.lol_reduction_mwh,
                          s.congestion_relief_pct,s.blackstart_reach_mw,s.model_mode,s.limitations_json,
                          s.source_name,s.source_ref,s.source_version,s.source_retrieved_at,s.fixture_batch_id
                   FROM site_candidates c JOIN site_scores s USING(site_id)
                   WHERE s.site_id=? AND s.scenario_id=? AND s.unit_mw=?""",
                [request.site_id, request.scenario_id, request.unit_mw],
            ).fetchone()
        except duckdb.BinderException as exc:
            raise unavailable("outcome_metadata_unavailable") from exc
        if not row:
            raise unavailable("no_persisted_outcome")
        return _normalise_site_outcome(row, request)
    except duckdb.Error as exc:
        raise unavailable("query_failed") from exc
    finally:
        con.close()


@router.post("/site-score")
def site_score(payload: SiteScoreRequest, request: Request) -> dict[str, Any]:
    return read_site(str(request.app.state.settings.duckdb_path), payload)


@router.post("/compare")
def compare(payload: CompareRequest, request: Request) -> dict[str, Any]:
    if any(not item.startswith("site:") for item in payload.intervention_ids):
        raise unavailable("unsupported_request", "comparison")
    scores = []
    for item in payload.intervention_ids:
        scores.append(
            read_site(
                str(request.app.state.settings.duckdb_path),
                SiteScoreRequest(
                    site_id=item[5:].split("@", 1)[0],
                    unit_mw=int(item.split("@", 1)[1]) if "@" in item else 300,
                    scenario_id=payload.scenario_id,
                ),
            )
        )
    return {
        "scenario_id": payload.scenario_id,
        "interventions": scores,
        "comparison_status": "values_are_not_derived_deltas",
    }

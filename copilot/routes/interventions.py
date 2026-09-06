"""Read-only persisted site-score and intervention comparison routes."""

from __future__ import annotations

import json
from typing import Any

import duckdb
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from copilot.api import NotFoundError, UnavailableError

router = APIRouter(tags=["interventions"])


class SiteScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_id: str = Field(min_length=1, max_length=128)
    unit_mw: int = Field(ge=1, le=10000)
    scenario_id: str = Field(min_length=1, max_length=128)


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(min_length=1, max_length=128)
    intervention_ids: list[str] = Field(min_length=1, max_length=5)


def unavailable(reason: str, artifact: str = "site_scores") -> UnavailableError:
    return UnavailableError(
        f"The {artifact} artifact is unavailable.",
        details={"artifact": artifact, "reason": reason},
    )


def read_site(path: str, request: SiteScoreRequest) -> dict[str, Any]:
    try:
        con = duckdb.connect(path, read_only=True)
    except duckdb.Error as exc:
        raise unavailable("missing", "database") from exc
    try:
        try:
            row = con.execute(
                """SELECT c.site_id,c.name,c.kind,c.county_fips,c.source_name,c.source_ref,c.source_version,c.source_retrieved_at,c.fixture_batch_id,s.safety_score,s.safety_flags_json,s.grid_value_score,s.lol_reduction_mwh,s.congestion_relief_pct,s.blackstart_reach_mw FROM site_candidates c JOIN site_scores s USING(site_id) WHERE s.site_id=? AND s.scenario_id=? AND s.unit_mw=?""",
                [request.site_id, request.scenario_id, request.unit_mw],
            ).fetchone()
        except duckdb.BinderException as exc:
            raise unavailable("schema_mismatch") from exc
        if not row:
            raise NotFoundError(
                "The requested site score does not exist.",
                details={"site_id": request.site_id},
            )
        keys = (
            "site_id",
            "name",
            "kind",
            "county_fips",
            "source_name",
            "source_ref",
            "source_version",
            "source_retrieved_at",
            "fixture_batch_id",
            "safety_score",
            "safety_flags",
            "grid_value_score",
            "lol_reduction_mwh",
            "congestion_relief_pct",
            "blackstart_reach_mw",
        )
        result = dict(zip(keys, row, strict=True))
        result["site_id"] = str(result["site_id"])
        result["scenario_id"] = request.scenario_id
        result["unit_mw"] = request.unit_mw
        result["safety_flags"] = json.loads(result["safety_flags"])
        result["provenance"] = {
            k: result.pop(k)
            for k in (
                "source_name",
                "source_ref",
                "source_version",
                "source_retrieved_at",
                "fixture_batch_id",
            )
        }
        result["regulatory_feasibility"] = "not_assessed"
        return result
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

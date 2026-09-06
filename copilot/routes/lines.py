"""HTTP access to persisted line-upgrade rankings."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from copilot.api import UnavailableError
from copilot.api.pagination import PageRequest
from copilot.tools.schemas import LinesData, UnavailableOutput
from copilot.tools_lines import TopLinesReader

router = APIRouter(prefix="/lines", tags=["lines"])

RegionQuery = Annotated[str, Query(min_length=1, max_length=64)]
TechQuery = Literal["dlr", "reconductor", "any"]
LimitQuery = Annotated[int, Query(ge=1, le=100)]
OffsetQuery = Annotated[int, Query(ge=0, le=10_000)]


@router.get("/top")
def top_lines(
    request: Request,
    region: RegionQuery,
    tech: TechQuery = "any",
    limit: LimitQuery = 50,
    offset: OffsetQuery = 0,
) -> dict[str, object]:
    """Return one bounded deterministic page from the persisted ranking only."""

    result: LinesData | UnavailableOutput = TopLinesReader(
        request.app.state.settings.duckdb_path
    ).top_lines_page(region, tech, PageRequest(limit=limit, offset=offset))
    if isinstance(result, UnavailableOutput):
        raise UnavailableError(
            result.unavailable.reason,
            details={"artifact": "line_upgrade_scores", "reason": result.unavailable.code},
        )
    return result.model_dump(mode="json")

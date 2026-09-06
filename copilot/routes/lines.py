"""HTTP access to persisted line-upgrade rankings."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from copilot.api import UnavailableError
from copilot.api.pagination import PageRequest
from copilot.tools.schemas import TOP_LINES_MAX_LIMIT, LinesData, UnavailableOutput
from copilot.tools_lines import TopLinesReader

router = APIRouter(prefix="/lines", tags=["lines"])

RegionQuery = Annotated[str, Query(min_length=1, max_length=64)]
TechQuery = Literal["dlr", "reconductor", "any"]
# The HTTP page may not exceed the model-facing tool contract for the same read
# (`TOP_LINES_MAX_LIMIT`, docs/specs/05-copilot.md), so the two surfaces cannot
# diverge.  This is the per-route override documented in docs/api/pagination.md.
LimitQuery = Annotated[int, Query(ge=1, le=TOP_LINES_MAX_LIMIT)]
OffsetQuery = Annotated[int, Query(ge=0, le=10_000)]


@router.get("/top")
def top_lines(
    request: Request,
    region: RegionQuery,
    tech: TechQuery = "any",
    limit: LimitQuery = TOP_LINES_MAX_LIMIT,
    offset: OffsetQuery = 0,
) -> dict[str, object]:
    """Return one bounded deterministic page from the persisted ranking only."""

    result: LinesData | UnavailableOutput = TopLinesReader(
        request.app.state.settings.duckdb_path
    ).top_lines_page(
        region,
        tech,
        PageRequest(limit=limit, offset=offset, max_limit=TOP_LINES_MAX_LIMIT),
    )
    if isinstance(result, UnavailableOutput):
        raise UnavailableError(
            result.unavailable.reason,
            details={
                "artifact": "line_upgrade_scores",
                "reason": result.unavailable.code,
            },
        )
    return result.model_dump(mode="json")

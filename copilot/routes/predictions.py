from __future__ import annotations

from typing import Any

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


@router.get("/predictions")
def predictions(
    request: Request,
    scenario_id: str | None = None,
    county_fips: str | None = None,
    model_kind: str | None = None,
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
    """Read a persisted topology cascade; aggregate evidence cannot supply one."""
    try:
        con = duckdb.connect(
            str(request.app.state.settings.duckdb_path), read_only=True
        )
    except duckdb.Error as exc:
        raise _unavailable("database_missing") from exc
    try:
        row = con.execute(
            "SELECT run_id, scenario_id FROM cascade_runs WHERE scenario_id=? ORDER BY run_id DESC LIMIT 1",
            [scenario_id],
        ).fetchone()
        if not row:
            raise _unavailable("topology_cascade_unsupported_or_absent")
        return {"status": "available", "run_id": row[0], "scenario_id": row[1]}
    except duckdb.BinderException as exc:
        raise _unavailable("topology_cascade_unsupported_or_absent") from exc
    finally:
        con.close()

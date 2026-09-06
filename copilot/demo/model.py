"""Opt-in read surface for the canonical synthetic Texas model geometry."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query

from copilot.api import UnavailableError


def create_demo_model_router(*, duckdb_path: Path, case_path: Path) -> APIRouter:
    """Expose only core-authored canonical IDs and current-AUX geometry."""

    router = APIRouter(prefix="/demo", tags=["demo"])

    @router.get("/model")
    async def model(
        element_id: Annotated[list[str] | None, Query(max_length=64)] = None,
    ) -> dict[str, object]:
        try:
            return await asyncio.to_thread(
                _read_model_geometry,
                duckdb_path=duckdb_path,
                case_path=case_path,
                element_ids=element_id,
            )
        except Exception as exc:  # Core errors stay behind the named API boundary.
            raise UnavailableError(
                "Synthetic model geometry is unavailable.",
                details={"artifact": "synthetic_model_geometry", "reason": "unavailable"},
            ) from exc

    return router


def _read_model_geometry(
    *, duckdb_path: Path, case_path: Path, element_ids: list[str] | None
) -> dict[str, object]:
    """Delegate identity and geometry resolution to the reviewed core mapping."""

    from twin.build import cached_base_network, model_geometry

    net = cached_base_network(case_path, db_path=duckdb_path)
    return model_geometry(net, element_ids=element_ids)

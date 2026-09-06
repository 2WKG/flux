"""Non-persisting HTTP boundary for Flux's synthetic simulation primitives."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from copilot.api import InvalidInputError, NotFoundError, UnavailableError


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EditOperation(_Request):
    op: Literal["outage"]
    element_id: str = Field(min_length=1, max_length=160)


class ScenarioEditRequest(_Request):
    base_scenario_id: str = Field(min_length=1, max_length=128)
    ops: list[EditOperation] = Field(min_length=1, max_length=64)
    hour: int = Field(default=0, ge=0, le=8_760)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)


class CascadeRequest(_Request):
    element_ids: list[str] = Field(min_length=1, max_length=64)
    scenario_id: str = Field(min_length=1, max_length=128)
    hour: int = Field(ge=0, le=8_760)
    edit_hash: str | None = Field(default=None, min_length=16, max_length=64, pattern=r"^[a-f0-9]+$")
    seed: int = Field(default=0, ge=0, le=2_147_483_647)


class SitingSearchRequest(_Request):
    kind: Literal["synthetic_generation"]
    unit_mw: float = Field(gt=0, le=100_000)
    scenario_id: str = Field(min_length=1, max_length=128)
    n: int = Field(ge=1, le=5)
    hour: int = Field(default=0, ge=0, le=8_760)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)


@dataclass(frozen=True)
class _Edit:
    scenario_id: str
    hour: int
    seed: int
    element_ids: tuple[str, ...]


class InteractiveService:
    """Shares immutable edit identities while rebuilding a fresh network per call."""

    def __init__(self, *, duckdb_path: Path) -> None:
        self.duckdb_path = duckdb_path
        self._edits: dict[str, _Edit] = {}

    async def scenario_edit(self, payload: ScenarioEditRequest) -> dict[str, object]:
        result = await _in_thread(_scenario_edit, payload, duckdb_path=self.duckdb_path)
        self._edits[str(result["data"]["edit_hash"])] = _Edit(
            payload.base_scenario_id, payload.hour, payload.seed,
            tuple(item.element_id for item in payload.ops),
        )
        return result

    async def cascade(self, payload: CascadeRequest) -> dict[str, object]:
        if payload.edit_hash is not None:
            saved = self._edits.get(payload.edit_hash)
            if saved is None:
                raise NotFoundError("The requested interactive edit is not available.")
            if (saved.scenario_id, saved.hour, saved.seed, saved.element_ids) != (
                payload.scenario_id, payload.hour, payload.seed, tuple(payload.element_ids),
            ):
                raise InvalidInputError("Cascade inputs do not match the immutable edit hash.")
        return await _in_thread(_cascade, payload, duckdb_path=self.duckdb_path)

    async def balance(self, *, scope: Literal["base", "edit"] = "base", scenario_id: str = "interactive", hour: int = 0, edit_hash: str | None = None) -> dict[str, object]:
        return await _in_thread(_balance, _resolve_edit(scope, edit_hash, self._edits), scenario_id=scenario_id, hour=hour, duckdb_path=self.duckdb_path)

    async def redundancy(self, *, bus_id: int, scenario_id: str = "interactive", hour: int = 0) -> dict[str, object]:
        return await _in_thread(_redundancy, bus_id, scenario_id=scenario_id, hour=hour, duckdb_path=self.duckdb_path)

    async def siting_search(self, payload: SitingSearchRequest) -> dict[str, object]:
        return await _in_thread(_siting_search, payload, duckdb_path=self.duckdb_path)


def create_interactive_service(*, duckdb_path: Path) -> InteractiveService:
    return InteractiveService(duckdb_path=duckdb_path)


def create_interactive_router(*, service: InteractiveService) -> APIRouter:
    """Return the five public root routes; persisted GET /cascade remains separate."""
    router = APIRouter(tags=["interactive-simulation"])

    @router.post("/scenario/edit")
    async def scenario_edit(payload: ScenarioEditRequest) -> dict[str, object]:
        return await service.scenario_edit(payload)

    @router.post("/cascade")
    async def cascade(payload: CascadeRequest) -> dict[str, object]:
        return await service.cascade(payload)

    @router.get("/balance")
    async def balance(
        scope: Literal["base", "edit"] = "base",
        scenario_id: Annotated[str, Query(min_length=1, max_length=128)] = "interactive",
        hour: Annotated[int, Query(ge=0, le=8_760)] = 0,
        edit_hash: Annotated[str | None, Query(min_length=16, max_length=64, pattern=r"^[a-f0-9]+$")] = None,
    ) -> dict[str, object]:
        return await service.balance(scope=scope, scenario_id=scenario_id, hour=hour, edit_hash=edit_hash)

    @router.get("/redundancy")
    async def redundancy(
        bus_id: int,
        scenario_id: Annotated[str, Query(min_length=1, max_length=128)] = "interactive",
        hour: Annotated[int, Query(ge=0, le=8_760)] = 0,
    ) -> dict[str, object]:
        return await service.redundancy(bus_id=bus_id, scenario_id=scenario_id, hour=hour)

    @router.post("/siting/search")
    async def siting_search(payload: SitingSearchRequest) -> dict[str, object]:
        return await service.siting_search(payload)

    return router


def _resolve_edit(scope: str, edit_hash: str | None, edits: dict[str, _Edit]) -> _Edit | None:
    if scope == "base":
        if edit_hash is not None:
            raise InvalidInputError("edit_hash is valid only when scope=edit.")
        return None
    if edit_hash is None:
        raise InvalidInputError("scope=edit requires edit_hash.")
    try:
        return edits[edit_hash]
    except KeyError as exc:
        raise NotFoundError("The requested interactive edit is not available.") from exc


async def _in_thread(function: Callable[..., dict[str, object]], payload: Any, **kwargs: Any) -> dict[str, object]:
    try:
        return await asyncio.to_thread(function, payload, **kwargs)
    except ValueError as exc:
        raise InvalidInputError("Interactive simulation inputs are invalid.") from exc
    except Exception as exc:
        if type(exc).__name__ in {"SimulationInputError", "SearchUnavailable"}:
            raise InvalidInputError("Interactive simulation inputs are invalid.") from exc
        if type(exc).__name__ in {"SimulationUnavailableError", "SimulationSolveError", "ImportError", "ModuleNotFoundError"}:
            raise UnavailableError("Synthetic interactive simulation is unavailable.", details={"reason": "synthetic_core_unavailable"}) from exc
        raise


def _net(*, duckdb_path: Path) -> Any:
    from twin.build import build_network

    return build_network(duckdb_path)


def _scenario_edit(payload: ScenarioEditRequest, *, duckdb_path: Path) -> dict[str, object]:
    from twin.edits import edit_hash, outage
    from twin.feasibility import evaluate_feasibility

    net = _net(duckdb_path=duckdb_path)
    edits = tuple(outage(item.element_id) for item in payload.ops)
    return _result(net, {"edit_hash": edit_hash(edits), "element_ids": [item.element_id for item in edits], "feasibility": [evaluate_feasibility(net, item) for item in edits]})


def _cascade(payload: CascadeRequest, *, duckdb_path: Path) -> dict[str, object]:
    from twin.cascade import run_cascade
    from twin.edits import outage

    net = _net(duckdb_path=duckdb_path)
    return _result(net, run_cascade(net, tuple(outage(element_id) for element_id in payload.element_ids)))


def _balance(edit: _Edit | None, *, scenario_id: str, hour: int, duckdb_path: Path) -> dict[str, object]:
    from twin.balance import balance_report
    from twin.edits import outage

    net = _net(duckdb_path=duckdb_path)
    edits = () if edit is None else tuple(outage(element_id) for element_id in edit.element_ids)
    return _result(net, balance_report(net, edits=edits))


def _redundancy(bus_id: int, *, scenario_id: str, hour: int, duckdb_path: Path) -> dict[str, object]:
    from siting.redundancy import score_redundancy

    net = _net(duckdb_path=duckdb_path)
    return _result(net, score_redundancy(net, bus_id, scenario_id=scenario_id, hour=hour))


def _siting_search(payload: SitingSearchRequest, *, duckdb_path: Path) -> dict[str, object]:
    from siting.search import search_locations

    net = _net(duckdb_path=duckdb_path)
    return _result(net, {"candidates": search_locations(net, kind="producer", unit_mw=payload.unit_mw, scenario_id=payload.scenario_id, n=payload.n, hour=payload.hour)})


def _result(net: Any, data: object) -> dict[str, object]:
    return {
        "model_fidelity": "dc_screening",
        "network_provenance": "synthetic_activsg2000",
        "limitations": [
            "Synthetic ACTIVSg2000 topology; not a physical asset or interconnection result.",
            "DC screening excludes AC voltage, transient stability, protection, unit commitment, and regulatory feasibility.",
            "Interactive edits stay in memory and no route writes DuckDB.",
        ],
        "data": data,
    }

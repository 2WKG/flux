"""Opt-in, non-persisting HTTP routes for the synthetic interactive model."""
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
    n: int = Field(ge=1, le=8)
    hour: int = Field(default=0, ge=0, le=8_760)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)


@dataclass(frozen=True)
class _Edit:
    scenario_id: str
    hour: int
    seed: int
    element_ids: tuple[str, ...]


class InteractiveService:
    """One shared in-memory edit registry and non-persisting core boundary."""

    def __init__(self, *, duckdb_path: Path, case_path: Path) -> None:
        self.duckdb_path = duckdb_path
        self.case_path = case_path
        self._edits: dict[str, _Edit] = {}

    async def scenario_edit(self, payload: ScenarioEditRequest) -> dict[str, object]:
        result = await _in_thread(
            _scenario_edit, payload, duckdb_path=self.duckdb_path, case_path=self.case_path
        )
        edit_hash = str(result.pop("edit_hash"))
        self._edits[edit_hash] = _Edit(
            payload.base_scenario_id,
            payload.hour,
            payload.seed,
            tuple(str(item["element_id"]) for item in result.pop("_ops")),
        )
        return result

    async def cascade(self, payload: CascadeRequest) -> dict[str, object]:
        if payload.edit_hash is not None:
            saved = self._edits.get(payload.edit_hash)
            if saved is None:
                raise NotFoundError("The requested interactive edit is not available.")
            if (saved.scenario_id, saved.hour, saved.element_ids) != (
                payload.scenario_id,
                payload.hour,
                tuple(payload.element_ids),
            ):
                raise InvalidInputError("Cascade inputs do not match the immutable edit hash.")
        return await _in_thread(
            _cascade, payload, duckdb_path=self.duckdb_path, case_path=self.case_path
        )

    async def balance(
        self,
        *,
        scope: Literal["base", "edit"] = "base",
        scenario_id: str = "interactive",
        hour: int = 0,
        edit_hash: str | None = None,
    ) -> dict[str, object]:
        return await _in_thread(
            _balance,
            _resolve_edit(scope, edit_hash, self._edits),
            scenario_id=scenario_id,
            hour=hour,
            duckdb_path=self.duckdb_path,
            case_path=self.case_path,
        )

    async def redundancy(
        self, *, bus_id: int, scenario_id: str = "interactive", hour: int = 0
    ) -> dict[str, object]:
        return await _in_thread(
            _redundancy,
            bus_id,
            scenario_id=scenario_id,
            hour=hour,
            duckdb_path=self.duckdb_path,
            case_path=self.case_path,
        )

    async def siting_search(self, payload: SitingSearchRequest) -> dict[str, object]:
        return await _in_thread(
            _siting_search, payload, duckdb_path=self.duckdb_path, case_path=self.case_path
        )


def create_interactive_service(*, duckdb_path: Path, case_path: Path) -> InteractiveService:
    """Build the sole shared service for the router and natural-language adapter."""
    return InteractiveService(duckdb_path=duckdb_path, case_path=case_path)


def create_interactive_router(
    *,
    service: InteractiveService | None = None,
    duckdb_path: Path | None = None,
    case_path: Path | None = None,
) -> APIRouter:
    """Create HTTP routes over a supplied shared service or a new one."""
    if service is None:
        if duckdb_path is None or case_path is None:
            raise ValueError("service or both duckdb_path and case_path are required")
        service = create_interactive_service(duckdb_path=duckdb_path, case_path=case_path)
    router = APIRouter(prefix="/interactive", tags=["interactive-simulation"])

    @router.post("/scenario/edit")
    async def scenario_edit(payload: ScenarioEditRequest) -> dict[str, object]:
        return await service.scenario_edit(payload)

    @router.post("/cascade")
    async def cascade(payload: CascadeRequest) -> dict[str, object]:
        return await service.cascade(payload)

    @router.get("/balance")
    async def balance(scope: Literal["base", "edit"] = "base", scenario_id: Annotated[str, Query(min_length=1, max_length=128)] = "interactive", hour: Annotated[int, Query(ge=0, le=8_760)] = 0, edit_hash: Annotated[str | None, Query(min_length=16, max_length=64, pattern=r"^[a-f0-9]+$")] = None) -> dict[str, object]:
        return await service.balance(scope=scope, scenario_id=scenario_id, hour=hour, edit_hash=edit_hash)

    @router.get("/redundancy")
    async def redundancy(bus_id: int, scenario_id: Annotated[str, Query(min_length=1, max_length=128)] = "interactive", hour: Annotated[int, Query(ge=0, le=8_760)] = 0) -> dict[str, object]:
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
    if edit_hash not in edits:
        raise NotFoundError("The requested interactive edit is not available.")
    return edits[edit_hash]


async def _in_thread(function: Callable[..., dict[str, object]], payload: Any, **kwargs: Any) -> dict[str, object]:
    try:
        return await asyncio.to_thread(function, payload, **kwargs)
    except ValueError as exc:
        raise InvalidInputError("Interactive simulation inputs are invalid.") from exc
    except Exception as exc:
        if type(exc).__name__ == "SimulationInputError":
            raise InvalidInputError("Interactive simulation inputs are invalid.") from exc
        if type(exc).__name__ in {"SimulationUnavailableError", "SimulationSolveError", "SimulationCancelledError", "ImportError", "ModuleNotFoundError"}:
            raise UnavailableError("Synthetic interactive simulation is unavailable.", details={"reason": "synthetic_core_unavailable"}) from exc
        raise


def _net(*, case_path: Path, duckdb_path: Path) -> Any:
    from twin.build import cached_base_network
    return cached_base_network(case_path, db_path=duckdb_path)


def _scenario_edit(payload: ScenarioEditRequest, *, duckdb_path: Path, case_path: Path) -> dict[str, object]:
    from twin.cascade import (
        feasibility_report,
        immutable_scenario_net,
        scenario_identity,
    )
    baseline = _net(case_path=case_path, duckdb_path=duckdb_path)
    ids = [item.element_id for item in payload.ops]
    identity = scenario_identity(ids, payload.base_scenario_id, payload.hour, seed=payload.seed, net=baseline, case_path=case_path)
    result = _result(
        baseline,
        case_path,
        {
            "edit_hash": identity["scenario_hash"],
            "element_ids": identity["element_ids"],
            "feasibility": [feasibility_report(immutable_scenario_net(baseline, ids))],
        },
    )
    result["edit_hash"] = identity["scenario_hash"]
    result["_ops"] = [{"element_id": value} for value in identity["element_ids"]]
    return result


def _cascade(payload: CascadeRequest, *, duckdb_path: Path, case_path: Path) -> dict[str, object]:
    from twin.cascade import run_cascade
    baseline = _net(case_path=case_path, duckdb_path=duckdb_path)
    return _result(baseline, case_path, run_cascade(payload.element_ids, payload.scenario_id, payload.hour, net=baseline, db_path=duckdb_path, seed=payload.seed, write=False))


def _balance(edit: _Edit | None, *, scenario_id: str, hour: int, duckdb_path: Path, case_path: Path) -> dict[str, object]:
    from twin.cascade import balance_report, immutable_scenario_net
    baseline = _net(case_path=case_path, duckdb_path=duckdb_path)
    return _result(baseline, case_path, balance_report(immutable_scenario_net(baseline, list(edit.element_ids)) if edit else baseline))


def _redundancy(bus_id: int, *, scenario_id: str, hour: int, duckdb_path: Path, case_path: Path) -> dict[str, object]:
    from twin.cascade import redundancy_report
    baseline = _net(case_path=case_path, duckdb_path=duckdb_path)
    pp_bus_index = _pp_bus_index(baseline, bus_id)
    report = redundancy_report(baseline, [pp_bus_index])[0]
    report.pop("bus_id", None)
    report["source_bus_id"] = bus_id
    report["pp_bus_index"] = pp_bus_index
    return _result(baseline, case_path, report)


def _siting_search(payload: SitingSearchRequest, *, duckdb_path: Path, case_path: Path) -> dict[str, object]:
    from twin.cascade import placement_counterfactual, rank_candidate_placements
    baseline = _net(case_path=case_path, duckdb_path=duckdb_path)
    ranked = rank_candidate_placements(baseline, list(baseline.bus.index))[:payload.n]
    evaluations = []
    for row in ranked:
        pp_bus_index = int(row["bus_id"])
        evaluation = placement_counterfactual(
            [], payload.scenario_id, payload.hour, net=baseline,
            site_bus=pp_bus_index, unit_mw=payload.unit_mw, seed=payload.seed,
        )
        evaluation.pop("site_bus", None)
        evaluation["source_bus_id"] = _source_bus_id(baseline, pp_bus_index)
        evaluation["pp_bus_index"] = pp_bus_index
        evaluations.append(evaluation)
    return _result(
        baseline,
        case_path,
        {
            "selection": {
                "method": "bounded synthetic graph screening before measured DC counterfactuals",
                "limitations": "Candidate preselection is not N-1 reliability, interconnection, or physical siting ranking.",
            },
            "candidates": evaluations,
        },
    )


def _pp_bus_index(net: Any, source_bus_id: int) -> int:
    """Resolve the external MATPOWER/AUX bus ID without relying on row order."""
    matches = [
        int(index)
        for index, source_id in net.bus.flux_source_bus_id.items()
        if int(source_id) == source_bus_id
    ]
    if len(matches) != 1:
        raise ValueError("source_bus_id is not a unique current synthetic model bus")
    return matches[0]


def _source_bus_id(net: Any, pp_bus_index: int) -> int:
    if pp_bus_index not in net.bus.index:
        raise ValueError("pandapower bus index is absent from the synthetic model")
    return int(net.bus.at[pp_bus_index, "flux_source_bus_id"])


def _result(net: Any, case_path: Path, data: object) -> dict[str, object]:
    return {"model_fidelity": "dc_screening", "network_provenance": "synthetic_activsg2000", "limitations": ["Synthetic ACTIVSg2000 topology; not a physical asset or interconnection result.", "DC screening excludes AC voltage, transient stability, protection, unit commitment, and regulatory feasibility.", "Interactive edits stay in memory and never write DuckDB."], "data": data}

"""Deterministic DC cascade simulation for the synthetic ACTIVSg2000 network."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import duckdb
import networkx as nx
import pandapower as pp

from twin.build import build_network
from twin.contracts import (
    SYNTHETIC_TOPOLOGY_LABEL,
    CascadeEvent,
    CascadeResult,
    PlacementResult,
    SimulationInputError,
    SimulationSolveError,
    SimulationUnavailableError,
)


def run_cascade(
    element_ids: list[str],
    scenario_id: str,
    hour: int,
    *,
    net: Any | None = None,
    case_path: str | Path | None = None,
    db_path: str | Path | None = None,
    write: bool = False,
    seed: int = 0,
    overload_limit_pct: float = 100.0,
    max_stages: int = 12,
    unit_mw: float | None = None,
    site_bus: int | None = None,
    counterfactual_site_id: int | None = None,
) -> dict[str, Any]:
    """Apply outages, solve with ``rundcpp``, and trip overloads to stability.

    ``element_ids`` accepts contract line IDs (``"42"`` or ``"line:42"``),
    plus explicit ``impedance:``, ``generator:``/``gen:``, and ``load:`` ids.
    The supplied network is deep-copied before every edit, so scenario reruns
    never mutate a shared baseline.  ``write=True`` persists the same row shape
    read by the existing copilot cascade route; a missing database is explicit.
    """
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise SimulationInputError("scenario_id must be a non-empty string")
    if isinstance(hour, bool) or not isinstance(hour, int) or hour < 0:
        raise SimulationInputError("hour must be a non-negative integer")
    if overload_limit_pct <= 0 or max_stages <= 0:
        raise SimulationInputError("overload_limit_pct and max_stages must be positive")
    if net is None:
        net = build_network(case_path, db_path=db_path if db_path is not None else None)
    scenario_net = copy.deepcopy(net)
    _ensure_element_ids(scenario_net)
    if unit_mw is not None or site_bus is not None:
        if unit_mw is None or site_bus is None:
            raise SimulationInputError("unit_mw and site_bus must be supplied together")
        add_unit(scenario_net, bus_id=site_bus, unit_mw=unit_mw)

    events, lost_load_mw, dark_buses = _apply_forced_outages(scenario_net, element_ids)
    metadata = _metadata_from_database(db_path, scenario_net) if db_path is not None else ({}, {})
    county_by_bus, critical_by_bus = metadata
    loading_by_element: dict[str, float] = {}
    for stage in range(1, max_stages + 1):
        island_lost, island_buses, island_events = _island_load_loss(scenario_net, stage)
        lost_load_mw += island_lost
        dark_buses.update(island_buses)
        events.extend(island_events)
        _solve(scenario_net)
        overloads = _overloaded_elements(scenario_net, overload_limit_pct)
        loading_by_element.update({element_id: loading for element_id, _, _, loading in overloads})
        if not overloads:
            break
        for element_id, table, index, loading in overloads:
            scenario_net[table].at[index, "in_service"] = False
            events.append(
                CascadeEvent(
                    element_id=element_id,
                    kind="line" if table == "line" else "impedance",
                    stage=stage,
                    cause="overload",
                    loading_percent=round(float(loading), 6),
                )
            )
    else:
        raise SimulationSolveError(
            f"cascade did not stabilize after {max_stages} stages; increase max_stages explicitly"
        )

    counties_dark = tuple(sorted({county_by_bus[bus] for bus in dark_buses if bus in county_by_bus}))
    critical_lost = tuple(
        sorted(critical_id for bus in dark_buses for critical_id in critical_by_bus.get(bus, ()))
    )
    forced_key = tuple(sorted(str(value) for value in element_ids))
    result = CascadeResult(
        run_id=make_run_id(scenario_id, seed, forced_key, counterfactual_site_id, unit_mw),
        scenario_id=scenario_id,
        hour=hour,
        tripped_element_ids=tuple(events),
        lost_load_mw=round(float(lost_load_mw), 6),
        counties_dark=counties_dark,
        critical_loads_lost=critical_lost,
        topology=str(scenario_net.get("flux_topology", SYNTHETIC_TOPOLOGY_LABEL)),
        loading_by_element=loading_by_element,
    )
    if write:
        if db_path is None:
            raise SimulationUnavailableError("write=True requires a cascade_runs database path")
        persist_result(result, db_path, counterfactual_site_id=counterfactual_site_id)
    return result.json()


def make_run_id(
    scenario_id: str,
    seed: int,
    forced_out: Sequence[str],
    counterfactual_site_id: int | None = None,
    unit_mw: float | None = None,
) -> str:
    """Build the shared deterministic baseline/counterfactual run identity."""
    digest = hashlib.sha256("\x1f".join(sorted(forced_out)).encode()).hexdigest()[:8]
    if counterfactual_site_id is not None:
        if unit_mw is None:
            raise SimulationInputError("counterfactual run_id requires unit_mw")
        return f"{scenario_id}-s{seed}-cf-{counterfactual_site_id}-{_number_token(unit_mw)}"
    return f"{scenario_id}-s{seed}-{digest}"


def add_unit(net: Any, *, bus_id: int, unit_mw: float) -> int:
    """Add synthetic firm generation and pro-rata displace existing dispatch."""
    if bus_id not in net.bus.index:
        raise SimulationInputError(f"site bus {bus_id} is absent from the synthetic network")
    if unit_mw <= 0:
        raise SimulationInputError("unit_mw must be positive")
    active = net.gen.index[net.gen.in_service]
    existing = float(net.gen.loc[active, "p_mw"].sum())
    if existing <= 0:
        raise SimulationInputError("cannot displace generation: no in-service generators")
    displacement = min(float(unit_mw), existing)
    net.gen.loc[active, "p_mw"] *= (existing - displacement) / existing
    index = pp.create_gen(
        net,
        bus=bus_id,
        p_mw=float(unit_mw),
        vm_pu=1.0,
        max_p_mw=float(unit_mw),
        min_p_mw=0.3 * float(unit_mw),
        name=f"synthetic-unit:{bus_id}",
    )
    net.gen.at[index, "flux_element_id"] = f"generator:site:{bus_id}"
    return int(index)


def rank_candidate_placements(
    net: Any,
    candidate_bus_ids: Iterable[int],
    *,
    max_hops: int = 3,
) -> list[dict[str, Any]]:
    """Rank synthetic buses by local redundancy and reachable synthetic load.

    This is a topology heuristic for site screening.  It intentionally returns
    no connection claim for a real facility or public inventory asset.
    """
    if max_hops < 1:
        raise SimulationInputError("max_hops must be at least one")
    graph = _in_service_graph(net)
    load_by_bus = net.load[net.load.in_service].groupby("bus").p_mw.sum().to_dict()
    results: list[PlacementResult] = []
    for raw_bus_id in candidate_bus_ids:
        bus_id = int(raw_bus_id)
        if bus_id not in graph:
            raise SimulationInputError(f"candidate bus {bus_id} is absent from the synthetic network")
        reached = nx.single_source_shortest_path_length(graph, bus_id, cutoff=max_hops)
        reachable_load = sum(float(load_by_bus.get(bus, 0.0)) for bus in reached)
        results.append(
            PlacementResult(
                bus_id=bus_id,
                redundancy=int(graph.degree(bus_id)),
                reachable_load_mw=round(reachable_load, 6),
            )
        )
    return [result.json() for result in sorted(results, key=lambda row: (-row.redundancy, -row.reachable_load_mw, row.bus_id))]


def persist_result(
    result: CascadeResult, db_path: str | Path, *, counterfactual_site_id: int | None = None) -> None:
    """Persist an exact ``cascade_runs`` row, failing closed on schema drift."""
    path = Path(db_path)
    if not path.is_file():
        raise SimulationUnavailableError(f"cascade database is unavailable: {path}")
    con = duckdb.connect(str(path))
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if "cascade_runs" not in tables:
            raise SimulationUnavailableError("cascade database has no cascade_runs table")
        columns = {row[1] for row in con.execute("PRAGMA table_info('cascade_runs')").fetchall()}
        required = {
            "run_id", "scenario_id", "hour", "tripped_element_ids_json", "lost_load_mw",
            "counties_dark_json", "critical_loads_lost_json",
        }
        missing = sorted(required - columns)
        if missing:
            raise SimulationUnavailableError(
                "cascade_runs schema is missing required columns: " + ", ".join(missing)
            )
        values: dict[str, Any] = {
            "run_id": result.run_id,
            "scenario_id": result.scenario_id,
            "hour": result.hour,
            "tripped_element_ids_json": json.dumps([event.json() for event in result.tripped_element_ids]),
            "lost_load_mw": result.lost_load_mw,
            "counties_dark_json": json.dumps(list(result.counties_dark)),
            "critical_loads_lost_json": json.dumps(list(result.critical_loads_lost)),
            "counterfactual_site_id": counterfactual_site_id,
            "source_name": "twin.cascade",
            "source_ref": "ACTIVSg2000 synthetic topology",
            "source_version": "current",
            "source_retrieved_at": None,
            "fixture_batch_id": "synthetic-cascade",
        }
        selected = [column for column in values if column in columns]
        con.execute(
            "DELETE FROM cascade_runs WHERE run_id = ? AND hour = ?",
            [result.run_id, result.hour],
        )
        con.execute(
            f"INSERT INTO cascade_runs ({', '.join(selected)}) VALUES ({', '.join('?' for _ in selected)})",
            [values[column] for column in selected],
        )
    finally:
        con.close()


def _apply_forced_outages(net: Any, element_ids: Sequence[str]) -> tuple[list[CascadeEvent], float, set[int]]:
    events: list[CascadeEvent] = []
    lost_load_mw = 0.0
    dark_buses: set[int] = set()
    seen: set[tuple[str, int]] = set()
    for raw_id in element_ids:
        table, index, element_id = _resolve_element(net, raw_id)
        marker = (table, index)
        if marker in seen:
            continue
        seen.add(marker)
        if not bool(net[table].at[index, "in_service"]):
            continue
        net[table].at[index, "in_service"] = False
        kind = {"line": "line", "impedance": "impedance", "gen": "generator", "load": "load"}[table]
        events.append(CascadeEvent(element_id=element_id, kind=kind, stage=0, cause="forced"))
        if table == "load":
            lost_load_mw += float(net.load.at[index, "p_mw"])
            dark_buses.add(int(net.load.at[index, "bus"]))
    return events, lost_load_mw, dark_buses


def _resolve_element(net: Any, raw_id: str) -> tuple[str, int, str]:
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise SimulationInputError("element_ids must contain non-empty strings")
    token = raw_id.strip()
    prefix, separator, value = token.partition(":")
    if not separator:
        prefix, value = "line", token
    aliases = {"line": "line", "impedance": "impedance", "generator": "gen", "gen": "gen", "load": "load"}
    table = aliases.get(prefix.lower())
    if table is None:
        raise SimulationInputError(f"unknown synthetic element kind in {raw_id!r}")
    expected = f"{prefix.lower()}:{value}"
    frame = net[table]
    if "flux_element_id" in frame:
        matches = frame.index[frame.flux_element_id.astype(str).isin({token, expected, f"generator:{value}"})]
        if len(matches) == 1:
            index = int(matches[0])
            return table, index, str(frame.at[index, "flux_element_id"])
    try:
        index = int(value) - 1
    except ValueError as exc:
        raise SimulationInputError(f"unknown {prefix} element id {raw_id!r}") from exc
    if index not in frame.index:
        raise SimulationInputError(f"unknown {prefix} element id {raw_id!r}")
    canonical = str(frame.at[index, "flux_element_id"]) if "flux_element_id" in frame else f"{prefix}:{index + 1}"
    return table, index, canonical


def _ensure_element_ids(net: Any) -> None:
    for table, prefix in (("line", "line"), ("impedance", "impedance"), ("gen", "generator"), ("load", "load")):
        if "flux_element_id" not in net[table]:
            net[table]["flux_element_id"] = [f"{prefix}:{int(index) + 1}" for index in net[table].index]


def _solve(net: Any) -> None:
    try:
        pp.rundcpp(net)
    except Exception as exc:
        raise SimulationSolveError(f"pandapower.rundcpp failed: {exc}") from exc
    if not bool(net.converged):
        raise SimulationSolveError("pandapower.rundcpp did not converge")


def _overloaded_elements(net: Any, limit: float) -> list[tuple[str, str, int, float]]:
    overloaded: list[tuple[str, str, int, float]] = []
    if not net.res_line.empty:
        for index, value in net.res_line.loading_percent.items():
            if bool(net.line.at[index, "in_service"]) and float(value) > limit:
                overloaded.append((str(net.line.at[index, "flux_element_id"]), "line", int(index), float(value)))
    if not net.res_impedance.empty:
        for index, row in net.res_impedance.iterrows():
            if not bool(net.impedance.at[index, "in_service"]):
                continue
            rating = float(net.impedance.at[index, "sn_mva"])
            if rating <= 0:
                continue
            loading = max(abs(float(row.p_from_mw)), abs(float(row.p_to_mw))) / rating * 100.0
            if loading > limit:
                overloaded.append((str(net.impedance.at[index, "flux_element_id"]), "impedance", int(index), loading))
    return sorted(overloaded, key=lambda value: value[0])


def _in_service_graph(net: Any) -> nx.Graph:
    graph = nx.Graph()
    graph.add_nodes_from(int(bus) for bus in net.bus.index[net.bus.in_service])
    for table in ("line", "impedance", "trafo"):
        if table not in net or net[table].empty:
            continue
        frame = net[table]
        for _, row in frame[frame.in_service].iterrows():
            first = "hv_bus" if table == "trafo" else "from_bus"
            second = "lv_bus" if table == "trafo" else "to_bus"
            graph.add_edge(int(row[first]), int(row[second]))
    return graph


def _island_load_loss(net: Any, stage: int) -> tuple[float, set[int], list[CascadeEvent]]:
    graph = _in_service_graph(net)
    source_buses = {int(value) for value in net.ext_grid.loc[net.ext_grid.in_service, "bus"]}
    source_buses.update(int(value) for value in net.gen.loc[net.gen.in_service, "bus"])
    lost_load_mw = 0.0
    dark_buses: set[int] = set()
    events: list[CascadeEvent] = []
    for component in nx.connected_components(graph):
        if source_buses.intersection(component):
            continue
        rows = net.load.index[net.load.in_service & net.load.bus.isin(component)]
        for index in rows:
            net.load.at[index, "in_service"] = False
            lost_load_mw += float(net.load.at[index, "p_mw"])
            bus = int(net.load.at[index, "bus"])
            dark_buses.add(bus)
            events.append(
                CascadeEvent(
                    element_id=str(net.load.at[index, "flux_element_id"]),
                    kind="load",
                    stage=stage,
                    cause="island",
                )
            )
    return lost_load_mw, dark_buses, events


def _metadata_from_database(db_path: str | Path, net: Any) -> tuple[dict[int, str], dict[int, tuple[str, ...]]]:
    path = Path(db_path)
    if not path.is_file():
        raise SimulationUnavailableError(f"metadata database is unavailable: {path}")
    con = duckdb.connect(str(path), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        counties: dict[int, str] = {}
        critical: dict[int, tuple[str, ...]] = {}
        if "buses" in tables:
            columns = {row[1] for row in con.execute("PRAGMA table_info('buses')").fetchall()}
            if {"bus_id", "county_fips"}.issubset(columns):
                counties = {
                    int(bus_id): str(county_fips)
                    for bus_id, county_fips in con.execute(
                        "SELECT bus_id, county_fips FROM buses WHERE county_fips IS NOT NULL"
                    ).fetchall()
                }
        if "critical_loads" in tables:
            columns = {row[1] for row in con.execute("PRAGMA table_info('critical_loads')").fetchall()}
            if {"cl_id", "bus_id"}.issubset(columns):
                grouped: dict[int, list[str]] = {}
                for critical_id, bus_id in con.execute(
                    "SELECT cl_id, bus_id FROM critical_loads WHERE bus_id IS NOT NULL"
                ).fetchall():
                    grouped.setdefault(int(bus_id), []).append(str(critical_id))
                critical = {bus: tuple(sorted(values)) for bus, values in grouped.items()}
        if "flux_source_bus_id" in net.bus:
            source_to_pandapower = {
                int(source_bus): int(pandapower_bus)
                for pandapower_bus, source_bus in net.bus.flux_source_bus_id.items()
            }
            counties = {
                source_to_pandapower[source_bus]: county
                for source_bus, county in counties.items()
                if source_bus in source_to_pandapower
            }
            critical = {
                source_to_pandapower[source_bus]: values
                for source_bus, values in critical.items()
                if source_bus in source_to_pandapower
            }
        return counties, critical
    finally:
        con.close()


def _number_token(value: float) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number).replace(".", "p")

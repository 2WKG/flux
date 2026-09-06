"""Conservative DC cascade and placement primitives over immutable edit states."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import networkx as nx
import pandapower as pp

from twin.contracts import (
    CascadeEvent,
    CascadeResult,
    GridEdit,
    SimulationInputError,
    SimulationSolveError,
)
from twin.edits import apply_edits, edit_hash


def run_cascade(
    net: Any,
    edits: Iterable[GridEdit] = (),
    *,
    overload_limit_pct: float = 100.0,
    max_stages: int = 12,
) -> dict[str, Any]:
    """Apply immutable edits, shed unsupplied islands, and trip DC overloads.

    This does not pretend ordinary generators can black-start an island.  Only
    an in-service ``ext_grid`` is grid-forming; generator capacity is reported
    by :func:`balance_report` for feasibility decisions made by later layers.
    """
    if overload_limit_pct <= 0 or max_stages <= 0:
        raise SimulationInputError("overload_limit_pct and max_stages must be positive")
    edits_tuple = tuple(edits)
    scenario = apply_edits(net, edits_tuple)
    events = _edit_events(net, edits_tuple)
    lost = sum(
        float(scenario.load.at[index, "p_mw"])
        for event in events
        if event.kind == "load"
        for _, index in [scenario.flux_element_lookup[event.element_id]]
    )
    dark_buses = {
        int(scenario.load.at[index, "bus"])
        for event in events
        if event.kind == "load"
        for _, index in [scenario.flux_element_lookup[event.element_id]]
    }
    loading: dict[str, float] = {}
    for stage in range(1, max_stages + 1):
        island_lost, buses, island_events = _shed_unsupplied_islands(scenario, stage)
        lost += island_lost
        dark_buses.update(buses)
        events.extend(island_events)
        deficit_lost, deficit_buses, deficit_events = _shed_capacity_deficits(
            scenario, stage
        )
        lost += deficit_lost
        dark_buses.update(deficit_buses)
        events.extend(deficit_events)
        _solve(scenario)
        overloads = _overloads(scenario, overload_limit_pct)
        loading.update({item[0]: item[3] for item in overloads})
        if not overloads:
            break
        for element_id, table, index, percent in overloads:
            scenario[table].at[index, "in_service"] = False
            events.append(
                CascadeEvent(
                    element_id,
                    "line" if table == "line" else "impedance",
                    stage,
                    "overload",
                    round(percent, 6),
                )
            )
    else:
        raise SimulationSolveError(
            f"cascade did not stabilize after {max_stages} stages"
        )
    served = float(scenario.load.loc[scenario.load.in_service, "p_mw"].sum())
    result = CascadeResult(
        edit_hash(edits_tuple),
        tuple(events),
        round(lost, 6),
        round(served, 6),
        tuple(_county_impacts(scenario)),
        tuple(_critical_impacts(scenario, dark_buses)),
        loading,
        str(scenario.get("flux_topology", "synthetic (ACTIVSg2000)")),
    )
    return result.json()


def island_primitives(net: Any, edits: Iterable[GridEdit] = ()) -> list[dict[str, Any]]:
    """Expose immutable component facts for dedicated policy layers.

    This function intentionally avoids feasibility, balance, redundancy, and
    search policy; their named public APIs live in their own issue-owned files.
    """
    edits_tuple = tuple(edits)
    candidate = apply_edits(net, edits_tuple)
    graph = _graph(candidate)
    sources = _source_buses(candidate)
    rows = []
    for component in sorted(nx.connected_components(graph), key=lambda item: min(item)):
        rows.append(
            {
                "bus_ids": [
                    int(candidate.flux_bus_metadata[int(bus)]["bus_id"])
                    for bus in sorted(component)
                ],
                "load_mw": round(
                    float(
                        candidate.load[
                            candidate.load.in_service
                            & candidate.load.bus.isin(component)
                        ].p_mw.sum()
                    ),
                    6,
                ),
                "available_generation_mw": round(_capacity(candidate, component), 6),
                "has_grid_forming_source": bool(sources.intersection(component)),
                "edit_hash": edit_hash(edits_tuple),
            }
        )
    return rows


def _edit_events(before: Any, edits: tuple[GridEdit, ...]) -> list[CascadeEvent]:
    events: list[CascadeEvent] = []
    for edit in edits:
        if edit.kind not in {"outage", "remove"}:
            continue
        try:
            table, _ = before.flux_element_lookup[edit.element_id]
        except KeyError:
            continue  # apply_edits raises the useful user error.
        if table == "ext_grid":
            continue
        kind = {
            "line": "line",
            "impedance": "impedance",
            "gen": "generator",
            "load": "load",
        }.get(table)
        if kind is not None:
            events.append(CascadeEvent(edit.element_id, kind, 0, "forced"))
    return events


def _graph(net: Any) -> nx.Graph:
    graph = nx.Graph()
    graph.add_nodes_from(int(value) for value in net.bus.index[net.bus.in_service])
    for table in ("line", "impedance", "trafo"):
        if table not in net or net[table].empty:
            continue
        first, second = (
            ("hv_bus", "lv_bus") if table == "trafo" else ("from_bus", "to_bus")
        )
        for _, row in net[table][net[table].in_service].iterrows():
            graph.add_edge(int(row[first]), int(row[second]))
    return graph


def _source_buses(net: Any) -> set[int]:
    return {int(value) for value in net.ext_grid.loc[net.ext_grid.in_service, "bus"]}


def _capacity(net: Any, buses: set[int]) -> float:
    capacity = 0.0
    if not net.gen.empty:
        capacity += float(
            net.gen[net.gen.in_service & net.gen.bus.isin(buses)]
            .max_p_mw.fillna(0.0)
            .sum()
        )
    if not net.sgen.empty and "max_p_mw" in net.sgen:
        capacity += float(
            net.sgen[net.sgen.in_service & net.sgen.bus.isin(buses)]
            .max_p_mw.fillna(0.0)
            .sum()
        )
    return capacity


def _shed_unsupplied_islands(
    net: Any, stage: int
) -> tuple[float, set[int], list[CascadeEvent]]:
    sources = _source_buses(net)
    lost, dark, events = 0.0, set(), []
    for component in nx.connected_components(_graph(net)):
        if sources.intersection(component):
            continue
        for index in net.load.index[net.load.in_service & net.load.bus.isin(component)]:
            net.load.at[index, "in_service"] = False
            lost += float(net.load.at[index, "p_mw"])
            dark.add(int(net.load.at[index, "bus"]))
            events.append(
                CascadeEvent(
                    str(net.load.at[index, "flux_element_id"]), "load", stage, "island"
                )
            )
    return lost, dark, events


def _shed_capacity_deficits(
    net: Any, stage: int
) -> tuple[float, set[int], list[CascadeEvent]]:
    """Proportionally shed an energized island whose finite supply is short."""
    sources = _source_buses(net)
    lost, dark, events = 0.0, set(), []
    for component in nx.connected_components(_graph(net)):
        if not sources.intersection(component):
            continue
        demand = float(
            net.load.loc[
                net.load.in_service & net.load.bus.isin(component), "p_mw"
            ].sum()
        )
        available = _available_capacity(net, component)
        if demand <= 0 or available >= demand:
            continue
        served_fraction = max(available, 0.0) / demand
        for index in net.load.index[net.load.in_service & net.load.bus.isin(component)]:
            before = float(net.load.at[index, "p_mw"])
            shed = before * (1.0 - served_fraction)
            if shed <= 0:
                continue
            net.load.at[index, "p_mw"] = before - shed
            lost += shed
            dark.add(int(net.load.at[index, "bus"]))
            events.append(
                CascadeEvent(
                    str(net.load.at[index, "flux_element_id"]), "load", stage, "island"
                )
            )
    return lost, dark, events


def _available_capacity(net: Any, buses: set[int]) -> float:
    available = _capacity(net, buses)
    for _, row in net.ext_grid[
        net.ext_grid.in_service & net.ext_grid.bus.isin(buses)
    ].iterrows():
        limit = row.get("max_p_mw")
        if limit is None or float(limit) != float(limit):
            return float("inf")
        available += max(float(limit), 0.0)
    return available


def _solve(net: Any) -> None:
    try:
        pp.rundcpp(net)
    except Exception as exc:
        raise SimulationSolveError(f"pandapower.rundcpp failed: {exc}") from exc
    if not bool(net.converged):
        raise SimulationSolveError("pandapower.rundcpp did not converge")


def _overloads(net: Any, limit: float) -> list[tuple[str, str, int, float]]:
    output: list[tuple[str, str, int, float]] = []
    for index, loading in net.res_line.loading_percent.items():
        if bool(net.line.at[index, "in_service"]) and float(loading) > limit:
            output.append(
                (
                    str(net.line.at[index, "flux_element_id"]),
                    "line",
                    int(index),
                    float(loading),
                )
            )
    for index, row in net.res_impedance.iterrows():
        if not bool(net.impedance.at[index, "in_service"]):
            continue
        rating = float(net.impedance.at[index, "sn_mva"])
        if rating > 0:
            loading = (
                max(abs(float(row.p_from_mw)), abs(float(row.p_to_mw))) / rating * 100.0
            )
            if loading > limit:
                output.append(
                    (
                        str(net.impedance.at[index, "flux_element_id"]),
                        "impedance",
                        int(index),
                        loading,
                    )
                )
    return sorted(output, key=lambda item: item[0])


def _county_impacts(net: Any) -> list[dict[str, Any]]:
    totals: dict[str, float] = {}
    lost: dict[str, float] = {}
    for _, row in net.load.iterrows():
        metadata = net.flux_bus_metadata[int(row.bus)]
        county = metadata.get("county_fips")
        if county is None:
            continue
        nominal = float(row.get("flux_nominal_p_mw", row.p_mw))
        totals[county] = totals.get(county, 0.0) + nominal
        served = float(row.p_mw) if bool(row.in_service) else 0.0
        if nominal > served:
            lost[county] = lost.get(county, 0.0) + nominal - served
    return [
        {
            "county_fips": county,
            "lost_mw": round(value, 6),
            "fraction_dark": round(value / totals[county], 6),
            "basis": "synthetic modeled load; customer count unavailable",
        }
        for county, value in sorted(lost.items())
    ]


def _critical_impacts(net: Any, dark_buses: set[int]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for bus in sorted(dark_buses):
        source_id = int(net.flux_bus_metadata[bus]["bus_id"])
        output.extend(net.flux_critical_loads.get(source_id, ()))
    return sorted(output, key=lambda item: item["cl_id"])


def _bus(net: Any, source_id: int) -> int:
    try:
        return int(net.flux_bus_index[int(source_id)])
    except KeyError as exc:
        raise SimulationInputError(f"unknown bus_id {source_id}") from exc

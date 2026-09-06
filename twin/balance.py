"""Checkable consumer-draw and producer-capability accounting.

The values in this module are an accounting view of an edited pandapower net.
They deliberately do not turn a DC slack result, availability derate, or fuel
guess into dispatch or firm capacity.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import isfinite
from typing import Any, Literal

import networkx as nx

from twin.contracts import GridEdit, SimulationInputError
from twin.edits import apply_edits, edit_hash


Scope = Literal["state", "ba", "county", "island"]
_SCOPES = frozenset(("state", "ba", "county", "island"))
_FIRM_FUELS = frozenset(
    (
        "biomass",
        "coal",
        "geothermal",
        "hydro",
        "natural gas",
        "nuclear",
        "oil",
        "other fossil",
        "petroleum",
    )
)
_BA_FIELDS = ("ba_code", "balancing_authority", "balancing_authority_code")
_STATE_FIELDS = ("state", "state_code", "state_fips")


def balance_report(
    net: Any,
    *,
    scope: Scope = "state",
    scope_id: str | int | Sequence[int] | None = None,
    edits: Iterable[GridEdit] = (),
) -> dict[str, Any]:
    """Report load draw, nameplate capability, and scheduled dispatch by scope.

    ``capability_mw`` is the sum of declared generator nameplate values, with no
    availability adjustment.  ``dispatch_mw`` is only the explicit ``p_mw``
    schedule in generator tables; a pandapower external-grid slack result is
    intentionally not represented as a dispatch schedule.

    ``scope='island'`` requires a source bus ID (or an exact sequence of source
    bus IDs) after edits.  The sequence form rejects partial/mixed islands so a
    caller cannot silently form an arbitrary island subset.
    """
    if scope not in _SCOPES:
        raise SimulationInputError(f"unknown balance scope {scope!r}")
    edits_tuple = tuple(edits)
    candidate = apply_edits(net, edits_tuple)
    buses, resolved_scope_id = _scope_buses(candidate, scope, scope_id)
    draw = _load_draw(candidate, buses)
    capacity, dispatch, resource_capability = _generation_totals(candidate, buses)
    headroom = capacity - draw
    return {
        "edit_hash": edit_hash(edits_tuple),
        "scope": scope,
        "scope_id": resolved_scope_id,
        "bus_ids": _source_bus_ids(candidate, buses),
        "draw_mw": _rounded(draw),
        "capability_mw": _rounded(capacity),
        "dispatch_mw": _rounded(dispatch),
        "headroom_mw": _rounded(headroom),
        "reserve_margin": None if draw == 0.0 else _rounded(headroom / draw),
        "capability_basis": "nameplate; not availability-derated",
        "wind_capability_mw": _rounded(resource_capability["wind"]),
        "solar_capability_mw": _rounded(resource_capability["solar"]),
        "firm_capability_mw": _rounded(resource_capability["firm"]),
        "unclassified_capability_mw": _rounded(resource_capability["unclassified"]),
        "limitations": [
            "Capability is declared nameplate, not availability-derated or a reliability accreditation.",
            "Wind and solar are shown separately and are not represented as firm capacity.",
            "Dispatch is an explicit generator schedule; no slack-bus output, unit commitment, OPF, AC voltage, or transient-stability result is inferred.",
        ],
    }


def _scope_buses(net: Any, scope: str, scope_id: str | int | Sequence[int] | None) -> tuple[set[int], str | int | list[int] | None]:
    active = {int(bus) for bus in net.bus.index[net.bus.in_service]}
    if not active:
        raise SimulationInputError("network has no in-service buses")
    metadata = _bus_metadata(net)
    if scope == "island":
        return _island_scope(net, active, scope_id)
    if scope == "state" and scope_id is None:
        return active, None
    if scope_id is None:
        raise SimulationInputError(f"balance scope {scope!r} requires scope_id")
    fields = _STATE_FIELDS if scope == "state" else _BA_FIELDS if scope == "ba" else ("county_fips",)
    selected = {
        bus
        for bus in active
        if any(_same_scope_id(metadata[bus].get(field), scope_id) for field in fields)
    }
    if not selected:
        known = sorted(
            {
                str(value)
                for bus in active
                for field in fields
                if (value := metadata[bus].get(field)) is not None
            }
        )
        if not known:
            raise SimulationInputError(f"network has no declared {scope} identity for balance accounting")
        raise SimulationInputError(f"unknown {scope} scope_id {scope_id!r}")
    return selected, scope_id


def _island_scope(net: Any, active: set[int], scope_id: str | int | Sequence[int] | None) -> tuple[set[int], int | list[int]]:
    if scope_id is None:
        raise SimulationInputError("balance scope 'island' requires a source bus ID")
    requested = [int(scope_id)] if isinstance(scope_id, (str, int)) else [int(item) for item in scope_id]
    if not requested:
        raise SimulationInputError("balance island scope_id must contain at least one source bus ID")
    source_to_internal = _source_to_internal(net)
    try:
        internal = {source_to_internal[item] for item in requested}
    except KeyError as exc:
        raise SimulationInputError(f"unknown bus_id {exc.args[0]!r}") from exc
    graph = _in_service_graph(net, active)
    components = [set(component) for component in nx.connected_components(graph)]
    component = next((item for item in components if next(iter(internal)) in item), None)
    assert component is not None  # every in-service bus is a graph node
    if not internal.issubset(component):
        raise SimulationInputError("island scope_id spans more than one in-service island")
    if set(requested) != set(_source_bus_ids(net, component)) and len(requested) != 1:
        raise SimulationInputError("island scope_id must name one source bus or every bus in the island")
    resolved: int | list[int] = requested[0] if len(requested) == 1 else sorted(requested)
    return component, resolved


def _bus_metadata(net: Any) -> dict[int, dict[str, Any]]:
    metadata = net.get("flux_bus_metadata")
    if not isinstance(metadata, dict):
        raise SimulationInputError("network lacks Flux bus metadata for balance accounting")
    active = {int(bus) for bus in net.bus.index[net.bus.in_service]}
    missing = sorted(active - {int(key) for key in metadata})
    if missing:
        raise SimulationInputError("network is missing Flux metadata for in-service buses")
    return {int(key): dict(value) for key, value in metadata.items()}


def _source_to_internal(net: Any) -> dict[int, int]:
    index = net.get("flux_bus_index")
    if not isinstance(index, dict):
        raise SimulationInputError("network lacks Flux bus identity metadata")
    return {int(source): int(internal) for source, internal in index.items()}


def _source_bus_ids(net: Any, buses: set[int]) -> list[int]:
    metadata = _bus_metadata(net)
    try:
        return sorted(int(metadata[bus]["bus_id"]) for bus in buses)
    except (KeyError, TypeError, ValueError) as exc:
        raise SimulationInputError("network bus metadata lacks source bus_id") from exc


def _in_service_graph(net: Any, active: set[int]) -> nx.Graph:
    graph = nx.Graph()
    graph.add_nodes_from(active)
    for table, first, second in (
        ("line", "from_bus", "to_bus"),
        ("impedance", "from_bus", "to_bus"),
        ("trafo", "hv_bus", "lv_bus"),
    ):
        frame = net.get(table)
        if frame is None or frame.empty:
            continue
        for _, row in frame[frame.in_service].iterrows():
            a, b = int(row[first]), int(row[second])
            if a in active and b in active:
                graph.add_edge(a, b)
    return graph


def _load_draw(net: Any, buses: set[int]) -> float:
    frame = net.get("load")
    if frame is None or frame.empty:
        return 0.0
    return float(frame.loc[frame.in_service & frame.bus.isin(buses), "p_mw"].sum())


def _generation_totals(net: Any, buses: set[int]) -> tuple[float, float, dict[str, float]]:
    capacity = dispatch = 0.0
    resources = {"wind": 0.0, "solar": 0.0, "firm": 0.0, "unclassified": 0.0}
    for table in ("gen", "sgen", "ext_grid"):
        frame = net.get(table)
        if frame is None or frame.empty:
            continue
        rows = frame[frame.in_service & frame.bus.isin(buses)]
        for _, row in rows.iterrows():
            nameplate = _nameplate(row)
            if nameplate is not None:
                capacity += nameplate
                resources[_resource_class(row.get("fuel"))] += nameplate
            if table != "ext_grid" and "p_mw" in row and _finite(row["p_mw"]):
                dispatch += float(row["p_mw"])
    return capacity, dispatch, resources


def _nameplate(row: Any) -> float | None:
    for field in ("pmax_mw", "max_p_mw"):
        if field in row and _finite(row[field]):
            value = float(row[field])
            if value >= 0:
                return value
    return None


def _resource_class(fuel: object) -> str:
    if not isinstance(fuel, str) or not fuel.strip():
        return "unclassified"
    normalized = " ".join(fuel.casefold().replace("_", " ").replace("-", " ").split())
    if "wind" in normalized:
        return "wind"
    if "solar" in normalized or "photovoltaic" in normalized or normalized == "pv":
        return "solar"
    if normalized in _FIRM_FUELS:
        return "firm"
    return "unclassified"


def _same_scope_id(actual: object, wanted: object) -> bool:
    return actual is not None and str(actual) == str(wanted)


def _finite(value: object) -> bool:
    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _rounded(value: float) -> float:
    return round(float(value), 6)

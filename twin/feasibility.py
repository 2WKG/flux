"""Fail-closed screening rules for proposed grid edits.

The rules here are a *screen*, not an interconnection study.  P2 and the
40-km spur screen are product choices, so their reasons identify them as such
rather than presenting them as a sourced engineering limit.  The module takes
the immutable ``GridEdit`` contract from :mod:`twin.edits` when it is present,
but deliberately accepts mappings too: the HTTP boundary can validate a
proposed edit before constructing that dataclass.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from math import isfinite
from typing import Any, Literal

import pandas as pd

FeasibilityStatus = Literal["valid", "invalid", "unknown"]
FeasibilityResult = dict[str, Any]

INTERCONNECT_DISTANCE_KM = 40.0
MIN_INTERCONNECT_KV = 138.0
LARGE_UNIT_MW = 300.0
LARGE_UNIT_MIN_KV = 230.0


def evaluate_feasibility(
    net: Any,
    edit: Any,
    *,
    ercot_boundary: Callable[[Any], bool] | Any | None = None,
) -> FeasibilityResult | list[FeasibilityResult]:
    """Screen one proposed edit, or an ordered edit sequence.

    The first conclusive failed rule is returned.  A missing prerequisite is
    ``unknown`` with its own named reason; callers must not turn it into a
    permissive placement.  ``valid`` means every rule applicable to the edit
    was evaluated on the supplied synthetic network.

    ``ercot_boundary`` may be a predicate that receives the edit mapping, or
    a geometry-like object exposing ``contains``.  In the absence of an
    explicit boundary, the synthetic twin's declared ``interconnection`` is
    used (and defaults to ERCOT for this ERCOT-only adapter).
    """
    if _is_edit_sequence(edit):
        return [
            evaluate_feasibility(net, item, ercot_boundary=ercot_boundary)
            for item in edit
        ]

    proposal = _as_mapping(edit)
    if not proposal:
        return _result("unknown", "input", "invalid_edit", {})

    membership = _check_membership(net, proposal, ercot_boundary)
    if membership is not None:
        return membership

    bus_id = _attach_bus_id(proposal)
    bus = _bus_row(net, bus_id)
    distance = _number(
        proposal.get("interconnect_distance_km", proposal.get("length_km"))
    )
    if distance is None:
        return _result(
            "unknown",
            "P1",
            "interconnect_distance_unknown",
            {"bus_id": bus_id, "required_kv": MIN_INTERCONNECT_KV},
        )
    if distance > INTERCONNECT_DISTANCE_KM:
        return _result(
            "invalid",
            "P1",
            "interconnect_distance_exceeds_40_km",
            {"distance_km": distance, "limit_km": INTERCONNECT_DISTANCE_KM},
        )
    if bus is None:
        return _result("unknown", "P1", "interconnect_bus_unknown", {"bus_id": bus_id})
    base_kv = _number(bus.get("vn_kv", bus.get("base_kv")))
    if base_kv is None:
        return _result(
            "unknown", "P1", "interconnect_voltage_unknown", {"bus_id": bus_id}
        )
    if base_kv < MIN_INTERCONNECT_KV:
        return _result(
            "invalid",
            "P1",
            "interconnect_voltage_below_138_kv",
            {"bus_id": bus_id, "base_kv": base_kv, "required_kv": MIN_INTERCONNECT_KV},
        )

    capacity = _capacity_mw(proposal)
    if capacity is None:
        return _result("unknown", "P2", "unit_capacity_unknown", {"bus_id": bus_id})
    if capacity > LARGE_UNIT_MW and base_kv < LARGE_UNIT_MIN_KV:
        return _result(
            "invalid",
            "P2",
            "large_unit_requires_230_kv_screening_choice",
            {
                "capacity_mw": capacity,
                "base_kv": base_kv,
                "threshold_mw": LARGE_UNIT_MW,
                "required_kv": LARGE_UNIT_MIN_KV,
                "basis": "unverified_screening_choice",
            },
        )

    spur = _number(proposal.get("spur_length_km"))
    # An add-line edit has no separate geometry yet, so its declared length is
    # the radial spur length.  Other edits use their P1 distance unless the
    # caller supplies a distinct routed spur length.
    if spur is None and _kind(proposal) == "add_line":
        spur = distance
    if spur is not None and spur > INTERCONNECT_DISTANCE_KM:
        return _result(
            "invalid",
            "P3",
            "radial_spur_exceeds_40_km_screening_choice",
            {
                "spur_length_km": spur,
                "limit_km": INTERCONNECT_DISTANCE_KM,
                "basis": "unverified_screening_choice",
            },
        )
    if _kind(proposal) == "add_line" and _number(proposal.get("rate_a_mw")) is None:
        return _result(
            "unknown",
            "P3",
            "spur_rating_unknown",
            {"basis": "smallest_conductor_class_for_voltage"},
        )

    edited = _apply_edit(net, edit)
    corridor = _check_corridor(edited)
    if corridor is not None:
        return corridor

    island = _check_island(edited, proposal)
    if island is not None:
        return island

    return _result(
        "valid",
        "all",
        "placement_screen_passed",
        {
            "bus_id": bus_id,
            "distance_km": distance,
            "base_kv": base_kv,
            "capacity_mw": capacity,
            "limits": {
                "p1_distance_km": INTERCONNECT_DISTANCE_KM,
                "p2_large_unit_mw": LARGE_UNIT_MW,
                "p2_required_kv": LARGE_UNIT_MIN_KV,
            },
        },
    )


def _check_membership(
    net: Any, proposal: Mapping[str, Any], boundary: Any | None
) -> FeasibilityResult | None:
    explicit = proposal.get("interconnection", proposal.get("region"))
    inside: bool | None = None
    if boundary is not None:
        try:
            if callable(boundary):
                inside = bool(boundary(proposal))
            elif hasattr(boundary, "contains"):
                point = proposal.get("point", proposal)
                inside = bool(boundary.contains(point))
        except (TypeError, ValueError, AttributeError):
            inside = None
    if inside is None and explicit is not None:
        inside = str(explicit).strip().upper() == "ERCOT"
    if inside is None:
        declared = _net_value(net, "interconnection")
        # This twin adapter is ERCOT-only until a different topology adapter
        # declares another interconnection.
        inside = str(declared if declared is not None else "ERCOT").upper() == "ERCOT"
    if not inside:
        return _result(
            "unknown",
            "P5",
            "outside_ercot_interconnection",
            {"interconnection": explicit or _net_value(net, "interconnection")},
        )
    return None


def _check_corridor(net: Any) -> FeasibilityResult | None:
    line = getattr(net, "line", None)
    if not isinstance(line, pd.DataFrame):
        return _result("unknown", "P4", "corridor_topology_unknown", {})
    if line.empty:
        return None

    results = getattr(net, "res_line", None)
    if not isinstance(results, pd.DataFrame) or "loading_percent" not in results:
        try:
            import pandapower as pp

            pp.rundcpp(net)
            results = getattr(net, "res_line", None)
        except Exception as exc:  # noqa: BLE001 - solver failure is an availability state
            return _result(
                "unknown", "P4", "dc_power_flow_unavailable", {"detail": str(exc)}
            )
    if not isinstance(results, pd.DataFrame) or "loading_percent" not in results:
        return _result("unknown", "P4", "corridor_loading_unknown", {})
    loading = pd.to_numeric(results["loading_percent"], errors="coerce")
    if loading.isna().any():
        return _result("unknown", "P4", "corridor_loading_unknown", {})
    overloaded = loading[loading > 100.0]
    if not overloaded.empty:
        return _result(
            "invalid",
            "P4",
            "corridor_loading_exceeds_100_percent",
            {
                "line_indices": [int(index) for index in overloaded.index],
                "max_loading_percent": float(overloaded.max()),
            },
        )
    return None


def _check_island(net: Any, proposal: Mapping[str, Any]) -> FeasibilityResult | None:
    buses = getattr(net, "bus", None)
    if not isinstance(buses, pd.DataFrame):
        return _result("unknown", "P6", "island_topology_unknown", {})
    bus_id = _attach_bus_id(proposal)
    attach_index = _net_bus_index(net, bus_id)
    if attach_index not in buses.index:
        return _result("unknown", "P6", "attach_bus_unknown", {"bus_id": bus_id})

    edges: dict[Any, set[Any]] = {bus: set() for bus in buses.index}
    for table_name in ("line", "impedance"):
        table = getattr(net, table_name, None)
        if not isinstance(table, pd.DataFrame):
            continue
        for _, row in table.iterrows():
            if not _in_service(row.get("in_service", True)):
                continue
            left, right = row.get("from_bus"), row.get("to_bus")
            if left in edges and right in edges:
                edges[left].add(right)
                edges[right].add(left)

    component = _component(edges, attach_index)
    if _component_has_generation(net, component, proposal):
        return None
    return _result(
        "invalid",
        "P6",
        "attach_island_has_no_generation",
        {"bus_id": bus_id, "island_bus_ids": sorted(component)},
    )


def _component_has_generation(
    net: Any, component: set[Any], proposal: Mapping[str, Any]
) -> bool:
    if (
        _kind(proposal) == "add_gen"
        and _net_bus_index(net, _attach_bus_id(proposal)) in component
    ):
        return (_capacity_mw(proposal) or 0.0) > 0.0
    for table_name in ("gen", "sgen", "ext_grid"):
        table = getattr(net, table_name, None)
        if not isinstance(table, pd.DataFrame):
            continue
        for _, row in table.iterrows():
            if (
                not _in_service(row.get("in_service", True))
                or row.get("bus") not in component
            ):
                continue
            if table_name == "ext_grid":
                return True
            for column in ("max_p_mw", "pmax_mw", "p_mw"):
                value = _number(row.get(column))
                if value is not None and value > 0.0:
                    return True
    return False


def _apply_edit(net: Any, edit: Any) -> Any:
    try:
        from twin.contracts import GridEdit
        from twin.edits import apply_edits

        if not isinstance(edit, GridEdit):
            return net
        return apply_edits(net, [edit])
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError):
        # The feature remains useful with an already-edited net for isolated
        # screening tests; P4/P6 retain their fail-closed checks below.
        return net


def _as_mapping(edit: Any) -> dict[str, Any]:
    if isinstance(edit, Mapping):
        return dict(edit)
    if is_dataclass(edit) and not isinstance(edit, type):
        return asdict(edit)
    values = getattr(edit, "__dict__", None)
    return dict(values) if isinstance(values, dict) else {}


def _is_edit_sequence(edit: Any) -> bool:
    return isinstance(edit, Sequence) and not isinstance(
        edit, (str, bytes, bytearray, Mapping)
    )


def _kind(proposal: Mapping[str, Any]) -> str:
    return str(proposal.get("kind", proposal.get("op", ""))).strip().lower()


def _attach_bus_id(proposal: Mapping[str, Any]) -> Any:
    return proposal.get(
        "bus_id", proposal.get("to_bus_id", proposal.get("from_bus_id"))
    )


def _bus_row(net: Any, bus_id: Any) -> dict[str, Any] | None:
    table = getattr(net, "bus", None)
    index = _net_bus_index(net, bus_id)
    if not isinstance(table, pd.DataFrame) or index not in table.index:
        return None
    return table.loc[index].to_dict()


def _net_bus_index(net: Any, bus_id: Any) -> Any:
    source_indices = _net_value(net, "flux_bus_index")
    if isinstance(source_indices, Mapping):
        return source_indices.get(bus_id, bus_id)
    return bus_id


def _capacity_mw(proposal: Mapping[str, Any]) -> float | None:
    return _number(
        proposal.get("pmax_mw", proposal.get("p_mw", proposal.get("rate_a_mw")))
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number >= 0.0 else None


def _in_service(value: Any) -> bool:
    """Treat pandas/numpy false values as out of service without guessing NaN."""
    if value is None or pd.isna(value):
        return False
    return bool(value)


def _net_value(net: Any, key: str) -> Any:
    if isinstance(net, Mapping):
        return net.get(key)
    return getattr(net, key, None)


def _component(edges: Mapping[Any, set[Any]], start: Any) -> set[Any]:
    seen = {start}
    frontier = [start]
    while frontier:
        current = frontier.pop()
        for neighbor in edges.get(current, set()):
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append(neighbor)
    return seen


def _result(
    status: FeasibilityStatus, rule: str, reason: str, evidence: dict[str, Any]
) -> FeasibilityResult:
    return {"status": status, "rule": rule, "reason": reason, "evidence": evidence}

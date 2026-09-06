"""Immutable, order-sensitive simulation edit operations."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable
from typing import Any

import pandapower as pp

from twin.contracts import GridEdit, SimulationInputError


def outage(element_id: str) -> GridEdit:
    return GridEdit("outage", _id(element_id))


def remove(element_id: str) -> GridEdit:
    return GridEdit("remove", _id(element_id))


def add_generator(element_id: str, bus_id: int, p_mw: float, *, pmax_mw: float | None = None) -> GridEdit:
    return GridEdit("add_gen", _id(element_id), bus_id=int(bus_id), p_mw=_positive(p_mw, "p_mw"), pmax_mw=_positive(pmax_mw if pmax_mw is not None else p_mw, "pmax_mw"))


def add_load(element_id: str, bus_id: int, p_mw: float) -> GridEdit:
    return GridEdit("add_load", _id(element_id), bus_id=int(bus_id), p_mw=_positive(p_mw, "p_mw"))


def add_line(element_id: str, from_bus_id: int, to_bus_id: int, *, r_pu: float, x_pu: float, rate_a_mw: float, base_kv: float, length_km: float = 1.0) -> GridEdit:
    if int(from_bus_id) == int(to_bus_id):
        raise SimulationInputError("an added line requires distinct endpoint buses")
    return GridEdit("add_line", _id(element_id), from_bus_id=int(from_bus_id), to_bus_id=int(to_bus_id), r_pu=_nonnegative(r_pu, "r_pu"), x_pu=_positive(x_pu, "x_pu"), rate_a_mw=_positive(rate_a_mw, "rate_a_mw"), base_kv=_positive(base_kv, "base_kv"), length_km=_positive(length_km, "length_km"))


def edit_hash(edits: Iterable[GridEdit]) -> str:
    """Hash the supplied edit sequence without sorting it.

    Order is intentional: ``[remove(x), add_line(x)]`` differs from the
    reversed sequence, and both are traceable scenario identities.
    """
    payload = [edit.json() if isinstance(edit, GridEdit) else _bad_edit(edit) for edit in edits]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def apply_edits(net: Any, edits: Iterable[GridEdit]) -> Any:
    """Return an independently editable copy; never mutate ``net`` or a cache."""
    result = copy.deepcopy(net)
    for edit in edits:
        if not isinstance(edit, GridEdit):
            raise SimulationInputError("edits must contain GridEdit values")
        _apply(result, edit)
    return result


def _apply(net: Any, edit: GridEdit) -> None:
    lookup = net.get("flux_element_lookup")
    if not isinstance(lookup, dict):
        raise SimulationInputError("network lacks Flux element identity metadata")
    if edit.kind in {"outage", "remove"}:
        try:
            table, index = lookup[edit.element_id]
        except KeyError as exc:
            raise SimulationInputError(f"unknown synthetic element {edit.element_id!r}") from exc
        if table == "ext_grid":
            raise SimulationInputError("removing the grid-forming reference requires an explicit replacement model")
        net[table].at[index, "in_service"] = False
        return
    if edit.element_id in lookup:
        raise SimulationInputError(f"duplicate synthetic element id {edit.element_id!r}")
    if edit.kind == "add_gen":
        bus = _bus(net, edit.bus_id)
        index = pp.create_gen(net, bus, p_mw=float(edit.p_mw), vm_pu=1.0, max_p_mw=float(edit.pmax_mw), min_p_mw=0.0, name=edit.element_id)
        table = "gen"
    elif edit.kind == "add_load":
        bus = _bus(net, edit.bus_id)
        index = pp.create_load(net, bus, p_mw=float(edit.p_mw), q_mvar=0.0, name=edit.element_id)
        table = "load"
    elif edit.kind == "add_line":
        first, second = _bus(net, edit.from_bus_id), _bus(net, edit.to_bus_id)
        z_base = float(edit.base_kv) ** 2 / float(net.sn_mva)
        index = pp.create_line_from_parameters(net, first, second, float(edit.length_km), float(edit.r_pu) * z_base / float(edit.length_km), float(edit.x_pu) * z_base / float(edit.length_km), 0.0, float(edit.rate_a_mw) / (3**0.5 * float(edit.base_kv)), name=edit.element_id)
        table = "line"
    else:  # GridEdit is public and may be reconstructed from untrusted JSON.
        raise SimulationInputError(f"unsupported edit kind {edit.kind!r}")
    net[table].at[index, "flux_element_id"] = edit.element_id
    if table == "load":
        net[table].at[index, "flux_nominal_p_mw"] = float(edit.p_mw)
    lookup[edit.element_id] = (table, int(index))


def _bus(net: Any, bus_id: int | None) -> int:
    try:
        return int(net.flux_bus_index[int(bus_id)])
    except (KeyError, TypeError, ValueError) as exc:
        raise SimulationInputError(f"unknown bus_id {bus_id!r}") from exc


def _id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SimulationInputError("element_id must be a non-empty string")
    return value.strip()


def _positive(value: float, name: str) -> float:
    number = float(value)
    if number <= 0:
        raise SimulationInputError(f"{name} must be positive")
    return number


def _nonnegative(value: float, name: str) -> float:
    number = float(value)
    if number < 0:
        raise SimulationInputError(f"{name} must be non-negative")
    return number


def _bad_edit(value: object) -> None:
    raise SimulationInputError(f"edits must contain GridEdit values, got {type(value).__name__}")

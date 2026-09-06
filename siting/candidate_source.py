"""Synthetic generator-bus candidate adapters.

The candidates here are model attachment points.  They are derived from the
generator and bus records already loaded from DuckDB by ``twin.build`` and do
not claim a physical site, interconnection point, or geographic suitability.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

from twin.contracts import SYNTHETIC_TOPOLOGY_LABEL

# Each source candidate triggers a peak-hour counterfactual in the current
# search path, so discovery is deliberately bounded as well.
MAX_SYNTHETIC_PRODUCER_CANDIDATES = 5
MIN_INTERCONNECT_KV = 138.0


class SyntheticCandidateSourceUnavailable(RuntimeError):
    """A network cannot prove the facts needed for a source-derived candidate."""


def producer_candidates(net: object) -> list[dict[str, object]]:
    """Return generator-bus attachment alternatives from a declared synthetic net.

    Zero distance means the added unit is co-located with the source generator's
    declared synthetic bus.  It is a model fact, never a real-world spur claim.
    """

    topology = _required_synthetic_topology(net)
    source_hash = _required_string(net, "flux_input_sha256")
    _required_string(net, "flux_source_db")
    bus_ids = _source_bus_ids(net)
    lookup = _element_lookup(net)
    candidates: dict[int, dict[str, object]] = {}

    for element_id, table_name, row_index in _generator_rows(lookup):
        row = _row(_table(net, table_name), row_index, element_id)
        bus_index = _integer(row.get("bus"), f"{element_id}.bus")
        bus_id = bus_ids.get(bus_index)
        if bus_id is None:
            raise SyntheticCandidateSourceUnavailable(
                f"{element_id} references a bus absent from flux_bus_index"
            )
        bus = _row(_table(net, "bus"), bus_index, f"bus {bus_id}")
        base_kv = _positive_number(bus.get("vn_kv"), f"bus {bus_id}.vn_kv")
        capacity_mw = _candidate_capacity(row.get("pmax_mw"), f"{element_id}.pmax_mw")
        if base_kv < MIN_INTERCONNECT_KV:
            continue
        # A zero-capacity source record supplies no declared capability for an
        # added-unit attachment comparison.  It is therefore ineligible, not
        # an unavailable network: other declared generators may still form a
        # bounded candidate population.
        if capacity_mw is None:
            continue
        generator_id = _generator_id(element_id)
        candidate = {
            "candidate_id": f"synthetic-generator:{generator_id}",
            "bus_id": bus_id,
            "source_generator_id": generator_id,
            "source_capacity_mw": capacity_mw,
            "base_kv": base_kv,
            "interconnect_distance_km": 0.0,
            "synthetic": True,
            "candidate_provenance": {
                "source_kind": "synthetic_topology_derived",
                "topology": topology,
                "derivation": (
                    "existing synthetic generator record joined to its declared "
                    "synthetic bus; model attachment point only, not a physical "
                    "site or interconnection claim"
                ),
                "generator_element_id": element_id,
                "source_bus_id": bus_id,
                "grid_input_sha256": source_hash,
            },
        }
        current = candidates.get(bus_id)
        if current is None or generator_id < int(current["source_generator_id"]):
            candidates[bus_id] = candidate

    return sorted(
        candidates.values(),
        key=lambda candidate: (
            int(candidate["source_generator_id"]),
            int(candidate["bus_id"]),
        ),
    )[:MAX_SYNTHETIC_PRODUCER_CANDIDATES]


def _required_synthetic_topology(net: object) -> str:
    topology = _required_string(net, "flux_topology")
    if topology != SYNTHETIC_TOPOLOGY_LABEL:
        raise SyntheticCandidateSourceUnavailable(
            "synthetic producer candidates require the declared synthetic topology"
        )
    return topology


def _required_string(net: object, name: str) -> str:
    value = _value(net, name)
    if not isinstance(value, str) or not value.strip():
        raise SyntheticCandidateSourceUnavailable(f"network lacks {name}")
    return value


def _source_bus_ids(net: object) -> dict[int, int]:
    raw = _value(net, "flux_bus_index")
    if not isinstance(raw, Mapping):
        raise SyntheticCandidateSourceUnavailable("network lacks flux_bus_index")
    result: dict[int, int] = {}
    for source_id, bus_index in raw.items():
        source = _integer(source_id, "flux_bus_index source id")
        index = _integer(bus_index, "flux_bus_index bus index")
        if index in result and result[index] != source:
            raise SyntheticCandidateSourceUnavailable(
                "flux_bus_index has ambiguous source bus identity"
            )
        result[index] = source
    return result


def _element_lookup(net: object) -> Mapping[object, object]:
    lookup = _value(net, "flux_element_lookup")
    if not isinstance(lookup, Mapping):
        raise SyntheticCandidateSourceUnavailable("network lacks flux_element_lookup")
    return lookup


def _generator_rows(lookup: Mapping[object, object]) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    for raw_element_id, raw_location in lookup.items():
        if not isinstance(raw_element_id, str) or not raw_element_id.startswith(
            "generator:"
        ):
            continue
        _generator_id(raw_element_id)
        # ``build_network`` records these as tuples on the ordinary builder
        # path and as lists on the native-PPC path.  Both are its declared
        # two-field identity metadata, so accept either representation while
        # retaining the strict table and row checks below.
        if (
            not isinstance(raw_location, (tuple, list))
            or len(raw_location) != 2
            or raw_location[0] not in {"gen", "sgen", "ext_grid"}
        ):
            raise SyntheticCandidateSourceUnavailable(
                f"{raw_element_id} lacks a declared generator row"
            )
        rows.append(
            (raw_element_id, str(raw_location[0]), _integer(raw_location[1], raw_element_id))
        )
    if not rows:
        raise SyntheticCandidateSourceUnavailable(
            "network has no declared synthetic generator records"
        )
    return sorted(rows, key=lambda row: (_generator_id(row[0]), row[0]))


def _generator_id(element_id: str) -> int:
    raw = element_id.removeprefix("generator:")
    return _integer(raw, "generator element id")


def _table(net: object, name: str) -> Any:
    table = _value(net, name)
    if table is None or not hasattr(table, "loc"):
        raise SyntheticCandidateSourceUnavailable(f"network lacks {name} table")
    return table


def _row(table: Any, index: int, label: str) -> dict[str, object]:
    try:
        raw = table.loc[index]
    except (KeyError, TypeError, ValueError) as exc:
        raise SyntheticCandidateSourceUnavailable(
            f"declared source row {label!r} is unavailable"
        ) from exc
    if not hasattr(raw, "to_dict"):
        raise SyntheticCandidateSourceUnavailable(f"declared source row {label!r} is invalid")
    value = raw.to_dict()
    if not isinstance(value, Mapping):
        raise SyntheticCandidateSourceUnavailable(f"declared source row {label!r} is invalid")
    return dict(value)


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise SyntheticCandidateSourceUnavailable(f"{label} must be an integer")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SyntheticCandidateSourceUnavailable(f"{label} must be an integer") from exc
    if not isfinite(number) or number != int(number):
        raise SyntheticCandidateSourceUnavailable(f"{label} must be an integer")
    return int(number)


def _positive_number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise SyntheticCandidateSourceUnavailable(f"{label} must be a finite positive number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SyntheticCandidateSourceUnavailable(
            f"{label} must be a finite positive number"
        ) from exc
    if not isfinite(number) or number <= 0.0:
        raise SyntheticCandidateSourceUnavailable(
            f"{label} must be a finite positive number"
        )
    return number


def _candidate_capacity(value: object, label: str) -> float | None:
    """Return declared usable capacity, skipping explicit zero-capacity rows."""

    if isinstance(value, bool):
        raise SyntheticCandidateSourceUnavailable(f"{label} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SyntheticCandidateSourceUnavailable(f"{label} must be a finite number") from exc
    if not isfinite(number):
        raise SyntheticCandidateSourceUnavailable(f"{label} must be a finite number")
    return number if number > 0.0 else None


def _value(net: object, name: str) -> object:
    if isinstance(net, Mapping):
        return net.get(name)
    getter = getattr(net, "get", None)
    if callable(getter):
        return getter(name)
    return getattr(net, name, None)

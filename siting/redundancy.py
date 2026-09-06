"""Bounded, deterministic topology redundancy checks for consumer buses.

This module deliberately runs only bounded, in-memory checks and never
persists a result.  Duck-typed networks receive a topology-only screen.  A
built Flux network also receives one immutable twin cascade replay per selected
N-1 contingency; that result remains synthetic-topology evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from math import isfinite
from typing import Any

import networkx as nx

MAX_CONTINGENCIES = 20


def score_redundancy(
    net: Any,
    bus_id: Any,
    *,
    scenario_id: str = "interactive",
    hour: int = 0,
    max_contingencies: int = MAX_CONTINGENCIES,
) -> dict[str, Any]:
    """Score a consumer bus's bounded N-1 topology redundancy.

    The candidate contingencies are the highest available DPTF-ranked active
    branches, capped at ``max_contingencies`` (20 by default).  Ties use the
    stable branch identifier, so a repeated call has the same contingency set
    and named worst contingency.

    ``net`` is intentionally duck typed.  Pandapower-style ``line``,
    ``trafo``, ``ext_grid``, ``gen`` and ``sgen`` tables work directly; small
    test or adapter networks may instead expose ``branches`` and ``sources``
    row collections.  A branch row needs endpoints (``from_bus``/``to_bus``
    or ``hv_bus``/``lv_bus``), and optional ``dptf`` or flow fields.
    """
    if max_contingencies < 0:
        raise ValueError("max_contingencies must be non-negative")
    max_contingencies = min(max_contingencies, MAX_CONTINGENCIES)

    reported_bus_id = _normalise_bus_id(bus_id)
    target = _network_bus_id(net, reported_bus_id)
    graph, branches = _graph_from_net(net)
    sources = _source_buses(net)
    synthetic = _synthetic_topology(net)

    evidence: dict[str, Any] = {
        "status": "topology_only",
        "synthetic_topology": synthetic,
        "scenario_id": scenario_id,
        "hour": hour,
        "branch_selection": "highest available DPTF-ranked in-service branches",
        "persistence": "not_persisted",
        "cascade": "not_run",
        "source_buses": sorted(sources, key=_sort_key),
    }

    if target not in graph:
        return _unavailable_result(
            reported_bus_id,
            evidence,
            "target_bus_not_in_active_topology",
            branch_count=len(branches),
        )
    if not sources:
        return _unavailable_result(
            reported_bus_id,
            evidence,
            "no_available_source_bus",
            branch_count=len(branches),
        )

    ranked = sorted(branches, key=lambda branch: (-branch["dptf"], branch["id"]))
    selected = ranked[:max_contingencies]
    baseline = _topology_components(graph, target, sources)

    contingencies: list[dict[str, Any]] = []
    for branch in selected:
        state, cascade_metrics = _contingency_state(net, graph, branch, target, sources)
        impact = _contingency_impact(baseline, state)
        contingencies.append(
            {
                "branch_id": branch["id"],
                "branch_name": branch["name"],
                "dptf": branch["dptf"],
                "source_reachable": state["source_reachable"],
                "available_source_count": state["reachable_source_count"],
                "nearest_source_hops": state["nearest_source_hops"],
                "impact": impact,
                "cascade_metrics": cascade_metrics,
            }
        )

    survivability = (
        100.0
        if not contingencies
        else 100.0
        * sum(1 for item in contingencies if item["source_reachable"])
        / len(contingencies)
    )
    path_score = min(100.0, 50.0 * baseline["edge_disjoint_paths"])
    proximity_score = _proximity_score(baseline["alternative_source_hops"])
    components = {
        "n_minus_one_survivability": round(survivability, 3),
        "edge_disjoint_paths": baseline["edge_disjoint_paths"],
        "edge_disjoint_path_score": round(path_score, 3),
        "alternative_source_hops": baseline["alternative_source_hops"],
        "alternative_source_proximity": round(proximity_score, 3),
    }
    score = round(0.5 * survivability + 0.3 * path_score + 0.2 * proximity_score, 3)
    worst = min(
        contingencies,
        key=lambda item: (-item["impact"], item["branch_id"]),
        default=None,
    )
    uses_twin = _value(net, "flux_element_lookup", None) is not None
    evidence.update(
        {
            "status": "available_with_twin_cascade" if uses_twin else "available",
            "active_branch_count": len(branches),
            "contingencies_evaluated": len(contingencies),
            "max_contingencies": max_contingencies,
            "cascade": "per_contingency_in_memory" if uses_twin else "not_run",
        }
    )
    return {
        "bus_id": reported_bus_id,
        "score": score,
        "components": components,
        "worst_contingency": worst,
        "synthetic_topology": synthetic,
        "evidence": evidence,
    }


def _unavailable_result(
    target: Any, evidence: dict[str, Any], reason: str, *, branch_count: int) -> dict[str, Any]:
    evidence.update({"status": "unavailable", "reason": reason, "active_branch_count": branch_count})
    return {
        "bus_id": target,
        "score": 0.0,
        "components": {
            "n_minus_one_survivability": 0.0,
            "edge_disjoint_paths": 0,
            "edge_disjoint_path_score": 0.0,
            "alternative_source_hops": None,
            "alternative_source_proximity": 0.0,
        },
        "worst_contingency": None,
        "synthetic_topology": evidence["synthetic_topology"],
        "evidence": evidence,
    }


def _graph_from_net(net: Any) -> tuple[nx.MultiGraph, list[dict[str, Any]]]:
    graph = nx.MultiGraph()
    branches: list[dict[str, Any]] = []
    for position, row in enumerate(_branch_rows(net)):
        if not _as_bool(_field(row, "in_service", True)):
            continue
        u = _field(row, "from_bus", _field(row, "hv_bus", None))
        v = _field(row, "to_bus", _field(row, "lv_bus", None))
        if u is None or v is None:
            continue
        u, v = _normalise_bus_id(u), _normalise_bus_id(v)
        branch_id = str(
            _field(
                row,
                "branch_id",
                _field(row, "element_id", _field(row, "flux_element_id", _field(row, "id", position))),
            )
        )
        kind = str(_field(row, "kind", _field(row, "element_type", "line")))
        if ":" not in branch_id:
            branch_id = f"{kind}:{branch_id}"
        branch = {
            "id": branch_id,
            "name": str(_field(row, "name", branch_id)),
            "u": u,
            "v": v,
            "dptf": _dptf(net, row, branch_id),
        }
        graph.add_edge(u, v, key=branch_id, **branch)
        branches.append(branch)
    return graph, branches


def _branch_rows(net: Any) -> Iterable[Any]:
    explicit = _value(net, "branches", None)
    if explicit is not None:
        yield from _rows(explicit)
        return
    for table_name, kind in (("line", "line"), ("impedance", "impedance"), ("trafo", "trafo")):
        table = _value(net, table_name, None)
        for index, row in _indexed_rows(table):
            if _field(row, "id", None) is None:
                row = {**_mapping(row), "id": index, "kind": kind}
            yield row


def _source_buses(net: Any) -> set[Any]:
    explicit = _value(net, "sources", None)
    if explicit is not None:
        rows = _rows(explicit)
    else:
        # The cascade contract defines only ext_grid as grid forming.  A
        # generator's capacity does not make it an alternative source here.
        tables = ("ext_grid",) if _value(net, "flux_element_lookup", None) is not None else ("ext_grid", "gen", "sgen")
        rows = (row for name in tables for _, row in _indexed_rows(_value(net, name, None)))
    return {
        _normalise_bus_id(bus)
        for row in rows
        if _as_bool(_field(row, "in_service", True))
        and (bus := _field(row, "bus", _field(row, "source_bus", None))) is not None
    }


def _topology_components(graph: nx.MultiGraph, target: Any, sources: set[Any]) -> dict[str, Any]:
    distances = sorted(
        [
            (distance, source)
            for source in sources
            if source in graph and (distance := _shortest_distance(graph, target, source)) is not None
        ],
        key=lambda item: (item[0], _sort_key(item[1])),
    )
    reachable_sources = [source for _, source in distances]
    edge_disjoint = _edge_disjoint_to_sources(graph, target, reachable_sources)
    return {
        "source_reachable": bool(reachable_sources),
        "reachable_source_count": len(reachable_sources),
        "nearest_source_hops": distances[0][0] if distances else None,
        "alternative_source_hops": distances[1][0] if len(distances) > 1 else None,
        "edge_disjoint_paths": edge_disjoint,
    }


def _contingency_state(
    net: Any,
    graph: nx.MultiGraph,
    branch: dict[str, Any],
    target: Any,
    sources: set[Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Use the twin's immutable adapters when this is a built Flux network."""
    if _value(net, "flux_element_lookup", None) is not None:
        from twin.cascade import island_primitives, run_cascade
        from twin.edits import outage

        edits = (outage(branch["id"]),)
        component = next(
            (item for item in island_primitives(net, edits) if _reported_bus_id(net, target) in item["bus_ids"]),
            None,
        )
        cascade = run_cascade(net, edits)
        state = _topology_components_after_edit(graph, branch, target, sources)
        if component is not None:
            state["source_reachable"] = bool(component["has_grid_forming_source"])
            state["reachable_source_count"] = int(bool(component["has_grid_forming_source"]))
        return state, {
            "lost_load_mw": cascade["lost_load_mw"],
            "served_load_mw": cascade["served_load_mw"],
            "edit_hash": cascade["edit_hash"],
        }
    return _topology_components_after_edit(graph, branch, target, sources), None


def _topology_components_after_edit(
    graph: nx.MultiGraph,
    branch: dict[str, Any],
    target: Any,
    sources: set[Any],
) -> dict[str, Any]:
    contingency_graph = graph.copy()
    contingency_graph.remove_edge(branch["u"], branch["v"], key=branch["id"])
    return _topology_components(contingency_graph, target, sources)


def _shortest_distance(graph: nx.MultiGraph, start: Any, end: Any) -> int | None:
    try:
        return int(nx.shortest_path_length(graph, start, end))
    except nx.NetworkXNoPath:
        return None


def _edge_disjoint_to_sources(graph: nx.MultiGraph, start: Any, sources: Iterable[Any]) -> int:
    # Convert each parallel branch to a distinct intermediate node.  A plain
    # Graph would incorrectly collapse parallel circuits into one edge.
    split = nx.Graph()
    split.add_nodes_from(graph.nodes)
    for u, v, key in graph.edges(keys=True):
        branch_node = ("branch", key)
        split.add_edge(u, branch_node)
        split.add_edge(branch_node, v)
    terminal = ("supply-terminal",)
    # A source can supply more than one edge-disjoint path.  Give each source
    # enough distinct terminal edges that its terminal connection cannot become
    # the artificial bottleneck in the physical branch count.
    for source in sources:
        if source == start:
            continue
        for position in range(len(graph.edges) + 1):
            connector = ("supply-connector", source, position)
            split.add_edge(source, connector)
            split.add_edge(connector, terminal)
    try:
        return sum(1 for _ in nx.edge_disjoint_paths(split, start, terminal))
    except (nx.NetworkXNoPath, nx.NetworkXError):
        return 0


def _contingency_impact(base: dict[str, Any], state: dict[str, Any]) -> float:
    if not state["source_reachable"]:
        return 10_000.0
    distance_increase = max(0, (state["nearest_source_hops"] or 0) - (base["nearest_source_hops"] or 0))
    source_loss = max(0, base["reachable_source_count"] - state["reachable_source_count"])
    path_loss = max(0, base["edge_disjoint_paths"] - state["edge_disjoint_paths"])
    return 1_000.0 * path_loss + 100.0 * source_loss + distance_increase


def _proximity_score(hops: int | None) -> float:
    return 0.0 if hops is None else 100.0 / (1.0 + hops)


def _dptf(net: Any, row: Any, branch_id: str) -> float:
    for name in ("dptf_by_branch", "flux_dptf_by_element"):
        values = _value(net, name, None)
        if isinstance(values, Mapping) and branch_id in values:
            value = _as_float(values[branch_id])
            if value is not None:
                return abs(value)
    for name in ("dptf", "dptf_mw", "p_from_mw", "p_to_mw", "loading_percent"):
        value = _as_float(_field(row, name, None))
        if value is not None:
            return abs(value)
    return 0.0


def _synthetic_topology(net: Any) -> bool:
    value = _value(net, "synthetic_topology", None)
    if value is None:
        topology = _value(net, "flux_topology", None)
        if topology is not None:
            return "synthetic" in str(topology).lower()
        metadata = _value(net, "metadata", {})
        value = _field(metadata, "synthetic_topology", True)
    return _as_bool(value)


def _value(value: Any, name: str, default: Any) -> Any:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _field(row: Any, name: str, default: Any) -> Any:
    return row.get(name, default) if isinstance(row, Mapping) else getattr(row, name, default)


def _mapping(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    if is_dataclass(row):
        return asdict(row)
    if hasattr(row, "to_dict"):
        return dict(row.to_dict())
    return dict(vars(row))


def _rows(table: Any) -> Iterable[Any]:
    if table is None:
        return ()
    if isinstance(table, Mapping):
        return table.values()
    if hasattr(table, "to_dict"):
        return table.to_dict("records")
    return table


def _indexed_rows(table: Any) -> Iterable[tuple[Any, Any]]:
    if table is None:
        return ()
    if hasattr(table, "iterrows"):
        return table.iterrows()
    if isinstance(table, Mapping):
        return table.items()
    return enumerate(table)


def _as_bool(value: Any) -> bool:
    return bool(value) if value is not None else False


def _as_float(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if isfinite(converted) else None


def _normalise_bus_id(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value


def _network_bus_id(net: Any, bus_id: Any) -> Any:
    mapping = _value(net, "flux_bus_index", None)
    if isinstance(mapping, Mapping):
        try:
            return mapping[int(bus_id)]
        except (KeyError, TypeError, ValueError):
            return bus_id
    return bus_id


def _reported_bus_id(net: Any, bus_id: Any) -> Any:
    metadata = _value(net, "flux_bus_metadata", None)
    if isinstance(metadata, Mapping) and bus_id in metadata:
        return metadata[bus_id].get("bus_id", bus_id)
    return bus_id


def _sort_key(value: Any) -> tuple[str, str]:
    return type(value).__name__, str(value)

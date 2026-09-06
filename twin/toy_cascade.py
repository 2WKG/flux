"""The explainer's low-complexity DC screening example, solved on the server.

The explainer page (`web/src/pages/ExplainerPage.tsx`) teaches the chain a DC
screening model follows: balance island injections, solve line flows, compare a
flow to a rating, trip the worst overload, solve again. It used to run that
chain in the browser, which put a second simulation engine next to
`twin/cascade.py` and made the browser compute an answer. This module owns the
teaching solve instead; `scripts/export_toy_cascade_trace.py` freezes its output
into `data/explainer/toy-cascade-trace.json`, and the page replays that trace.

This is deliberately NOT `twin/cascade.py`. It is a five-bus teaching network
with hand-picked reactances and ratings, no pandapower, no DuckDB, no weather
and no county attribution. It is not the product's solver and must not be
reused as one; see `docs/specs/03-cascade-sim.md` -> "Explainer teaching solve".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

SCHEMA_VERSION = 1

#: The initiating outage the lesson is built around.
INITIATING_LINE_ID = "hub-east"

#: The teaching rule trips at most this many lines after the initiating outage.
MAX_CASCADE_TRIPS = 3

_ZERO_TOLERANCE = 1e-9


@dataclass(frozen=True)
class ToyBus:
    id: str
    name: str
    generation_mw: float
    demand_mw: float
    x: float
    y: float


@dataclass(frozen=True)
class ToyLine:
    id: str
    from_bus: str
    to_bus: str
    reactance: float
    rating_mw: float


class ToyCascadeError(RuntimeError):
    """A named refusal from the teaching solve. Never a plausible default."""


TOY_BUSES: tuple[ToyBus, ...] = (
    ToyBus("west", "West generator", 120.0, 0.0, 84, 185),
    ToyBus("north", "North load", 40.0, 50.0, 255, 65),
    ToyBus("hub", "Central hub", 0.0, 30.0, 390, 185),
    ToyBus("east", "East load", 0.0, 70.0, 590, 125),
    ToyBus("south", "South load", 0.0, 10.0, 490, 330),
)

TOY_LINES: tuple[ToyLine, ...] = (
    ToyLine("west-north", "west", "north", 0.25, 80.0),
    ToyLine("west-hub", "west", "hub", 0.20, 110.0),
    ToyLine("north-hub", "north", "hub", 0.25, 80.0),
    ToyLine("hub-east", "hub", "east", 0.20, 90.0),
    ToyLine("hub-south", "hub", "south", 0.25, 70.0),
    ToyLine("east-south", "east", "south", 0.25, 35.0),
)

_BUS_BY_ID = {bus.id: bus for bus in TOY_BUSES}
_LINE_BY_ID = {line.id: line for line in TOY_LINES}


def _number(value: float) -> float:
    """Collapse solver noise to a signed-zero-free 0 and fix to 6 decimals."""
    return 0.0 if abs(value) < _ZERO_TOLERANCE else round(value, 6) + 0.0


def _connected_components(active_lines: tuple[ToyLine, ...]) -> list[list[str]]:
    neighbours: dict[str, list[str]] = {bus.id: [] for bus in TOY_BUSES}
    for line in active_lines:
        neighbours[line.from_bus].append(line.to_bus)
        neighbours[line.to_bus].append(line.from_bus)
    unseen = [bus.id for bus in TOY_BUSES]
    components: list[list[str]] = []
    while unseen:
        first = unseen.pop(0)
        component = [first]
        todo = [first]
        while todo:
            current = todo.pop()
            for neighbour in neighbours[current]:
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    component.append(neighbour)
                    todo.append(neighbour)
        components.append(component)
    return components


def _balance_components(
    active_lines: tuple[ToyLine, ...],
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    injections = {bus.id: bus.generation_mw - bus.demand_mw for bus in TOY_BUSES}
    actions: list[dict[str, Any]] = []
    for component in _connected_components(active_lines):
        total = sum(injections[bus_id] for bus_id in component)
        if abs(total) < _ZERO_TOLERANCE:
            continue
        shedding = total < 0
        candidates = [
            _BUS_BY_ID[bus_id]
            for bus_id in component
            if (
                _BUS_BY_ID[bus_id].demand_mw
                if shedding
                else _BUS_BY_ID[bus_id].generation_mw
            )
            > 0
        ]
        denominator = sum(
            (bus.demand_mw if shedding else bus.generation_mw) for bus in candidates
        )
        if not denominator:
            raise ToyCascadeError(
                f"Cannot balance component containing {', '.join(component)}."
            )
        for bus in candidates:
            share = bus.demand_mw if shedding else bus.generation_mw
            mw = abs(total) * (share / denominator)
            injections[bus.id] += mw if shedding else -mw
            actions.append(
                {
                    "busId": bus.id,
                    "kind": "shed_load" if shedding else "curtail_generation",
                    "mw": _number(mw),
                }
            )
    return injections, actions


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gauss-Jordan elimination. The teaching system is at most 4x4."""
    size = len(matrix)
    augmented = [list(row) + [vector[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < _ZERO_TOLERANCE:
            raise ToyCascadeError("Toy DC matrix is singular.")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * augmented[column][index]
                for index, value in enumerate(augmented[row])
            ]
    return [_number(row[-1]) for row in augmented]


def solve_toy_dc(active_line_ids: frozenset[str]) -> dict[str, Any]:
    """Balance every island, then solve B-theta for the active corridors."""
    active_lines = tuple(line for line in TOY_LINES if line.id in active_line_ids)
    injections, actions = _balance_components(active_lines)
    angles = {bus.id: 0.0 for bus in TOY_BUSES}
    for component in _connected_components(active_lines):
        if len(component) < 2:
            continue
        unknowns = [bus_id for bus_id in component if bus_id != component[0]]
        index = {bus_id: position for position, bus_id in enumerate(unknowns)}
        matrix = [[0.0] * len(unknowns) for _ in unknowns]
        vector = [injections[bus_id] for bus_id in unknowns]
        for line in active_lines:
            susceptance = 1 / line.reactance
            from_index = index.get(line.from_bus)
            to_index = index.get(line.to_bus)
            if from_index is not None:
                matrix[from_index][from_index] += susceptance
                if to_index is not None:
                    matrix[from_index][to_index] -= susceptance
            if to_index is not None:
                matrix[to_index][to_index] += susceptance
                if from_index is not None:
                    matrix[to_index][from_index] -= susceptance
        solution = _solve_linear_system(matrix, vector)
        for bus_id in unknowns:
            angles[bus_id] = solution[index[bus_id]]
    lines = []
    for line in active_lines:
        flow_mw = _number(
            (angles[line.from_bus] - angles[line.to_bus]) / line.reactance
        )
        lines.append(
            {
                "id": line.id,
                "from": line.from_bus,
                "to": line.to_bus,
                "reactance": line.reactance,
                "ratingMw": line.rating_mw,
                "flowMw": flow_mw,
                "utilizationPct": _number(abs(flow_mw) / line.rating_mw * 100),
            }
        )
    return {
        "injections": {bus_id: _number(value) for bus_id, value in injections.items()},
        "actions": actions,
        "angles": angles,
        "lines": lines,
    }


def _most_overloaded(lines: list[dict[str, Any]]) -> str | None:
    overloaded = [line for line in lines if line["utilizationPct"] > 100]
    if not overloaded:
        return None
    overloaded.sort(key=lambda line: (-line["utilizationPct"], line["id"]))
    return str(overloaded[0]["id"])


def run_toy_cascade() -> list[dict[str, Any]]:
    """The seeded outage, the re-dispatch, and the overload trips that follow."""
    open_lines: set[str] = set()
    stages: list[dict[str, Any]] = []

    def add_stage(
        stage_id: str, title: str, explanation: str, tripped_line_id: str | None
    ) -> None:
        active_line_ids = [line.id for line in TOY_LINES if line.id not in open_lines]
        solved = solve_toy_dc(frozenset(active_line_ids))
        stages.append(
            {
                "id": stage_id,
                "title": title,
                "explanation": explanation,
                "trippedLineId": tripped_line_id,
                "activeLineIds": active_line_ids,
                "injectionsMw": solved["injections"],
                "angles": solved["angles"],
                "balanceActions": solved["actions"],
                "lines": solved["lines"],
                "nextTripLineId": _most_overloaded(solved["lines"]),
            }
        )

    add_stage(
        "base",
        "1. Normal toy network",
        "All six synthetic corridors are available. DC flow balances the five specified bus injections.",
        None,
    )
    open_lines.add(INITIATING_LINE_ID)
    add_stage(
        "event",
        "2. Synthetic initiating outage",
        "For teaching purposes, Central hub → East load trips. Re-solving redistributes its power through East load → South load.",
        INITIATING_LINE_ID,
    )
    for step in range(MAX_CASCADE_TRIPS):
        next_trip = stages[-1]["nextTripLineId"]
        if not next_trip:
            break
        open_lines.add(next_trip)
        line = _LINE_BY_ID[next_trip]
        add_stage(
            f"cascade-{step + 1}",
            f"3. Cascade trip {step + 1}",
            f"{line.from_bus} → {line.to_bus} exceeds its thermal rating, so this toy rule removes the most overloaded remaining line and re-solves.",
            next_trip,
        )
    return stages


def trace_hash(stages: list[dict[str, Any]]) -> str:
    """A stable digest of the frozen stages, so a replayed trace is checkable."""
    canonical = json.dumps(stages, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def toy_cascade_trace() -> dict[str, Any]:
    """The whole persisted artifact: network, stages, and the digest over them."""
    stages = run_toy_cascade()
    kind: Literal["synthetic_five_bus_teaching_network"] = (
        "synthetic_five_bus_teaching_network"
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "modelFidelity": "dc_screening",
        "networkProvenance": kind,
        "networkLabel": "synthetic five-bus teaching network",
        "limitations": [
            "Synthetic five-bus teaching network; not ACTIVSg2000, not a physical asset, and not an interconnection result.",
            "DC screening excludes AC voltage, transient stability, protection, unit commitment, and regulatory feasibility.",
            "This teaching solve is deliberately independent of twin/cascade.py and is not the product's solver.",
        ],
        "network": {
            "buses": [
                {
                    "id": bus.id,
                    "name": bus.name,
                    "generationMw": bus.generation_mw,
                    "demandMw": bus.demand_mw,
                    "x": bus.x,
                    "y": bus.y,
                }
                for bus in TOY_BUSES
            ],
            "lines": [
                {
                    "id": line.id,
                    "from": line.from_bus,
                    "to": line.to_bus,
                    "reactance": line.reactance,
                    "ratingMw": line.rating_mw,
                }
                for line in TOY_LINES
            ],
        },
        "stages": stages,
        "traceHash": trace_hash(stages),
    }

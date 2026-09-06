"""Deterministic, flow-aware contingency plans for solver-labelled samples.

The sampler is deliberately separate from labelling.  A plan can therefore be
hashed, split, inspected, and resumed before an expensive solver call starts.
It uses solved base-case branch flows to favour consequential outages while
retaining deterministic pseudo-random coverage inside the eligible set.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from typing import Any

from gnn.contracts import (
    BranchFlow,
    HourPoint,
    PlannedSample,
    SamplingError,
    derive_seed,
)


@dataclass(frozen=True)
class SamplerConfig:
    """The complete plan policy.  Its JSON form is persisted in the manifest."""

    n1_per_hour: int = 2
    n2_per_hour: int = 1
    placement_per_hour: int = 1
    generator_unit_mw: float = 300.0
    added_load_mw: float = 100.0
    min_site_kv: float = 115.0

    def validate(self) -> None:
        counts = (self.n1_per_hour, self.n2_per_hour, self.placement_per_hour)
        if any(int(value) < 0 for value in counts):
            raise SamplingError("sample counts must be non-negative")
        if self.n1_per_hour == 0 and (self.n2_per_hour or self.placement_per_hour):
            raise SamplingError(
                "N-2 and placement samples require at least one N-1 sample"
            )
        if any(
            float(value) <= 0 for value in (self.generator_unit_mw, self.added_load_mw)
        ):
            raise SamplingError("placement MW values must be positive")
        if float(self.min_site_kv) <= 0:
            raise SamplingError("minimum site kV must be positive")

    def json(self) -> dict[str, Any]:
        return asdict(self)


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def plan_identity(plan: PlannedSample, *, seed: int, scenario_id: str) -> str:
    """Stable opaque identity for one plan, independent of a process RNG."""
    payload = {"plan": plan.json(), "scenario_id": scenario_id, "seed": int(seed)}
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def baseline_branch_flows(net: Any) -> list[BranchFlow]:
    """Solve the unmodified state and return every active labelled branch flow."""
    import pandapower as pp

    try:
        pp.rundcpp(net)
    except Exception as exc:
        raise SamplingError(f"unable to solve baseline DC flow: {exc}") from exc
    if not bool(net.converged):
        raise SamplingError("baseline DC flow did not converge")

    output: list[BranchFlow] = []
    for table in ("line", "impedance"):
        if table not in net or net[table].empty:
            continue
        result_table = net[f"res_{table}"]
        for index, row in net[table].iterrows():
            if not bool(row.in_service):
                continue
            element_id = row.get("flux_element_id")
            if not isinstance(element_id, str) or not element_id:
                continue
            result = result_table.loc[index]
            flow = max(abs(float(result.p_from_mw)), abs(float(result.p_to_mw)))
            if table == "line":
                loading = float(result.loading_percent)
                rating = _line_rating_mva(row, net)
                first, second = int(row.from_bus), int(row.to_bus)
            else:
                rating = _finite_or_none(row.get("sn_mva"))
                loading = (
                    None if rating is None or rating <= 0 else flow / rating * 100.0
                )
                first, second = int(row.from_bus), int(row.to_bus)
            output.append(
                BranchFlow(
                    element_id=element_id,
                    table=table,
                    index=int(index),
                    from_bus=first,
                    to_bus=second,
                    abs_flow_mw=round(flow, 9),
                    rating_mva=rating,
                    loading_percent=None if loading is None else round(loading, 9),
                )
            )
    if not output:
        raise SamplingError("baseline network has no active labelled branches")
    return sorted(output, key=lambda item: item.element_id)


def build_plan(
    net: Any,
    hours: Iterable[HourPoint],
    *,
    seed: int,
    config: SamplerConfig | None = None,
) -> list[PlannedSample]:
    """Build a reproducible set of baseline, N-1, N-2, and placement plans.

    Every N-2 and placement plan is attached to an N-1 primary contingency by
    ``group_key``.  That family key is the indivisible train/held-out unit.
    """
    policy = config or SamplerConfig()
    policy.validate()
    points = sorted(hours, key=lambda item: (item.hour, item.ts))
    if not points:
        raise SamplingError("cannot plan samples without observed demand hours")
    flows = baseline_branch_flows(net)
    candidates = _weighted_order(flows, derive_seed(seed, "contingency-candidates"))
    if len(candidates) < 2 and policy.n2_per_hour:
        raise SamplingError(
            "N-2 sampling requires at least two active labelled branches"
        )
    site_buses = _site_buses(net, min_kv=policy.min_site_kv)
    if policy.placement_per_hour and not site_buses:
        raise SamplingError(
            "placement sampling requires an active bus at the configured kV"
        )

    plans: list[PlannedSample] = []
    next_index = 0
    for point in points:
        plans.append(
            PlannedSample(
                sample_index=next_index,
                kind="baseline",
                hour=point.hour,
                element_ids=(),
                primary_element_id=None,
                group_key=f"baseline:hour:{point.hour}",
            )
        )
        next_index += 1
        primary = _choose_many(
            candidates,
            policy.n1_per_hour,
            derive_seed(seed, "n1", point.hour),
        )
        for ordinal, branch in enumerate(primary):
            group_key = f"contingency:{branch.element_id}"
            plans.append(
                PlannedSample(
                    sample_index=next_index,
                    kind="n1",
                    hour=point.hour,
                    element_ids=(branch.element_id,),
                    primary_element_id=branch.element_id,
                    group_key=group_key,
                )
            )
            next_index += 1
            alternatives = [
                item for item in candidates if item.element_id != branch.element_id
            ]
            for secondary in _choose_many(
                alternatives,
                policy.n2_per_hour,
                derive_seed(seed, "n2", point.hour, branch.element_id),
            ):
                element_ids = tuple(sorted((branch.element_id, secondary.element_id)))
                plans.append(
                    PlannedSample(
                        sample_index=next_index,
                        kind="n2",
                        hour=point.hour,
                        element_ids=element_ids,
                        primary_element_id=branch.element_id,
                        group_key=group_key,
                    )
                )
                next_index += 1
            for placement_ordinal in range(policy.placement_per_hour):
                site_bus = site_buses[
                    derive_seed(
                        seed,
                        "placement-site",
                        point.hour,
                        branch.element_id,
                        placement_ordinal,
                    )
                    % len(site_buses)
                ]
                kind = (
                    "placement_gen" if placement_ordinal % 2 == 0 else "placement_load"
                )
                plans.append(
                    PlannedSample(
                        sample_index=next_index,
                        kind=kind,
                        hour=point.hour,
                        element_ids=(branch.element_id,),
                        primary_element_id=branch.element_id,
                        group_key=group_key,
                        site_bus=site_bus,
                        unit_mw=policy.generator_unit_mw
                        if kind == "placement_gen"
                        else None,
                        added_load_mw=policy.added_load_mw
                        if kind == "placement_load"
                        else None,
                    )
                )
                next_index += 1
    return _coalesce_contingency_families(plans)


def _coalesce_contingency_families(
    plans: list[PlannedSample],
) -> list[PlannedSample]:
    """Make every overlapping contingency family indivisible for splitting."""
    parent: dict[str, str] = {}

    def find(value: str) -> str:
        parent.setdefault(value, value)
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def join(first: str, second: str) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parent[max(first_root, second_root)] = min(first_root, second_root)

    for plan in plans:
        if plan.element_ids:
            for element_id in plan.element_ids[1:]:
                join(plan.element_ids[0], element_id)
            find(plan.element_ids[0])
    members: dict[str, list[str]] = {}
    for element_id in parent:
        members.setdefault(find(element_id), []).append(element_id)
    family_by_element = {
        element_id: "contingency_family:"
        + hashlib.sha256(canonical_json(sorted(component)).encode()).hexdigest()[:16]
        for component in members.values()
        for element_id in component
    }
    return [
        plan
        if not plan.element_ids
        else replace(plan, group_key=family_by_element[plan.element_ids[0]])
        for plan in plans
    ]


def _weighted_order(flows: list[BranchFlow], seed: int) -> list[BranchFlow]:
    """Weighted random permutation, favouring high-flow corridors without replacement."""
    rng = random.Random(seed)
    remaining = list(flows)
    output: list[BranchFlow] = []
    while remaining:
        weights = [max(item.abs_flow_mw, 0.0) for item in remaining]
        if sum(weights) == 0:
            index = rng.randrange(len(remaining))
        else:
            index = _weighted_index(weights, rng)
        output.append(remaining.pop(index))
    return output


def _choose_many(items: list[BranchFlow], count: int, seed: int) -> list[BranchFlow]:
    if count <= 0:
        return []
    if not items:
        raise SamplingError("contingency sampler has no eligible branch")
    order = _weighted_order(items, seed)
    return order[: min(int(count), len(order))]


def _weighted_index(weights: list[float], rng: random.Random) -> int:
    target = rng.random() * sum(weights)
    running = 0.0
    for index, value in enumerate(weights):
        running += value
        if running >= target:
            return index
    return len(weights) - 1


def _site_buses(net: Any, *, min_kv: float) -> list[int]:
    output = []
    for bus, row in net.bus.iterrows():
        if not bool(row.in_service) or float(row.vn_kv) < min_kv:
            continue
        metadata = net.flux_bus_metadata.get(int(bus), {})
        source_id = metadata.get("bus_id")
        if source_id is not None:
            output.append(int(source_id))
    return sorted(set(output))


def _line_rating_mva(row: Any, net: Any) -> float | None:
    current = _finite_or_none(row.get("max_i_ka"))
    voltage = _finite_or_none(net.bus.at[int(row.from_bus), "vn_kv"])
    if current is None or voltage is None or current <= 0 or voltage <= 0:
        return None
    return round(3**0.5 * current * voltage, 9)


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None

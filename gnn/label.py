"""Use the Flux DC cascade solver as the sole source of sample labels."""

from __future__ import annotations

import time
from typing import Any

from gnn.contracts import HourPoint, PlannedSample, SampleLabels, TrainingSample
from gnn.hours import demand_provenance, scaled_network
from gnn.sampler import plan_identity


def label_sample(
    net: Any,
    plan: PlannedSample,
    point: HourPoint,
    *,
    seed: int,
    scenario_id: str,
    scenario_identity: dict[str, Any],
    ba_code: str,
    scale_dispatch: bool = True,
) -> TrainingSample:
    """Label one plan and retain solver failures as explicit failed rows."""
    if plan.hour != point.hour:
        raise ValueError("sample plan hour does not match its demand point")
    sample_id = plan_identity(plan, seed=seed, scenario_id=scenario_id)
    demand = demand_provenance(point, ba_code=ba_code, scale_dispatch=scale_dispatch)
    started = time.monotonic()
    try:
        from twin.cascade import run_cascade

        hourly = scaled_network(net, point, scale_dispatch=scale_dispatch)
        nominal = float(hourly.load.loc[hourly.load.in_service, "p_mw"].sum())
        result = run_cascade(hourly, _edits(plan))
        served = float(result["served_load_mw"])
        lost = float(result["lost_load_mw"])
        shed = max(nominal - served, 0.0)
        labels = SampleLabels(
            lost_load_mw=round(lost, 6),
            total_served_load_mw=round(served, 6),
            total_shed_load_mw=round(shed, 6),
            lost_load_reconciled=abs(lost - shed) <= 1e-5,
            terminal_solve_status="solved",
            # run_cascade exposes terminal overload evidence keyed by element;
            # absent keys mean the solver recorded no terminal overload, not 0%.
            branch_loading_percent={
                str(key): float(value)
                for key, value in sorted(result["loading_by_element"].items())
            },
            out_of_service_element_ids=tuple(
                sorted(
                    {
                        str(event["element_id"])
                        for event in result["tripped_element_ids"]
                        if event["cause"] in {"forced", "overload"}
                    }
                )
            ),
        )
        return TrainingSample(
            sample_id=sample_id,
            plan=plan,
            status="labelled",
            seed=seed,
            scenario_id=scenario_id,
            scenario_identity=scenario_identity,
            demand=demand,
            labels=labels,
            solve_seconds=round(time.monotonic() - started, 6),
        )
    except Exception as exc:  # noqa: BLE001 - a solver exception is a failed training label.
        return TrainingSample(
            sample_id=sample_id,
            plan=plan,
            status="failed",
            seed=seed,
            scenario_id=scenario_id,
            scenario_identity=scenario_identity,
            demand=demand,
            failure_kind=type(exc).__name__,
            failure_message=str(exc),
            solve_seconds=round(time.monotonic() - started, 6),
        )


def _edits(plan: PlannedSample):
    from twin.edits import add_generator, add_load, outage

    edits = [outage(element_id) for element_id in plan.element_ids]
    if plan.kind == "placement_gen":
        edits.append(
            add_generator(
                f"gnn:placement-gen:{plan.sample_index}",
                int(plan.site_bus),
                float(plan.unit_mw),
            )
        )
    elif plan.kind == "placement_load":
        edits.append(
            add_load(
                f"gnn:placement-load:{plan.sample_index}",
                int(plan.site_bus),
                float(plan.added_load_mw),
            )
        )
    return tuple(edits)

"""Reproducible robustness checks for Flux's checked-in synthetic preview.

This validates only the power-balance fixture used by ``generate_demo.py``.  It
does not represent a grid-flow solve, historical replay, or a Minnesota/New
York network study.
"""
from __future__ import annotations

import copy
import json
import platform
import statistics
import sys
import time
from pathlib import Path

from model.generate_demo import artifact_hash, result_payload


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "demo" / "synthetic-cross-scenario-validation-v1.json"
SENSITIVITY_GRID = (
    (0.95, 0.90), (0.95, 1.00), (0.95, 1.10),
    (1.00, 0.90), (1.00, 1.00), (1.00, 1.10),
    (1.05, 0.90), (1.05, 1.00), (1.05, 1.10),
)
UNSEEN_PERTURBATION = {"demandScale": 1.08, "generationAvailabilityScale": 0.94}
NETWORK_COPIES = (1, 5, 10, 20)


def _perturbed_inputs(inputs: dict, demand_scale: float, generation_scale: float) -> dict:
    """Return one synthetic perturbation without changing the source fixture."""
    changed = copy.deepcopy(inputs)
    assumptions = changed["assumptions"]
    assumptions["demandMw"] *= demand_scale
    assumptions["baselineAvailableGenerationMw"] *= generation_scale
    for intervention in changed["interventions"]:
        intervention["modeledContributionMw"] *= generation_scale
    return changed


def _metric_row(scenario: dict) -> dict:
    metrics = scenario["metrics"]
    return {
        "scenarioId": scenario["id"],
        "label": scenario["label"],
        "demandMw": metrics["demandMw"],
        "unservedMw": metrics["shedMw"],
        "unservedMwhOverHorizon": metrics["shedMwh"],
        "horizonHours": metrics["shedMwh"] / metrics["shedMw"] if metrics["shedMw"] else None,
        "fractionDemandUnserved": metrics["shedMw"] / metrics["demandMw"],
        "improvementMw": metrics["improvementMw"],
    }


def normalized_metrics(inputs: dict) -> list[dict]:
    """Report absolute MW/MWh and fraction-unserved for the base fixture."""
    return [_metric_row(item) for item in result_payload(inputs)["scenarios"].values()]


def _a_vs_b(payload: dict) -> str:
    a_shed = payload["scenarios"]["a"]["metrics"]["shedMw"]
    b_shed = payload["scenarios"]["b"]["metrics"]["shedMw"]
    if a_shed < b_shed:
        return "a_better"
    if b_shed < a_shed:
        return "b_better"
    return "tie"


def sensitivity_analysis(inputs: dict) -> dict:
    """Evaluate a fixed demand/availability grid and report any A/B reversal."""
    base_ranking = _a_vs_b(result_payload(inputs))
    rows = []
    for demand_scale, generation_scale in SENSITIVITY_GRID:
        payload = result_payload(_perturbed_inputs(inputs, demand_scale, generation_scale))
        rows.append({
            "demandScale": demand_scale,
            "generationAvailabilityScale": generation_scale,
            "aVsB": _a_vs_b(payload),
            "scenarios": [_metric_row(payload["scenarios"][name]) for name in ("baseline", "a", "b")],
        })
    reversals = [
        {"demandScale": row["demandScale"], "generationAvailabilityScale": row["generationAvailabilityScale"]}
        for row in rows if row["aVsB"] not in {base_ranking, "tie"}
    ]
    return {
        "baseRanking": base_ranking,
        "grid": rows,
        "rankReversals": reversals,
        "tieCount": sum(row["aVsB"] == "tie" for row in rows),
        "finding": "No A/B rank reversal in this grid." if not reversals else "A/B rank reversals found in this grid.",
    }


def unseen_scenario(inputs: dict) -> dict:
    """Run an out-of-grid deterministic perturbation of the same fixture."""
    payload = result_payload(_perturbed_inputs(inputs, **{
        "demand_scale": UNSEEN_PERTURBATION["demandScale"],
        "generation_scale": UNSEEN_PERTURBATION["generationAvailabilityScale"],
    }))
    return {
        "id": "unseen_fixture_colder_shortfall_v1",
        "perturbation": UNSEEN_PERTURBATION,
        "aVsB": _a_vs_b(payload),
        "scenarios": [_metric_row(payload["scenarios"][name]) for name in ("baseline", "a", "b")],
        "scope": "Unseen deterministic perturbation of the checked-in synthetic fixture; it is not a temporal or geographic holdout.",
    }


def _scaled_inputs(inputs: dict, copies: int) -> dict:
    """Replicate only the fixture topology for an execution-cost comparison."""
    scaled = copy.deepcopy(inputs)
    buses, lines = [], []
    for copy_number in range(copies):
        prefix = f"copy-{copy_number}:"
        buses.extend({**bus, "id": prefix + bus["id"]} for bus in inputs["network"]["buses"])
        for line in inputs["network"]["lines"]:
            lines.append({
                **line,
                "id": prefix + line["id"],
                "from": prefix + line["from"],
                "to": prefix + line["to"],
            })
    scaled["network"]["buses"] = buses
    scaled["network"]["lines"] = lines
    for intervention in scaled["interventions"]:
        original = intervention["lineLoadingMultipliers"]
        intervention["lineLoadingMultipliers"] = {
            f"copy-{copy_number}:{line_id}": multiplier
            for copy_number in range(copies)
            for line_id, multiplier in original.items()
        }
    return scaled


def _execute_for_timing(inputs: dict) -> None:
    result_payload(inputs)


def runtime_scaling(inputs: dict, samples: int = 31) -> list[dict]:
    """Measure same-process execution cost for replicated fixture topology.

    The calculation has no grid-flow solver, so these are only Python fixture
    materialization timings; they must not be interpreted as solver scaling.
    """
    measurements = []
    for copies in NETWORK_COPIES:
        scaled = _scaled_inputs(inputs, copies)
        _execute_for_timing(scaled)  # warm-up in the same process
        elapsed_ms = []
        for _ in range(samples):
            start = time.perf_counter_ns()
            _execute_for_timing(scaled)
            elapsed_ms.append((time.perf_counter_ns() - start) / 1_000_000)
        measurements.append({
            "fixtureCopies": copies,
            "busCount": len(scaled["network"]["buses"]),
            "lineCount": len(scaled["network"]["lines"]),
            "sampleCount": samples,
            "medianExecutionMs": round(statistics.median(elapsed_ms), 4),
            "minExecutionMs": round(min(elapsed_ms), 4),
        })
    return measurements


def validation_report(inputs: dict, runtime_samples: int = 31) -> dict:
    """Build the traceable report; analytical fields are deterministic."""
    return {
        "schemaVersion": 1,
        "artifactId": "flux:synthetic-cross-scenario-validation:v1",
        "inputArtifactId": inputs["artifactId"],
        "inputHash": artifact_hash(inputs),
        "modelMode": inputs["assumptions"]["modelMode"],
        "baseMetrics": normalized_metrics(inputs),
        "sensitivity": sensitivity_analysis(inputs),
        "unseenScenario": unseen_scenario(inputs),
        "runtimeScaling": {
            "machine": {
                "platform": platform.platform(),
                "python": sys.version.split()[0],
                "processor": platform.processor() or "unreported",
            },
            "method": "Same Python process, one warm-up per size, then perf_counter_ns around result_payload().",
            "caveat": "This measures fixture materialization only. It does not run or estimate a power-flow, OPF, cascade, or real network solver.",
            "measurements": runtime_scaling(inputs, runtime_samples),
        },
        "transferBoundary": {
            "temporal": "Not evaluated: the fixture is a four-hour static balance, not a time-indexed holdout.",
            "geographic": "Not evaluated: the fixture is explicitly not Minnesota, New York, Texas, ERCOT, MISO, or an actual interconnection model.",
            "computational": "Measured only as in-process fixture materialization across replicated five-bus shapes; no solver scale claim.",
            "futureFeasible": "A Minnesota or New York case remains future/feasible-only until an actual verified case and execution are completed.",
        },
    }


def main() -> None:
    from model.generate_demo import load_inputs

    report = validation_report(load_inputs())
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

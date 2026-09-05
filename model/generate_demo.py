"""Execute Flux's explicit synthetic preview scenario contract.

This is intentionally a small, checked-in fixture model. It is not a replacement
for the Minnesota topology/aggregate-model prerequisite.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "demo" / "synthetic-scenario-input-v1.json"
OUTPUT = ROOT / "data" / "demo" / "bundle.json"


def load_inputs(path: Path = INPUT) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_hash(inputs: dict) -> str:
    payload = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


def line_loadings(inputs: dict, intervention: dict | None) -> dict[str, int]:
    multipliers = intervention["lineLoadingMultipliers"] if intervention else {}
    return {
        line["id"]: round(line["baselineLoadingPct"] * multipliers.get(line["id"], 1))
        for line in inputs["network"]["lines"]
    }


def execute_scenario(inputs: dict, intervention: dict | None) -> dict:
    assumptions = inputs["assumptions"]
    contribution = intervention["modeledContributionMw"] if intervention else 0
    demand = assumptions["demandMw"]
    available = assumptions["baselineAvailableGenerationMw"] + contribution
    shed = max(0, demand - available)
    baseline_shed = demand - assumptions["baselineAvailableGenerationMw"]
    return {
        "id": intervention["id"] if intervention else "baseline",
        "label": intervention["name"] if intervention else "Baseline",
        "status": "available",
        "modelMode": assumptions["modelMode"],
        "assumptionSetId": assumptions["id"],
        "intervention": None if intervention is None else {
            "id": intervention["id"], "capacityMw": intervention["capacityMw"],
            "modeledContributionMw": contribution, "description": intervention["description"],
        },
        "metrics": {
            "shedMw": shed, "shedMwh": shed * assumptions["durationHours"],
            "availableGenerationMw": available, "demandMw": demand,
            "improvementMw": baseline_shed - shed, "lineLoadings": line_loadings(inputs, intervention),
        },
        "units": {"shedMw": "MW", "shedMwh": "MWh", "availableGenerationMw": "MW", "demandMw": "MW", "improvementMw": "MW", "lineLoading": "%"},
        "provenance": {**inputs["provenance"], "artifactId": inputs["artifactId"], "inputHash": artifact_hash(inputs)},
        "limitations": inputs["limitations"],
    }


def result_payload(inputs: dict | None = None) -> dict:
    inputs = load_inputs() if inputs is None else inputs
    scenarios = {"baseline": execute_scenario(inputs, None)}
    scenarios.update({item["id"]: execute_scenario(inputs, item) for item in inputs["interventions"]})
    provenance = {**inputs["provenance"], "artifactId": inputs["artifactId"], "inputHash": artifact_hash(inputs)}
    return {
        "schemaVersion": 2, "generatedFrom": inputs["artifactId"], "fixtureHash": artifact_hash(inputs),
        "execution": {"status": "available", "modelMode": inputs["assumptions"]["modelMode"], "assumptionSetId": inputs["assumptions"]["id"], "assumptions": inputs["assumptions"], "provenance": provenance, "limitations": inputs["limitations"]},
        "network": {
            "buses": inputs["network"]["buses"],
            "lines": [{key: value for key, value in line.items() if key != "baselineLoadingPct"} for line in inputs["network"]["lines"]],
            "candidates": [{key: value for key, value in item.items() if key not in {"modeledContributionMw", "lineLoadingMultipliers"}} for item in inputs["interventions"]],
        },
        "scenarios": scenarios,
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result_payload(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

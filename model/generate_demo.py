"""Build the small deterministic, explicitly synthetic Flux demo bundle.

No downloaded grid case is used here. This is the D01 fallback: a five-bus
illustrative fixture that gives the UI a stable offline result bundle.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "web" / "public" / "demo" / "bundle.json"
DURATION_HOURS = 4

BUSES = [
    {"id": "west", "name": "West Junction", "x": 120, "y": 245, "demandMw": 330, "generationMw": 160},
    {"id": "north", "name": "North Ridge", "x": 315, "y": 110, "demandMw": 220, "generationMw": 175},
    {"id": "central", "name": "Central Hub", "x": 395, "y": 265, "demandMw": 405, "generationMw": 285},
    {"id": "east", "name": "East Plain", "x": 625, "y": 215, "demandMw": 350, "generationMw": 140},
    {"id": "south", "name": "South Bend", "x": 505, "y": 420, "demandMw": 260, "generationMw": 135},
]

LINES = [
    {"id": "w-n", "from": "west", "to": "north", "capacityMw": 190},
    {"id": "w-c", "from": "west", "to": "central", "capacityMw": 220},
    {"id": "n-c", "from": "north", "to": "central", "capacityMw": 175},
    {"id": "c-e", "from": "central", "to": "east", "capacityMw": 205},
    {"id": "c-s", "from": "central", "to": "south", "capacityMw": 165},
    {"id": "e-s", "from": "east", "to": "south", "capacityMw": 150},
]

CANDIDATES = [
    {"id": "a", "name": "Candidate A · West Junction", "busId": "west", "x": 120, "y": 245, "addedMw": 300,
     "description": "Illustrative western addition near stressed import paths."},
    {"id": "b", "name": "Candidate B · East Plain", "busId": "east", "x": 625, "y": 215, "addedMw": 300,
     "description": "Illustrative eastern addition near a constrained demand center."},
]

# Each state is a saved result, not a live power-flow calculation in the browser.
RESULTS = {
    "baseline": {
        "label": "Baseline", "shedMw": 188, "availableGenerationMw": 1177, "demandMw": 1365,
        "lineLoadings": {"w-n": 82, "w-c": 94, "n-c": 69, "c-e": 96, "c-s": 88, "e-s": 74},
    },
    "a": {
        "label": "Candidate A", "shedMw": 51, "availableGenerationMw": 1437, "demandMw": 1365,
        "lineLoadings": {"w-n": 61, "w-c": 77, "n-c": 59, "c-e": 83, "c-s": 70, "e-s": 62},
    },
    "b": {
        "label": "Candidate B", "shedMw": 82, "availableGenerationMw": 1437, "demandMw": 1365,
        "lineLoadings": {"w-n": 78, "w-c": 89, "n-c": 66, "c-e": 75, "c-s": 81, "e-s": 57},
    },
}


def result_payload() -> dict:
    baseline = RESULTS["baseline"]
    scenarios = {}
    for key, result in RESULTS.items():
        delta = baseline["shedMw"] - result["shedMw"]
        scenarios[key] = {
            **result,
            "shedMwh": result["shedMw"] * DURATION_HOURS,
            "improvementMw": delta,
            "improvementMwh": delta * DURATION_HOURS,
            "reasons": ([] if key == "baseline" else [
                "Uses the same synthetic demand, derating and 300 MW addition assumptions as the comparison.",
                ("Reduces modeled imports across the west-to-central path." if key == "a"
                 else "Reduces modeled stress at the east demand center and its adjacent branch."),
            ]),
        }
    fixture = {"buses": BUSES, "lines": LINES, "candidates": CANDIDATES}
    fixture_hash = hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest()[:12]
    return {
        "schemaVersion": 1,
        "generatedFrom": "checked-in synthetic five-bus fixture",
        "fixtureHash": fixture_hash,
        "solverStatus": "illustrative fixture: validated shortage arithmetic; not a real grid solve",
        "stress": {
            "name": "Illustrative cold-weather stress",
            "demandMultiplier": 1.17,
            "generationAvailability": 0.79,
            "durationHours": DURATION_HOURS,
        },
        "limitations": [
            "Synthetic test fixture; it does not represent the Texas grid or an actual interconnection.",
            "This is an illustrative stress snapshot, not a Uri reconstruction or outage forecast.",
            "Candidate locations, capacities and branch loadings are fictional until D01-backed data is available.",
        ],
        "sources": [
            {"label": "Fixture", "detail": "Checked-in synthetic five-bus network"},
            {"label": "Method", "detail": "Fixed snapshot with finite generation and modeled load shedding"},
        ],
        "network": fixture,
        "scenarios": scenarios,
    }


def main() -> None:
    started = perf_counter()
    payload = result_payload()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    elapsed = perf_counter() - started
    if elapsed > 1:
        raise RuntimeError(f"Fixture generation exceeded fallback budget: {elapsed:.2f}s")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} in {elapsed * 1000:.0f} ms")


if __name__ == "__main__":
    main()

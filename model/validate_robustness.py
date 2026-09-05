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
from numbers import Real
from pathlib import Path

from model.generate_demo import artifact_hash, load_inputs, result_payload

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "demo" / "synthetic-cross-scenario-validation-v1.json"
TIMINGS_OUTPUT = ROOT / "data" / "demo" / "synthetic-cross-scenario-timings.local.json"
SENSITIVITY_GRID = (
    (0.95, 0.90),
    (0.95, 1.00),
    (0.95, 1.10),
    (1.00, 0.90),
    (1.00, 1.00),
    (1.00, 1.10),
    (1.05, 0.90),
    (1.05, 1.00),
    (1.05, 1.10),
)
UNSEEN_PERTURBATION = {"demandScale": 1.08, "generationAvailabilityScale": 0.94}
NETWORK_COPIES = (1, 5, 10, 20)
CANDIDATE_IDS = ("a", "b")
METRIC_UNITS = {
    "demandMw": "MW",
    "unservedMw": "MW",
    "unservedMwhOverHorizon": "MWh",
    "horizonHours": "h",
    "fractionDemandUnserved": "fraction",
    "improvementMw": "MW",
}

# Fields the grid actually scales, and the fixture fields it deliberately does
# not touch because ``generate_demo.py`` never reads them (see PR #106 review).
DRIVEN_FIELDS = (
    "assumptions.demandMw",
    "assumptions.baselineAvailableGenerationMw",
    "interventions[].modeledContributionMw",
)
NOT_CONSUMED_FIELDS = (
    "assumptions.demandMultiplier",
    "assumptions.generationAvailabilityFraction",
)
STRUCTURAL_NOTE = (
    "Structural guarantee, not evidence: the fixture computes shed = max(0, demandMw - "
    "(baselineAvailableGenerationMw + modeledContributionMw)) and this grid scales both "
    "candidates' modeledContributionMw by the same availability factor, so the candidate "
    "with the larger modeledContributionMw is never worse in any cell for any positive "
    "scale. An empty rankReversals list is therefore expected by construction; the grid can "
    "only produce ties (both candidates at zero unserved MW), never a reversal."
)


class ValidationInputInvalid(ValueError):
    """Raised when the fixture cannot be validated; names the field and reason."""

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


def _require_number(container: dict, field: str, label: str, *, positive: bool) -> None:
    if field not in container:
        raise ValidationInputInvalid(label, "missing")
    value = container[field]
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValidationInputInvalid(
            label, f"must be a number, got {type(value).__name__}"
        )
    if positive and value <= 0:
        raise ValidationInputInvalid(label, f"must be > 0, got {value}")
    if not positive and value < 0:
        raise ValidationInputInvalid(label, f"must be >= 0, got {value}")


def validate_inputs(inputs: dict) -> dict:
    """Reject fixtures this validator cannot honestly report on.

    Returns ``inputs`` unchanged so callers can chain it.  No defaults are
    substituted: a missing or non-physical value is an explicit failure.
    """
    if not isinstance(inputs, dict):
        raise ValidationInputInvalid("inputs", "must be an object")
    for key in ("artifactId", "assumptions", "interventions"):
        if key not in inputs:
            raise ValidationInputInvalid(key, "missing")
    assumptions = inputs["assumptions"]
    if not isinstance(assumptions, dict):
        raise ValidationInputInvalid("assumptions", "must be an object")
    _require_number(assumptions, "demandMw", "assumptions.demandMw", positive=True)
    _require_number(
        assumptions,
        "baselineAvailableGenerationMw",
        "assumptions.baselineAvailableGenerationMw",
        positive=False,
    )
    _require_number(
        assumptions, "durationHours", "assumptions.durationHours", positive=True
    )
    if "modelMode" not in assumptions:
        raise ValidationInputInvalid("assumptions.modelMode", "missing")

    interventions = inputs["interventions"]
    if not isinstance(interventions, list):
        raise ValidationInputInvalid("interventions", "must be a list")
    ids = [item.get("id") if isinstance(item, dict) else None for item in interventions]
    if sorted(str(i) for i in ids) != sorted(CANDIDATE_IDS):
        raise ValidationInputInvalid(
            "interventions",
            f"candidate ids must be exactly {list(CANDIDATE_IDS)}, got {ids}",
        )
    for item in interventions:
        _require_number(
            item,
            "modeledContributionMw",
            f"interventions[{item['id']}].modeledContributionMw",
            positive=False,
        )
    return inputs


def _perturbed_inputs(
    inputs: dict, demand_scale: float, generation_scale: float
) -> dict:
    """Return one synthetic perturbation without changing the source fixture.

    Only the fields in ``DRIVEN_FIELDS`` are scaled.  The availability axis
    scales the baseline generation *and* every candidate's contribution by the
    same factor.
    """
    changed = copy.deepcopy(inputs)
    assumptions = changed["assumptions"]
    assumptions["demandMw"] *= demand_scale
    assumptions["baselineAvailableGenerationMw"] *= generation_scale
    for intervention in changed["interventions"]:
        intervention["modeledContributionMw"] *= generation_scale
    return changed


def _metric_row(scenario: dict, duration_hours: float) -> dict:
    metrics = scenario["metrics"]
    return {
        "scenarioId": scenario["id"],
        "label": scenario["label"],
        "demandMw": round(metrics["demandMw"], 4),
        "unservedMw": round(metrics["shedMw"], 4),
        "unservedMwhOverHorizon": round(metrics["shedMwh"], 4),
        "horizonHours": round(duration_hours, 4),
        "fractionDemandUnserved": round(metrics["shedMw"] / metrics["demandMw"], 6),
        "improvementMw": round(metrics["improvementMw"], 4),
    }


def normalized_metrics(inputs: dict) -> list[dict]:
    """Report absolute MW/MWh and fraction-unserved for the base fixture."""
    validate_inputs(inputs)
    duration_hours = inputs["assumptions"]["durationHours"]
    return [
        _metric_row(item, duration_hours)
        for item in result_payload(inputs)["scenarios"].values()
    ]


def _a_vs_b(payload: dict) -> str:
    a_shed = payload["scenarios"]["a"]["metrics"]["shedMw"]
    b_shed = payload["scenarios"]["b"]["metrics"]["shedMw"]
    if a_shed < b_shed:
        return "a_better"
    if b_shed < a_shed:
        return "b_better"
    return "tie"


def detect_reversals(base_ranking: str, rows: list[dict]) -> list[dict]:
    """Cells whose A/B ranking differs from the base ranking; ties are not reversals."""
    return [
        {
            "demandScale": row["demandScale"],
            "generationAvailabilityScale": row["generationAvailabilityScale"],
        }
        for row in rows
        if row["aVsB"] not in {base_ranking, "tie"}
    ]


def sensitivity_analysis(inputs: dict) -> dict:
    """Evaluate a fixed demand/availability grid and report any A/B reversal.

    See ``STRUCTURAL_NOTE``: for this fixture model a reversal is impossible by
    construction, so the detector's live path is proven by tests that inject a
    per-cell reordering rather than by the checked-in fixture.
    """
    validate_inputs(inputs)
    base_ranking = _a_vs_b(result_payload(inputs))
    duration_hours = inputs["assumptions"]["durationHours"]
    rows = []
    for demand_scale, generation_scale in SENSITIVITY_GRID:
        payload = result_payload(
            _perturbed_inputs(inputs, demand_scale, generation_scale)
        )
        rows.append(
            {
                "demandScale": demand_scale,
                "generationAvailabilityScale": generation_scale,
                "aVsB": _a_vs_b(payload),
                "scenarios": [
                    _metric_row(payload["scenarios"][name], duration_hours)
                    for name in ("baseline", "a", "b")
                ],
            }
        )
    reversals = detect_reversals(base_ranking, rows)
    return {
        "axes": {
            "drivenFields": list(DRIVEN_FIELDS),
            "notConsumed": list(NOT_CONSUMED_FIELDS),
            "note": (
                "The grid scales the fields in drivenFields directly. The fixture's displayed "
                "demandMultiplier and generationAvailabilityFraction are not read by "
                "generate_demo.py and therefore do not enter any metric here."
            ),
        },
        "baseRanking": base_ranking,
        "grid": rows,
        "rankReversals": reversals,
        "tieCount": sum(row["aVsB"] == "tie" for row in rows),
        "structuralNote": STRUCTURAL_NOTE,
        "finding": (
            "No A/B rank reversal in this grid; expected by construction, see structuralNote."
            if not reversals
            else "A/B rank reversals found in this grid."
        ),
    }


def unseen_scenario(inputs: dict) -> dict:
    """Run an out-of-grid deterministic perturbation of the same fixture."""
    validate_inputs(inputs)
    duration_hours = inputs["assumptions"]["durationHours"]
    payload = result_payload(
        _perturbed_inputs(
            inputs,
            demand_scale=UNSEEN_PERTURBATION["demandScale"],
            generation_scale=UNSEEN_PERTURBATION["generationAvailabilityScale"],
        )
    )
    return {
        "id": "unseen_fixture_colder_shortfall_v1",
        "perturbation": UNSEEN_PERTURBATION,
        "aVsB": _a_vs_b(payload),
        "scenarios": [
            _metric_row(payload["scenarios"][name], duration_hours)
            for name in ("baseline", "a", "b")
        ],
        "scope": (
            "Unseen deterministic perturbation of the checked-in synthetic fixture; "
            "it is not a temporal or geographic holdout."
        ),
    }


def _scaled_inputs(inputs: dict, copies: int) -> dict:
    """Replicate only the fixture topology for an execution-cost comparison."""
    scaled = copy.deepcopy(inputs)
    buses, lines = [], []
    for copy_number in range(copies):
        prefix = f"copy-{copy_number}:"
        buses.extend(
            {**bus, "id": prefix + bus["id"]} for bus in inputs["network"]["buses"]
        )
        for line in inputs["network"]["lines"]:
            lines.append(
                {
                    **line,
                    "id": prefix + line["id"],
                    "from": prefix + line["from"],
                    "to": prefix + line["to"],
                }
            )
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
        measurements.append(
            {
                "fixtureCopies": copies,
                "busCount": len(scaled["network"]["buses"]),
                "lineCount": len(scaled["network"]["lines"]),
                "sampleCount": samples,
                "medianExecutionMs": round(statistics.median(elapsed_ms), 4),
                "minExecutionMs": round(min(elapsed_ms), 4),
            }
        )
    return measurements


RUNTIME_METHOD = "Same Python process, one warm-up per size, then perf_counter_ns around result_payload()."
RUNTIME_CAVEAT = (
    "This measures fixture materialization only. It does not run or estimate a power-flow, "
    "OPF, cascade, or real network solver."
)


def timings_report(inputs: dict, runtime_samples: int = 31) -> dict:
    """Machine-specific wall-clock timings; written separately and never committed."""
    validate_inputs(inputs)
    return {
        "schemaVersion": 1,
        "artifactId": "flux:synthetic-cross-scenario-timings:local",
        "inputArtifactId": inputs["artifactId"],
        "inputHash": artifact_hash(inputs),
        "machine": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "processor": platform.processor() or "unreported",
        },
        "method": RUNTIME_METHOD,
        "caveat": RUNTIME_CAVEAT,
        "measurements": runtime_scaling(inputs, runtime_samples),
    }


def validation_report(inputs: dict) -> dict:
    """Build the traceable, fully deterministic report.

    Wall-clock timings and machine identity are deliberately excluded so the
    committed artifact regenerates byte-for-byte on any machine; see
    ``timings_report`` and the ``--timings`` flag for the local measurement.
    """
    validate_inputs(inputs)
    return {
        "schemaVersion": 1,
        "artifactId": "flux:synthetic-cross-scenario-validation:v1",
        "inputArtifactId": inputs["artifactId"],
        "inputHash": artifact_hash(inputs),
        "modelMode": inputs["assumptions"]["modelMode"],
        "units": METRIC_UNITS,
        "baseMetrics": normalized_metrics(inputs),
        "sensitivity": sensitivity_analysis(inputs),
        "unseenScenario": unseen_scenario(inputs),
        "runtimeScaling": {
            "committed": False,
            "method": RUNTIME_METHOD,
            "caveat": RUNTIME_CAVEAT,
            "timingsArtifact": (
                "Not committed: machine identity and wall-clock medians are written to "
                f"{TIMINGS_OUTPUT.relative_to(ROOT).as_posix()} by "
                "`python -m model.validate_robustness --timings` and are git-ignored."
            ),
        },
        "transferBoundary": {
            "temporal": (
                "Not evaluated: the fixture is a four-hour static balance, "
                "not a time-indexed holdout."
            ),
            "geographic": (
                "Not evaluated: the fixture is explicitly not Minnesota, New York, Texas, "
                "ERCOT, MISO, or an actual interconnection model."
            ),
            "computational": (
                "Measured only as in-process fixture materialization across replicated "
                "five-bus shapes; no solver scale claim. Timings are not part of this artifact."
            ),
            "ranking": STRUCTURAL_NOTE,
            "assumptionsNotConsumed": (
                "The fixture's displayed demandMultiplier and generationAvailabilityFraction "
                "are not consumed by the model, so this grid says nothing about them."
            ),
            "futureFeasible": (
                "A Minnesota or New York case remains future/feasible-only until an actual "
                "verified case and execution are completed."
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    unknown = [arg for arg in args if arg != "--timings"]
    if unknown:
        print(
            f"unknown argument(s): {unknown}; only --timings is accepted",
            file=sys.stderr,
        )
        return 2
    try:
        inputs = validate_inputs(load_inputs())
    except ValidationInputInvalid as error:
        print(
            f"validation input invalid: {error.field}: {error.reason}", file=sys.stderr
        )
        return 2
    report = validation_report(inputs)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    if "--timings" in args:
        TIMINGS_OUTPUT.write_text(
            json.dumps(timings_report(inputs), indent=2) + "\n", encoding="utf-8"
        )
        print(f"Wrote {TIMINGS_OUTPUT.relative_to(ROOT)} (local, not committed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

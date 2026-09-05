from __future__ import annotations

from model.generate_demo import load_inputs
from model.validate_robustness import (
    NETWORK_COPIES,
    SENSITIVITY_GRID,
    normalized_metrics,
    runtime_scaling,
    sensitivity_analysis,
    unseen_scenario,
    validation_report,
)


def test_base_metrics_keep_absolute_and_normalized_units() -> None:
    metrics = {row["scenarioId"]: row for row in normalized_metrics(load_inputs())}

    assert metrics["baseline"] == {
        "scenarioId": "baseline", "label": "Baseline", "demandMw": 1365,
        "unservedMw": 188, "unservedMwhOverHorizon": 752, "horizonHours": 4,
        "fractionDemandUnserved": 188 / 1365, "improvementMw": 0,
    }
    assert metrics["a"]["unservedMwhOverHorizon"] == metrics["a"]["unservedMw"] * 4
    assert metrics["b"]["fractionDemandUnserved"] == 82 / 1365


def test_sensitivity_reports_no_reversal_and_low_shortage_ties() -> None:
    sensitivity = sensitivity_analysis(load_inputs())

    assert len(sensitivity["grid"]) == len(SENSITIVITY_GRID)
    assert sensitivity["baseRanking"] == "a_better"
    assert sensitivity["rankReversals"] == []
    assert sensitivity["tieCount"] == 2
    assert sensitivity["finding"] == "No A/B rank reversal in this grid."


def test_unseen_fixture_perturbation_is_not_mislabeled_as_transfer() -> None:
    report = unseen_scenario(load_inputs())

    assert report["id"] == "unseen_fixture_colder_shortfall_v1"
    assert report["aVsB"] == "a_better"
    assert report["scenarios"][0]["unservedMw"] > 0
    assert "not a temporal or geographic holdout" in report["scope"]


def test_runtime_scaling_uses_replicated_shapes_and_same_process_samples() -> None:
    measurements = runtime_scaling(load_inputs(), samples=2)

    assert [row["fixtureCopies"] for row in measurements] == list(NETWORK_COPIES)
    assert [row["busCount"] for row in measurements] == [5 * copies for copies in NETWORK_COPIES]
    assert [row["lineCount"] for row in measurements] == [6 * copies for copies in NETWORK_COPIES]
    assert all(row["sampleCount"] == 2 and row["minExecutionMs"] >= 0 for row in measurements)


def test_report_keeps_fixture_and_transfer_limits_explicit() -> None:
    report = validation_report(load_inputs(), runtime_samples=2)

    assert report["inputArtifactId"] == "flux:synthetic-scenario-input:v1"
    assert report["modelMode"] == "synthetic_power_balance_preview"
    assert "does not run or estimate" in report["runtimeScaling"]["caveat"]
    assert "Not evaluated" in report["transferBoundary"]["temporal"]
    assert "future/feasible-only" in report["transferBoundary"]["futureFeasible"]

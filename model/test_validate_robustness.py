from __future__ import annotations

import copy
import json

import pytest

from model import validate_robustness
from model.generate_demo import load_inputs
from model.validate_robustness import (
    DRIVEN_FIELDS,
    NETWORK_COPIES,
    NOT_CONSUMED_FIELDS,
    OUTPUT,
    SENSITIVITY_GRID,
    ValidationInputInvalid,
    _perturbed_inputs,
    detect_reversals,
    normalized_metrics,
    runtime_scaling,
    sensitivity_analysis,
    timings_report,
    unseen_scenario,
    validate_inputs,
    validation_report,
)


def _swapped_contributions(inputs: dict) -> dict:
    swapped = copy.deepcopy(inputs)
    by_id = {item["id"]: item for item in swapped["interventions"]}
    by_id["a"]["modeledContributionMw"], by_id["b"]["modeledContributionMw"] = (
        by_id["b"]["modeledContributionMw"],
        by_id["a"]["modeledContributionMw"],
    )
    return swapped


def test_base_metrics_keep_absolute_and_normalized_units() -> None:
    metrics = {row["scenarioId"]: row for row in normalized_metrics(load_inputs())}

    assert metrics["baseline"] == {
        "scenarioId": "baseline",
        "label": "Baseline",
        "demandMw": 1365,
        "unservedMw": 188,
        "unservedMwhOverHorizon": 752,
        "horizonHours": 4,
        "fractionDemandUnserved": 188 / 1365,
        "improvementMw": 0,
    }
    assert metrics["a"]["unservedMwhOverHorizon"] == metrics["a"]["unservedMw"] * 4
    assert metrics["b"]["fractionDemandUnserved"] == 82 / 1365


def test_horizon_follows_fixture_duration() -> None:
    inputs = load_inputs()
    inputs["assumptions"]["durationHours"] = 3

    metrics = {row["scenarioId"]: row for row in normalized_metrics(inputs)}

    assert metrics["baseline"]["horizonHours"] == 3
    for row in metrics.values():
        assert row["unservedMwhOverHorizon"] == row["unservedMw"] * 3


def test_sensitivity_reports_no_reversal_and_low_shortage_ties() -> None:
    sensitivity = sensitivity_analysis(load_inputs())

    assert len(sensitivity["grid"]) == len(SENSITIVITY_GRID)
    assert sensitivity["baseRanking"] == "a_better"
    assert sensitivity["rankReversals"] == []
    assert sensitivity["tieCount"] == 2
    assert sensitivity["finding"].startswith(
        "No A/B rank reversal in this grid; expected by construction"
    )


def test_sensitivity_discloses_structural_guarantee_and_driven_fields() -> None:
    sensitivity = sensitivity_analysis(load_inputs())

    assert "expected by construction" in sensitivity["structuralNote"]
    assert (
        "max(0, demandMw - (baselineAvailableGenerationMw + modeledContributionMw))"
        in (sensitivity["structuralNote"])
    )
    assert sensitivity["axes"]["drivenFields"] == list(DRIVEN_FIELDS)
    assert sensitivity["axes"]["notConsumed"] == list(NOT_CONSUMED_FIELDS)
    assert "assumptions.demandMultiplier" in sensitivity["axes"]["notConsumed"]
    assert (
        "assumptions.generationAvailabilityFraction"
        in sensitivity["axes"]["notConsumed"]
    )


def test_swapping_contributions_flips_every_cell_but_is_not_a_reversal() -> None:
    """Confirms the structural note: a swapped fixture flips the base ranking in
    every cell simultaneously, so the detector correctly reports zero reversals."""
    sensitivity = sensitivity_analysis(_swapped_contributions(load_inputs()))

    assert sensitivity["baseRanking"] == "b_better"
    assert {row["aVsB"] for row in sensitivity["grid"]} == {"b_better", "tie"}
    assert sensitivity["rankReversals"] == []


def test_detector_reports_reversal_when_a_cell_reorders_candidates(monkeypatch) -> None:
    """Reversal-positive path: swap the contributions only in the reduced-availability
    cells so the grid genuinely reorders A and B relative to the base ranking."""
    original = validate_robustness._perturbed_inputs

    def reorder_low_availability(
        inputs: dict, demand_scale: float, generation_scale: float
    ):
        source = _swapped_contributions(inputs) if generation_scale < 1 else inputs
        return original(source, demand_scale, generation_scale)

    monkeypatch.setattr(
        validate_robustness, "_perturbed_inputs", reorder_low_availability
    )

    sensitivity = sensitivity_analysis(load_inputs())

    assert sensitivity["baseRanking"] == "a_better"
    assert sensitivity["rankReversals"] == [
        {"demandScale": 0.95, "generationAvailabilityScale": 0.90},
        {"demandScale": 1.00, "generationAvailabilityScale": 0.90},
        {"demandScale": 1.05, "generationAvailabilityScale": 0.90},
    ]
    assert sensitivity["finding"] == "A/B rank reversals found in this grid."


def test_detect_reversals_ignores_ties_and_flags_opposite_ranking() -> None:
    rows = [
        {"demandScale": 1.0, "generationAvailabilityScale": 1.0, "aVsB": "a_better"},
        {"demandScale": 1.0, "generationAvailabilityScale": 1.1, "aVsB": "tie"},
        {"demandScale": 1.05, "generationAvailabilityScale": 0.9, "aVsB": "b_better"},
    ]

    assert detect_reversals("a_better", rows) == [
        {"demandScale": 1.05, "generationAvailabilityScale": 0.9}
    ]
    assert detect_reversals("b_better", rows) == [
        {"demandScale": 1.0, "generationAvailabilityScale": 1.0}
    ]


def test_availability_axis_scales_baseline_and_candidate_contribution() -> None:
    inputs = load_inputs()

    perturbed = _perturbed_inputs(inputs, demand_scale=1.0, generation_scale=0.5)

    assert perturbed["assumptions"]["demandMw"] == inputs["assumptions"]["demandMw"]
    assert perturbed["assumptions"]["baselineAvailableGenerationMw"] == pytest.approx(
        inputs["assumptions"]["baselineAvailableGenerationMw"] * 0.5
    )
    for before, after in zip(
        inputs["interventions"], perturbed["interventions"], strict=True
    ):
        assert after["modeledContributionMw"] == pytest.approx(
            before["modeledContributionMw"] * 0.5
        )
    # The displayed fixture multipliers are not an axis; they are left untouched.
    for field in ("demandMultiplier", "generationAvailabilityFraction"):
        assert perturbed["assumptions"][field] == inputs["assumptions"][field]
    assert inputs == load_inputs(), "the source fixture must not be mutated"


def test_unseen_fixture_perturbation_is_not_mislabeled_as_transfer() -> None:
    report = unseen_scenario(load_inputs())

    assert report["id"] == "unseen_fixture_colder_shortfall_v1"
    assert report["aVsB"] == "a_better"
    assert report["scenarios"][0]["unservedMw"] > 0
    assert "not a temporal or geographic holdout" in report["scope"]


def test_unseen_perturbation_differs_from_base_fixture() -> None:
    inputs = load_inputs()
    report = unseen_scenario(inputs)
    base = {row["scenarioId"]: row for row in normalized_metrics(inputs)}
    unseen = {row["scenarioId"]: row for row in report["scenarios"]}

    assert unseen["baseline"]["demandMw"] == pytest.approx(1365 * 1.08)
    assert unseen["baseline"]["demandMw"] != base["baseline"]["demandMw"]
    assert unseen["baseline"]["unservedMw"] > base["baseline"]["unservedMw"]


def test_runtime_scaling_uses_replicated_shapes_and_same_process_samples() -> None:
    measurements = runtime_scaling(load_inputs(), samples=2)

    assert [row["fixtureCopies"] for row in measurements] == list(NETWORK_COPIES)
    assert [row["busCount"] for row in measurements] == [
        5 * copies for copies in NETWORK_COPIES
    ]
    assert [row["lineCount"] for row in measurements] == [
        6 * copies for copies in NETWORK_COPIES
    ]
    assert all(
        row["sampleCount"] == 2 and row["minExecutionMs"] >= 0 for row in measurements
    )


def test_committed_report_excludes_machine_and_timings() -> None:
    report = validation_report(load_inputs())
    serialized = json.dumps(report)

    assert report["runtimeScaling"]["committed"] is False
    assert "machine" not in report["runtimeScaling"]
    assert "measurements" not in report["runtimeScaling"]
    assert "medianExecutionMs" not in serialized
    assert validation_report(load_inputs()) == report, "report must be deterministic"


def test_timings_report_is_separate_and_carries_machine_identity() -> None:
    timings = timings_report(load_inputs(), runtime_samples=2)

    assert timings["artifactId"] == "flux:synthetic-cross-scenario-timings:local"
    assert set(timings["machine"]) == {"platform", "python", "processor"}
    assert [row["fixtureCopies"] for row in timings["measurements"]] == list(
        NETWORK_COPIES
    )
    assert "does not run or estimate" in timings["caveat"]


def test_committed_report_matches_code() -> None:
    """The checked-in artifact must be exactly what the code regenerates."""
    expected = json.dumps(validation_report(load_inputs()), indent=2) + "\n"

    assert OUTPUT.read_text(encoding="utf-8") == expected


def test_report_keeps_fixture_and_transfer_limits_explicit() -> None:
    report = validation_report(load_inputs())

    assert report["inputArtifactId"] == "flux:synthetic-scenario-input:v1"
    assert report["modelMode"] == "synthetic_power_balance_preview"
    assert "does not run or estimate" in report["runtimeScaling"]["caveat"]
    assert "Not evaluated" in report["transferBoundary"]["temporal"]
    assert "future/feasible-only" in report["transferBoundary"]["futureFeasible"]
    assert "expected by construction" in report["transferBoundary"]["ranking"]
    assert "demandMultiplier" in report["transferBoundary"]["assumptionsNotConsumed"]


@pytest.mark.parametrize(
    ("mutate", "field", "reason_fragment"),
    [
        (
            lambda i: i["assumptions"].__setitem__("demandMw", 0),
            "assumptions.demandMw",
            "> 0",
        ),
        (
            lambda i: i["assumptions"].__setitem__("demandMw", -100),
            "assumptions.demandMw",
            "> 0",
        ),
        (
            lambda i: i["assumptions"].__setitem__("baselineAvailableGenerationMw", -1),
            "assumptions.baselineAvailableGenerationMw",
            ">= 0",
        ),
        (
            lambda i: i["assumptions"].__setitem__("durationHours", 0),
            "assumptions.durationHours",
            "> 0",
        ),
        (
            lambda i: i["assumptions"].__setitem__("demandMw", "1365"),
            "assumptions.demandMw",
            "must be a number",
        ),
        (lambda i: i["assumptions"].pop("demandMw"), "assumptions.demandMw", "missing"),
        (
            lambda i: i["interventions"].pop(),
            "interventions",
            "candidate ids must be exactly",
        ),
        (lambda i: i.pop("interventions"), "interventions", "missing"),
        (
            lambda i: i["interventions"][0].__setitem__("modeledContributionMw", -5),
            "interventions[a].modeledContributionMw",
            ">= 0",
        ),
    ],
)
def test_invalid_inputs_raise_named_reason(mutate, field, reason_fragment) -> None:
    inputs = load_inputs()
    mutate(inputs)

    with pytest.raises(ValidationInputInvalid) as caught:
        validate_inputs(inputs)
    assert caught.value.field == field
    assert reason_fragment in caught.value.reason

    for entry in (
        normalized_metrics,
        sensitivity_analysis,
        unseen_scenario,
        validation_report,
    ):
        with pytest.raises(ValidationInputInvalid):
            entry(inputs)


def test_main_exits_nonzero_with_named_reason_on_invalid_fixture(
    monkeypatch, capsys, tmp_path
) -> None:
    broken = load_inputs()
    broken["assumptions"]["demandMw"] = 0
    monkeypatch.setattr(validate_robustness, "load_inputs", lambda: broken)
    monkeypatch.setattr(validate_robustness, "OUTPUT", tmp_path / "report.json")

    exit_code = validate_robustness.main([])

    assert exit_code == 2
    assert "validation input invalid: assumptions.demandMw: must be > 0, got 0" in (
        capsys.readouterr().err
    )
    assert not (tmp_path / "report.json").exists()


def test_main_writes_timings_only_with_flag(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(validate_robustness, "OUTPUT", tmp_path / "report.json")
    monkeypatch.setattr(
        validate_robustness, "TIMINGS_OUTPUT", tmp_path / "timings.json"
    )
    monkeypatch.setattr(validate_robustness, "ROOT", tmp_path)

    assert validate_robustness.main([]) == 0
    assert (tmp_path / "report.json").exists()
    assert not (tmp_path / "timings.json").exists()

    assert validate_robustness.main(["--timings"]) == 0
    timings = json.loads((tmp_path / "timings.json").read_text(encoding="utf-8"))
    assert "machine" in timings
    assert (
        "machine"
        not in json.loads((tmp_path / "report.json").read_text())["runtimeScaling"]
    )

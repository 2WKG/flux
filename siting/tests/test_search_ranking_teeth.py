"""Probes that hold the siting ranking, its bounds, and its labels to account.

Every test here was verified by making the mutation it names, watching it go
red, and restoring.  On a ranked surface the order *is* the recommendation, so
an unasserted sort is a real defect, not a coverage gap.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from siting.search import (
    MAX_FULL_WINDOW_COUNTERFACTUALS,
    MODEL_MODE,
    MODEL_MODES,
    PROHIBITED_DISPLAY_TOKEN,
    REGULATORY_LABEL,
    SCREENING_LABEL,
    SITING_SEARCH_RESULT_KIND,
    SITING_SEARCH_SCHEMA_VERSION,
    SYNTHETIC_TOPOLOGY_LABEL,
    SearchAdapters,
    build_search_response,
    search_locations,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SITING_PANEL = REPO_ROOT / "web" / "src" / "interactive" / "SitingPanel.tsx"


@dataclass
class FakeNet:
    site_candidates: list[dict[str, object]]
    consumer_candidates: list[dict[str, object]]


def _producer_net(candidate_ids: list[str]) -> FakeNet:
    return FakeNet(
        site_candidates=[
            {"candidate_id": name, "bus_id": f"bus-{name}"} for name in candidate_ids
        ],
        consumer_candidates=[],
    )


def _adapters(
    *,
    peak_lost_load: dict[str, float],
    full_lost_load: dict[str, float] | None = None,
    calls: list[tuple[str, int | None]] | None = None,
) -> SearchAdapters:
    """A cascade double whose peak-hour and full-window orders can differ."""

    full = full_lost_load if full_lost_load is not None else peak_lost_load

    def cascade(**kwargs):
        hour = kwargs["hour"]
        candidate = next(
            (
                edit["element_id"].rsplit(":", 1)[-1]
                for edit in kwargs["edits"]
                if edit["kind"] in {"add_gen", "add_load"}
            ),
            "base",
        )
        if calls is not None:
            calls.append((candidate, hour))
        table = peak_lost_load if hour is not None else full
        lost = 100.0 if candidate == "base" else table[candidate]
        return {"lost_load_mwh": lost, "congestion_mwh": 100.0}

    return SearchAdapters(
        feasibility=lambda **kwargs: {"feasible": True},
        redundancy=lambda **kwargs: {"score": 0.0},
        cascade=cascade,
        edit_factory=lambda **kwargs: {
            key: value for key, value in kwargs.items() if value is not None
        },
    )


def _ranked(net: FakeNet, adapters: SearchAdapters, *, n: int = 5) -> list[str]:
    return [
        result["candidate_id"]
        for result in search_locations(
            net, kind="producer", unit_mw=100, scenario_id="s", n=n, adapters=adapters
        )
    ]


# --------------------------------------------------------------------------
# The two sorts
# --------------------------------------------------------------------------


def test_preliminary_sort_selects_the_finalist_set_not_insertion_order() -> None:
    """RED when ``preliminary.sort(key=_rank_key)`` is commented out.

    Seven candidates are declared in an order that is the exact reverse of
    their peak-hour strength, and only five may reach the full window.  Without
    the preliminary sort the first five declared win the bounded slots, so the
    two strongest candidates never appear.
    """

    names = [f"site-{index}" for index in range(7)]
    # site-6 is strongest (lowest lost load), site-0 weakest, declared 0..6.
    peak = {name: 90.0 - float(name.rsplit("-", 1)[-1]) for name in names}
    results = _ranked(_producer_net(names), _adapters(peak_lost_load=peak), n=5)

    assert results == ["site-6", "site-5", "site-4", "site-3", "site-2"]
    assert "site-0" not in results
    assert "site-1" not in results


def test_final_sort_reorders_when_the_full_window_disagrees_with_peak() -> None:
    """RED when ``finalists.sort(key=_rank_key)`` is commented out.

    The full-window counterfactual reverses the peak-hour strength order, so
    the emitted order can only be right if the finalists are re-sorted after
    the full-window components are assigned.
    """

    names = ["alpha", "bravo", "charlie"]
    peak = {"alpha": 10.0, "bravo": 50.0, "charlie": 90.0}
    full = {"alpha": 90.0, "bravo": 50.0, "charlie": 10.0}
    results = _ranked(
        _producer_net(names),
        _adapters(peak_lost_load=peak, full_lost_load=full),
        n=3,
    )

    assert results == ["charlie", "bravo", "alpha"]
    assert [result for result in results] != ["alpha", "bravo", "charlie"]


def test_ranking_is_deterministic_under_input_reordering() -> None:
    names = ["alpha", "bravo", "charlie", "delta"]
    peak = {"alpha": 10.0, "bravo": 30.0, "charlie": 50.0, "delta": 70.0}

    forward = _ranked(_producer_net(names), _adapters(peak_lost_load=peak), n=4)
    reverse = _ranked(
        _producer_net(list(reversed(names))), _adapters(peak_lost_load=peak), n=4
    )

    assert forward == reverse == ["alpha", "bravo", "charlie", "delta"]


def test_a_tie_scores_zero_and_breaks_alphabetically() -> None:
    """RED when ``_minmax`` returns anything but 0.0 on ``high == low``."""

    names = ["charlie", "alpha", "bravo"]
    peak = dict.fromkeys(names, 40.0)
    results = search_locations(
        _producer_net(names),
        kind="producer",
        unit_mw=100,
        scenario_id="s",
        n=3,
        adapters=_adapters(peak_lost_load=peak),
    )

    assert [result["candidate_id"] for result in results] == [
        "alpha",
        "bravo",
        "charlie",
    ]
    assert [result["objective"] for result in results] == [0.0, 0.0, 0.0]


# --------------------------------------------------------------------------
# The two bounds
# --------------------------------------------------------------------------


def test_full_window_replay_is_invoked_exactly_the_declared_number_of_times() -> None:
    """RED when ``MAX_FULL_WINDOW_COUNTERFACTUALS`` is widened.

    Counts adapter invocations rather than the returned slice: seven eligible
    candidates all pass the peak phase, so a widened bound replays all seven.
    """

    assert MAX_FULL_WINDOW_COUNTERFACTUALS == 5
    names = [f"site-{index}" for index in range(7)]
    peak = {name: 90.0 - float(name.rsplit("-", 1)[-1]) for name in names}
    calls: list[tuple[str, int | None]] = []
    _ranked(_producer_net(names), _adapters(peak_lost_load=peak, calls=calls), n=5)

    peak_calls = [name for name, hour in calls if hour is not None and name != "base"]
    full_window_calls = [
        name for name, hour in calls if hour is None and name != "base"
    ]

    assert len(peak_calls) == 7
    assert len(full_window_calls) == 5
    assert len(full_window_calls) == MAX_FULL_WINDOW_COUNTERFACTUALS


def test_request_n_above_the_declared_ceiling_is_refused() -> None:
    """RED when the ``n`` ceiling in ``_validate_request`` is widened."""

    net = _producer_net(["alpha"])
    adapters = _adapters(peak_lost_load={"alpha": 10.0})
    with pytest.raises(ValueError, match="n must be an integer from 1 to 5"):
        search_locations(
            net, kind="producer", unit_mw=100, scenario_id="s", n=6, adapters=adapters
        )
    with pytest.raises(ValueError):
        search_locations(
            net,
            kind="producer",
            unit_mw=100,
            scenario_id="s",
            n=MAX_FULL_WINDOW_COUNTERFACTUALS + 1,
            adapters=adapters,
        )


# --------------------------------------------------------------------------
# Truth labels
# --------------------------------------------------------------------------


def test_honesty_label_is_pinned_to_its_literal_wording() -> None:
    """RED when ``SCREENING_LABEL`` is rewritten.

    The literal is asserted here, not the constant, so rewriting the constant
    to a permitting claim cannot stay green.
    """

    assert (
        SCREENING_LABEL
        == "synthetic-topology screening; not a physical siting or permitability claim"
    )
    results = search_locations(
        _producer_net(["alpha"]),
        kind="producer",
        unit_mw=100,
        scenario_id="s",
        n=1,
        adapters=_adapters(peak_lost_load={"alpha": 10.0}),
    )
    assert results[0]["analysis_label"] == (
        "synthetic-topology screening; not a physical siting or permitability claim"
    )


def test_every_record_carries_the_synthetic_and_hypothetical_tokens() -> None:
    names = ["alpha", "bravo"]
    results = search_locations(
        _producer_net(names),
        kind="producer",
        unit_mw=100,
        scenario_id="s",
        n=2,
        adapters=_adapters(peak_lost_load={"alpha": 10.0, "bravo": 50.0}),
    )

    assert len(results) == 2
    for result in results:
        assert result["topology"] == "synthetic (ACTIVSg2000)"
        assert result["regulatory_label"] == "hypothetical"
        assert result["model_mode"] == "topology"
        assert result["model_mode"] in MODEL_MODES


def test_model_mode_is_a_closed_frozen_set() -> None:
    assert MODEL_MODES == frozenset({"topology", "aggregate", "not_applicable"})
    assert isinstance(MODEL_MODES, frozenset)
    assert MODEL_MODE in MODEL_MODES
    assert "synthetic" not in MODEL_MODES
    assert SYNTHETIC_TOPOLOGY_LABEL == "synthetic (ACTIVSg2000)"
    assert REGULATORY_LABEL == "hypothetical"


# --------------------------------------------------------------------------
# The panel contract, read from the component source
# --------------------------------------------------------------------------


def _panel_required_keys() -> dict[str, set[str]]:
    """Extract the keys ``isSitingSearchResponse`` requires from the component.

    Read from ``SitingPanel.tsx`` rather than restated, so a change on either
    side of the seam surfaces here instead of at runtime.
    """

    source = SITING_PANEL.read_text(encoding="utf-8")
    guard = source[
        source.index("function isSitingSearchResponse") : source.index(
            "export function buildSitingPresentation"
        )
    ]
    assert guard.strip(), "the SitingPanel type guard could not be located"
    return {
        "response": set(re.findall(r"\bresponse\.([A-Za-z]+)", guard)),
        "scenario": set(re.findall(r"\bscenario\.([A-Za-z]+)", guard)),
        "candidate": set(re.findall(r"\bcandidate\.([A-Za-z]+)", guard)),
        "provenance": set(
            re.findall(r'"(artifactId|artifactVersion|sourceKind)"', guard)
        ),
        "evidence": set(re.findall(r'"(label|value|provenanceRef)"', guard)),
        "schemaVersion": set(re.findall(r'schemaVersion !== "([^"]+)"', guard)),
        "resultKind": set(re.findall(r'resultKind !== "([^"]+)"', guard)),
    }


def _response() -> dict[str, object]:
    return build_search_response(
        _producer_net(["alpha", "bravo"]),
        kind="producer",
        unit_mw=100,
        scenario_id="synthetic-stress",
        scenario_label="Synthetic stress screening",
        n=2,
        adapters=_adapters(peak_lost_load={"alpha": 10.0, "bravo": 50.0}),
    )


def test_response_emits_every_key_the_panel_component_requires() -> None:
    required = _panel_required_keys()
    assert required["response"] >= {
        "schemaVersion",
        "resultKind",
        "scenario",
        "limitations",
        "candidates",
    }
    assert required["scenario"] == {"id", "label", "assumptions"}
    assert required["candidate"] >= {
        "id",
        "label",
        "limitations",
        "provenance",
        "evidence",
    }

    response = _response()
    for key in required["response"]:
        assert key in response, f"panel requires response.{key}"
    assert response["schemaVersion"] in required["schemaVersion"]
    assert response["resultKind"] in required["resultKind"]
    assert response["schemaVersion"] == SITING_SEARCH_SCHEMA_VERSION
    assert response["resultKind"] == SITING_SEARCH_RESULT_KIND

    scenario = response["scenario"]
    for key in required["scenario"]:
        assert key in scenario, f"panel requires scenario.{key}"
    assert isinstance(scenario["assumptions"], list) and scenario["assumptions"]
    assert all(
        isinstance(item, str) and item.strip() for item in scenario["assumptions"]
    )

    assert isinstance(response["limitations"], list) and response["limitations"]
    assert all(
        isinstance(item, str) and item.strip() for item in response["limitations"]
    )

    candidates = response["candidates"]
    assert len(candidates) == 2
    for candidate in candidates:
        for key in required["candidate"]:
            assert key in candidate, f"panel requires candidate.{key}"
        assert isinstance(candidate["id"], str) and candidate["id"]
        assert isinstance(candidate["label"], str) and candidate["label"]
        assert candidate["limitations"] and all(
            isinstance(item, str) and item.strip() for item in candidate["limitations"]
        )
        for key in required["provenance"]:
            value = candidate["provenance"][key]
            assert isinstance(value, str) and value, f"panel requires provenance.{key}"
        assert candidate["evidence"]
        for entry in candidate["evidence"]:
            for key in required["evidence"]:
                value = entry[key]
                assert isinstance(value, str) and value, (
                    f"panel requires evidence.{key}"
                )

    # The panel's guard runs on transported JSON, so the envelope must survive
    # a round trip unchanged.
    assert json.loads(json.dumps(response)) == response


def test_rendered_response_carries_the_truth_labels_and_never_the_removed_token() -> (
    None
):
    response = _response()
    rendered = json.dumps(response)

    assert SYNTHETIC_TOPOLOGY_LABEL in rendered
    assert "synthetic (ACTIVSg2000)" in rendered
    assert "hypothetical" in rendered
    assert SCREENING_LABEL in response["limitations"]
    assert PROHIBITED_DISPLAY_TOKEN == "illustrative"
    assert "illustrative" not in rendered.casefold()

    for candidate in response["candidates"]:
        assert "synthetic (ACTIVSg2000)" in candidate["label"]
        assert "hypothetical" in candidate["label"]
        assert candidate["provenance"]["sourceKind"] == "synthetic (ACTIVSg2000)"
        assert any(
            "synthetic (ACTIVSg2000)" in item for item in candidate["limitations"]
        )
        assert any("hypothetical" in item for item in candidate["limitations"])


# --------------------------------------------------------------------------
# Cross-candidate contamination
# --------------------------------------------------------------------------


def _consumer_net(candidate_ids: list[str]) -> FakeNet:
    return FakeNet(
        site_candidates=[],
        consumer_candidates=[
            {"candidate_id": name, "bus_id": f"load-bus-{name}"}
            for name in candidate_ids
        ],
    )


def _consumer_adapters(headroom: dict[str, float]) -> SearchAdapters:
    return SearchAdapters(
        feasibility=lambda **kwargs: {"feasible": True},
        balance=lambda **kwargs: {
            "p4_passed": True,
            "headroom_mw": headroom[kwargs["candidate"]["candidate_id"]],
        },
        # Redundancy is flat, so headroom is the only differentiator and the
        # preliminary cut depends entirely on reading each candidate's own
        # balance evidence.
        redundancy=lambda **kwargs: {"score": 10.0},
        cascade=lambda **kwargs: {"lost_load_mwh": 100.0, "congestion_mwh": 100.0},
        edit_factory=lambda **kwargs: {
            key: value for key, value in kwargs.items() if value is not None
        },
    )


def test_preliminary_consumer_scores_use_their_own_balance_evidence() -> None:
    """RED when ``_components`` is fed the leaked eligibility-loop ``balance``.

    Seven consumers compete for five bounded full-window slots and differ only
    in headroom.  If every preliminary candidate is scored with the *last*
    eligible candidate's headroom the headroom component ties for all seven,
    the cut degrades to an alphabetical tie-break, and the two largest-headroom
    candidates are dropped before the full window ever sees them.
    """

    names = [f"load-{index}" for index in range(7)]
    headroom = {name: 10.0 * float(name.rsplit("-", 1)[-1]) for name in names}
    results = [
        result["candidate_id"]
        for result in search_locations(
            _consumer_net(names),
            kind="consumer",
            unit_mw=100,
            scenario_id="s",
            n=5,
            adapters=_consumer_adapters(headroom),
        )
    ]

    assert results == ["load-6", "load-5", "load-4", "load-3", "load-2"]
    # The alphabetical cut the leak produces keeps the two weakest candidates.
    assert "load-0" not in results
    assert "load-1" not in results

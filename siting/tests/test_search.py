from __future__ import annotations

from dataclasses import dataclass

import pytest

from siting.search import (
    SCREENING_LABEL,
    SearchAdapters,
    SearchUnavailable,
    search_locations,
)


@dataclass
class FakeNet:
    site_candidates: list[dict[str, object]]
    consumer_candidates: list[dict[str, object]]


def _adapters(*, p4_by_candidate: dict[str, bool] | None = None) -> SearchAdapters:
    calls: list[tuple[str, str, int | None]] = []

    def feasibility(**kwargs):
        return {
            "feasible": kwargs["candidate"]["candidate_id"] != "unsafe",
            "flags": ["S1"],
        }

    def balance(**kwargs):
        candidate_id = kwargs["candidate"]["candidate_id"]
        return {
            "p4_passed": (p4_by_candidate or {}).get(candidate_id, True),
            "headroom_mw": {"load-a": 80.0, "load-b": 120.0, "bad-corridor": 999.0}.get(
                candidate_id, 50.0
            ),
        }

    def redundancy(**kwargs):
        candidate = kwargs["candidate"]
        if candidate is None:
            return {"score": 10.0}
        return {
            "score": {
                "small-headroom": 60.0,
                "large-headroom": 20.0,
                "load-a": 80.0,
                "load-b": 20.0,
            }.get(candidate["candidate_id"], 30.0)
        }

    def cascade(**kwargs):
        candidate_edits = kwargs["edits"]
        hour = kwargs["hour"]
        candidate = next(
            (
                edit["element_id"].rsplit(":", 1)[-1]
                for edit in candidate_edits
                if edit["kind"] in {"add_gen", "add_load"}
            ),
            "base",
        )
        calls.append((candidate, kwargs["scenario_id"], hour))
        by_candidate = {
            "base": (100.0, 100.0),
            "small-headroom": (20.0, 50.0),
            "large-headroom": (60.0, 80.0),
            "load-a": (100.0, 100.0),
            "load-b": (100.0, 100.0),
        }
        lost, congestion = by_candidate[candidate]
        return {"lost_load_mwh": lost, "congestion_mwh": congestion, "hour": hour}

    return SearchAdapters(
        feasibility=feasibility,
        balance=balance,
        redundancy=redundancy,
        cascade=cascade,
        edit_factory=lambda **kwargs: {
            key: value for key, value in kwargs.items() if value is not None
        },
    )


def _net() -> FakeNet:
    return FakeNet(
        site_candidates=[
            {
                "candidate_id": "small-headroom",
                "bus_id": "bus-1",
                "safety_flags": ["S1"],
            },
            {
                "candidate_id": "large-headroom",
                "bus_id": "bus-2",
                "safety_flags": ["S2"],
            },
            {"candidate_id": "unsafe", "bus_id": "bus-3"},
        ],
        consumer_candidates=[
            {"candidate_id": "load-a", "bus_id": "load-bus-a"},
            {"candidate_id": "load-b", "bus_id": "load-bus-b"},
            {"candidate_id": "bad-corridor", "bus_id": "load-bus-c"},
        ],
    )


def test_producer_objective_is_counterfactual_and_not_naive_headroom() -> None:
    results = search_locations(
        _net(),
        kind="producer",
        unit_mw=300,
        scenario_id="synthetic-stress",
        n=2,
        adapters=_adapters(),
    )

    assert [result["candidate_id"] for result in results] == [
        "small-headroom",
        "large-headroom",
    ]
    top = results[0]
    assert top["objective_components"]["lost_load_reduction_mwh"] == 80.0
    assert top["objective_components"]["mean_redundancy_uplift"] == 50.0
    assert top["edit_hash"]
    assert top["analysis_label"] == SCREENING_LABEL
    assert top["model_mode"] == "topology"
    assert top["topology"] == "synthetic (ACTIVSg2000)"
    assert top["regulatory_label"] == "hypothetical"
    assert top["safety_flags"] == ["S1"]


def test_consumer_rejects_p4_breach_even_with_largest_headroom() -> None:
    results = search_locations(
        _net(),
        kind="consumer",
        unit_mw=100,
        scenario_id="synthetic-stress",
        n=2,
        adapters=_adapters(p4_by_candidate={"bad-corridor": False}),
    )

    assert [result["candidate_id"] for result in results] == ["load-a", "load-b"]
    assert all(result["balance"]["p4_passed"] is True for result in results)


def test_consumer_requires_explicit_corridor_pass() -> None:
    adapters = _adapters()
    adapters = SearchAdapters(
        feasibility=adapters.feasibility,
        balance=lambda **kwargs: {"headroom_mw": 100.0},
        redundancy=adapters.redundancy,
        cascade=adapters.cascade,
        edit_factory=adapters.edit_factory,
    )
    assert (
        search_locations(
            _net(), kind="consumer", unit_mw=100, scenario_id="s", adapters=adapters
        )
        == []
    )


def test_missing_policy_fails_closed() -> None:
    with pytest.raises(SearchUnavailable, match="placement feasibility"):
        search_locations(_net(), kind="producer", unit_mw=100, scenario_id="s")


def test_full_window_work_is_bounded_to_five_candidates() -> None:
    net = _net()
    net.site_candidates = [
        {"candidate_id": f"site-{index}", "bus_id": f"bus-{index}"}
        for index in range(7)
    ]
    adapters = _adapters()
    # Make all seven candidates evaluable by replacing the fixed fixture cascade.
    adapters = SearchAdapters(
        feasibility=lambda **kwargs: {"feasible": True},
        balance=adapters.balance,
        redundancy=lambda **kwargs: {
            "score": 1.0
            if kwargs["candidate"] is None
            else float(kwargs["candidate"]["candidate_id"].split("-")[-1])
        },
        cascade=lambda **kwargs: {
            "lost_load_mwh": 100.0 if not kwargs["edits"] else 90.0,
            "congestion_mwh": 100.0,
        },
        edit_factory=adapters.edit_factory,
    )
    results = search_locations(
        net, kind="producer", unit_mw=100, scenario_id="s", n=5, adapters=adapters
    )
    assert len(results) == 5

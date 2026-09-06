from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from siting.redundancy import score_redundancy


def _toy_net() -> SimpleNamespace:
    """Two sources: one direct path and one two-edge alternative path."""
    return SimpleNamespace(
        branches=[
            {"id": "direct", "from_bus": "load", "to_bus": "source_a", "dptf": 90.0},
            {"id": "via_mid_1", "from_bus": "load", "to_bus": "mid", "dptf": 70.0},
            {"id": "via_mid_2", "from_bus": "mid", "to_bus": "source_b", "dptf": 60.0},
            {"id": "low_priority", "from_bus": "mid", "to_bus": "spur", "dptf": 1.0},
        ],
        sources=[{"bus": "source_a"}, {"bus": "source_b"}],
        synthetic_topology=True,
    )


def test_n_minus_one_retains_an_alternative_source_and_names_worst_contingency() -> (
    None
):
    result = score_redundancy(_toy_net(), "load")

    assert result["evidence"]["status"] == "available"
    assert result["synthetic_topology"] is True
    assert result["components"]["n_minus_one_survivability"] == 100.0
    assert result["components"]["edge_disjoint_paths"] == 2
    assert result["components"]["alternative_source_hops"] == 2
    assert result["worst_contingency"]["branch_id"] == "line:direct"
    assert result["worst_contingency"]["available_source_count"] == 1


def test_contingencies_are_bounded_by_highest_dptf_then_stable_branch_id() -> None:
    net = _toy_net()
    result = score_redundancy(net, "load", max_contingencies=2)

    assert result["evidence"]["contingencies_evaluated"] == 2
    assert result["worst_contingency"]["branch_id"] == "line:direct"
    assert result["worst_contingency"]["dptf"] == 90.0


def test_contingency_bound_never_exceeds_twenty() -> None:
    net = SimpleNamespace(
        branches=[
            {
                "id": str(index),
                "from_bus": "load",
                "to_bus": f"source_{index}",
                "dptf": index,
            }
            for index in range(25)
        ],
        sources=[{"bus": f"source_{index}"} for index in range(25)],
    )

    result = score_redundancy(net, "load", max_contingencies=999)

    assert result["evidence"]["max_contingencies"] == 20
    assert result["evidence"]["contingencies_evaluated"] == 20


def test_single_path_failure_is_reflected_in_n_minus_one_score() -> None:
    net = SimpleNamespace(
        branches=[{"id": "only_path", "from_bus": 1, "to_bus": 2, "dptf": 5.0}],
        sources=[{"bus": 2}],
    )

    result = score_redundancy(net, 1)

    assert result["components"]["n_minus_one_survivability"] == 0.0
    assert result["worst_contingency"]["source_reachable"] is False
    assert result["score"] < 30


def test_pandapower_style_tables_are_duck_typed_without_a_pandapower_runtime() -> None:
    net = SimpleNamespace(
        line=pd.DataFrame(
            [
                {"from_bus": 1, "to_bus": 2, "in_service": True},
                {"from_bus": 1, "to_bus": 3, "in_service": True},
                {"from_bus": 3, "to_bus": 2, "in_service": True},
            ],
            index=["direct", "first", "second"],
        ),
        ext_grid=pd.DataFrame([{"bus": 2, "in_service": True}]),
        gen=pd.DataFrame(columns=["bus", "in_service"]),
        sgen=pd.DataFrame(columns=["bus", "in_service"]),
    )

    result = score_redundancy(net, 1)

    assert result["components"]["edge_disjoint_paths"] == 2
    assert result["evidence"]["contingencies_evaluated"] == 3
    assert result["worst_contingency"]["branch_id"] == "line:direct"


def test_unavailable_topology_is_explicit_instead_of_a_plausible_score() -> None:
    result = score_redundancy(_toy_net(), "unknown")

    assert result["score"] == 0.0
    assert result["worst_contingency"] is None
    assert result["evidence"]["status"] == "unavailable"
    assert result["evidence"]["reason"] == "target_bus_not_in_active_topology"


def test_negative_bound_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        score_redundancy(_toy_net(), "load", max_contingencies=-1)


def test_flux_network_uses_immutable_outage_and_cascade_adapters(tmp_path) -> None:
    from twin.build import build_network

    path = tmp_path / "toy.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE buses(bus_id BIGINT, name TEXT, base_kv DOUBLE, lon DOUBLE, lat DOUBLE, county_fips TEXT)"
        )
        con.execute(
            "CREATE TABLE lines(line_id BIGINT, from_bus BIGINT, to_bus BIGINT, base_kv DOUBLE, r_pu DOUBLE, x_pu DOUBLE, rate_a_mw DOUBLE, length_km DOUBLE, is_transformer BOOLEAN)"
        )
        con.execute(
            "CREATE TABLE gens(gen_id BIGINT, bus_id BIGINT, fuel TEXT, pmax_mw DOUBLE)"
        )
        con.execute(
            "CREATE TABLE loads(load_id BIGINT, bus_id BIGINT, p_mw_nominal DOUBLE)"
        )
        con.execute(
            "INSERT INTO buses VALUES (10, 'source', 110, -97, 30, '48001'), (20, 'consumer', 110, -97.1, 30.1, '48001')"
        )
        con.execute(
            "INSERT INTO lines VALUES (1, 10, 20, 110, 0.01, 0.1, 100, 1, false)"
        )
        con.execute("INSERT INTO gens VALUES (1, 10, 'gas', 100)")
        con.execute("INSERT INTO loads VALUES (1, 20, 10)")

    result = score_redundancy(build_network(path), 20)

    assert result["evidence"]["cascade"] == "per_contingency_in_memory"
    assert result["evidence"]["persistence"] == "not_persisted"
    assert result["components"]["n_minus_one_survivability"] == 0.0
    assert result["worst_contingency"]["branch_id"] == "line:1"
    assert result["worst_contingency"]["cascade_metrics"]["lost_load_mw"] == 10.0


def test_one_twin_contingency_solve_failure_keeps_topology_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from twin import cascade
    from twin.contracts import SimulationSolveError

    net = SimpleNamespace(
        branches=[
            {"id": "direct", "from_bus": "load", "to_bus": "source_a", "dptf": 90.0},
            {
                "id": "spur",
                "from_bus": "source_a",
                "to_bus": "spur_bus",
                "dptf": 80.0,
            },
        ],
        sources=[{"bus": "source_a"}],
        flux_element_lookup={},
        flux_bus_metadata={},
    )

    monkeypatch.setattr(
        cascade,
        "island_primitives",
        lambda _net, _edits: [],
    )

    calls: list[str] = []

    def run_cascade(_net, edits):
        calls.append(edits[0].element_id)
        if edits[0].element_id == "line:direct":
            raise SimulationSolveError("forced fixture solve failure")
        return {
            "lost_load_mw": 0.0,
            "served_load_mw": 10.0,
            "edit_hash": "successful-contingency",
        }

    monkeypatch.setattr(cascade, "run_cascade", run_cascade)

    result = score_redundancy(net, "load", max_contingencies=2)

    # One of two replays is unusable, so the aggregate is a mixed basis and the
    # evidence must say so rather than claim a full twin cascade.
    assert result["evidence"]["status"] == "available_with_partial_twin_cascade"
    assert result["evidence"]["cascade"] == "per_contingency_in_memory_partial"
    assert result["evidence"]["cascade_unavailable_contingencies"] == 1
    assert calls == ["line:direct", "line:spur"]
    assert result["worst_contingency"]["cascade_metrics"] == {
        "status": "unavailable",
        "reason": "simulation_solve_error",
    }
    assert result["worst_contingency"]["branch_id"] == "line:direct"


def _two_branch_twin_net() -> SimpleNamespace:
    return SimpleNamespace(
        branches=[
            {"id": "direct", "from_bus": "load", "to_bus": "source_a", "dptf": 90.0},
            {"id": "spur", "from_bus": "source_a", "to_bus": "spur_bus", "dptf": 80.0},
        ],
        sources=[{"bus": "source_a"}],
        # A non-None (if empty) element lookup is what selects the twin branch.
        flux_element_lookup={},
        flux_bus_metadata={},
    )


def test_every_twin_contingency_solve_failure_degrades_the_evidence_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from twin import cascade
    from twin.contracts import SimulationSolveError

    monkeypatch.setattr(cascade, "island_primitives", lambda _net, _edits: [])

    def run_cascade(_net, _edits):
        raise SimulationSolveError("forced fixture solve failure")

    monkeypatch.setattr(cascade, "run_cascade", run_cascade)

    result = score_redundancy(_two_branch_twin_net(), "load", max_contingencies=2)

    # Every contingency fell back to topology-only reachability, so the score
    # has no twin-cascade basis at all and the evidence must not claim one.
    assert result["evidence"]["contingencies_evaluated"] == 2
    assert result["evidence"]["cascade_unavailable_contingencies"] == 2
    assert result["evidence"]["status"] == "available_topology_only"
    assert result["evidence"]["cascade"] == "unavailable"
    assert result["evidence"]["status"] != "available_with_twin_cascade"
    assert result["evidence"]["cascade"] != "per_contingency_in_memory"


def test_a_non_solve_twin_failure_is_not_relabelled_a_solve_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The catch is deliberately narrow: broadening it to ``except Exception``
    # would report an unrelated bug as reason "simulation_solve_error".
    from twin import cascade

    monkeypatch.setattr(cascade, "island_primitives", lambda _net, _edits: [])

    def run_cascade(_net, _edits):
        raise ValueError("unrelated bug inside the twin call")

    monkeypatch.setattr(cascade, "run_cascade", run_cascade)

    with pytest.raises(ValueError, match="unrelated bug inside the twin call"):
        score_redundancy(_two_branch_twin_net(), "load", max_contingencies=2)

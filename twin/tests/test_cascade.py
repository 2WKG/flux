from __future__ import annotations

from pathlib import Path

import duckdb
import pandapower as pp
import pytest

from twin.build import build_network
from twin.cascade import (
    balance_report,
    feasibility_report,
    immutable_scenario_net,
    placement_counterfactual,
    rank_candidate_placements,
    redundancy_report,
    run_cascade,
    scenario_identity,
)
from twin.contracts import (
    SYNTHETIC_TOPOLOGY_LABEL,
    SimulationInputError,
    SimulationUnavailableError,
)


def _overloaded_impedance_net():
    net = pp.create_empty_network(sn_mva=100)
    buses = [pp.create_bus(net, 110) for _ in range(3)]
    pp.create_ext_grid(net, buses[0])
    pp.create_line_from_parameters(net, buses[0], buses[1], 1, 0.01, 0.1, 0, 1.0)
    pp.create_impedance(net, buses[1], buses[2], rft_pu=0.001, xft_pu=0.01, sn_mva=5)
    pp.create_load(net, buses[2], p_mw=10)
    return net


def _island_generator_net(generator_mw: float) -> object:
    net = pp.create_empty_network(sn_mva=100)
    first, second = pp.create_bus(net, 110), pp.create_bus(net, 110)
    pp.create_ext_grid(net, first)
    pp.create_line_from_parameters(net, first, second, 1, 0.01, 0.1, 0, 1.0)
    pp.create_load(net, second, p_mw=10)
    if generator_mw:
        pp.create_gen(
            net, second, p_mw=generator_mw, vm_pu=1, max_p_mw=generator_mw, min_p_mw=0
        )
    return net


def test_cascade_trips_impedance_and_sheds_its_island_without_mutating_input() -> None:
    net = _overloaded_impedance_net()
    result = run_cascade([], "storm", 0, net=net, max_stages=4)
    events = result["tripped_element_ids"]
    assert any(
        event["kind"] == "impedance" and event["cause"] == "overload"
        for event in events
    )
    assert result["lost_load_mw"] == pytest.approx(10.0)
    assert net.impedance.at[0, "in_service"]
    assert result["topology"] == SYNTHETIC_TOPOLOGY_LABEL


@pytest.mark.parametrize("generator_mw", [0, 5, 20])
def test_isolated_normal_generator_is_not_claimed_as_grid_forming_supply(
    generator_mw: float,
) -> None:
    result = run_cascade(
        ["line:1"], "storm", 0, net=_island_generator_net(generator_mw)
    )
    assert result["lost_load_mw"] == pytest.approx(10.0)
    assert any(event["cause"] == "island" for event in result["tripped_element_ids"])


def test_forced_load_outage_and_candidate_ranking_are_json_safe() -> None:
    net = _overloaded_impedance_net()
    result = run_cascade(["load:1"], "storm", 1, net=net)
    assert result["lost_load_mw"] == pytest.approx(10.0)
    assert result["tripped_element_ids"][0]["cause"] == "forced"
    placements = rank_candidate_placements(net, [0, 1], max_hops=2)
    assert placements[0]["topology"] == SYNTHETIC_TOPOLOGY_LABEL
    with pytest.raises(SimulationInputError, match="unknown"):
        run_cascade(["physical:1"], "storm", 1, net=net)


def test_county_impact_reports_synthetic_load_fraction_without_customer_claim(
    tmp_path,
) -> None:
    db = tmp_path / "grid.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE buses(bus_id BIGINT, county_fips TEXT)")
    con.execute("INSERT INTO buses VALUES (2, '48001')")
    con.close()
    result = run_cascade(
        ["load:1"], "storm", 1, net=_overloaded_impedance_net(), db_path=db
    )
    assert result["counties_dark"] == ["48001"]
    assert result["county_impacts"] == [
        {
            "county_fips": "48001",
            "lost_mw": 10.0,
            "customers_out": None,
            "fraction_dark": 1.0,
            "basis": "synthetic modeled load; customer count unavailable",
        }
    ]


def test_identity_and_immutable_edit_are_deterministic() -> None:
    net = _overloaded_impedance_net()
    first = scenario_identity(["line:1", "load:1"], "storm", 1, net=net)
    second = scenario_identity(["load:1", "1", "line:1"], "storm", 1, net=net)
    assert first == second
    assert (
        scenario_identity(["line:1", "load:1"], "storm", 1, net=net, max_stages=13)
        != first
    )
    edited = immutable_scenario_net(net, ["line:1"])
    assert net.line.at[0, "in_service"]
    assert not edited.line.at[0, "in_service"]
    with pytest.raises(RuntimeError, match="cancelled"):
        run_cascade([], "storm", 0, net=net, cancel_check=lambda: True)
    forward = run_cascade(["line:1", "load:1"], "storm", 1, net=net)
    reverse = run_cascade(["load:1", "1", "line:1"], "storm", 1, net=net)
    assert forward == reverse
    changed_case = _overloaded_impedance_net()
    changed_case["flux_case_path"] = __file__
    original = run_cascade(["line:1"], "storm", 1, net=net)
    changed = run_cascade(["line:1"], "storm", 1, net=changed_case)
    assert original["run_id"] != changed["run_id"]


def test_static_generator_source_identity_is_exact_and_slack_fails_closed() -> None:
    net = _overloaded_impedance_net()
    pp.create_sgen(net, 0, p_mw=1)
    net.gen["flux_element_id"] = []
    net.sgen["flux_element_id"] = ["generator:40"]
    net.ext_grid["flux_element_id"] = ["slack:379"]
    result = run_cascade(["generator:40"], "storm", 0, net=net)
    assert result["tripped_element_ids"][0] == {
        "element_id": "generator:40",
        "kind": "static_generator",
        "stage": 0,
        "cause": "forced",
    }
    assert net.sgen.at[0, "in_service"]
    with pytest.raises(SimulationInputError, match="grid-forming slack outages"):
        run_cascade(["slack:379"], "storm", 0, net=net)


def test_feasibility_balance_redundancy_and_measured_counterfactual() -> None:
    net = _overloaded_impedance_net()
    pp.create_gen(net, 0, p_mw=1, vm_pu=1, max_p_mw=20, min_p_mw=0)
    feasibility = feasibility_report(net)
    assert feasibility["dc_solve_converged"]
    balance = balance_report(net)
    assert balance["dc_balance_residual_mw"] == pytest.approx(0.0)
    redundancy = redundancy_report(net, [0, 2])
    assert redundancy[0]["topology"] == SYNTHETIC_TOPOLOGY_LABEL
    comparison = placement_counterfactual(
        [], "storm", 0, net=net, site_bus=0, unit_mw=1
    )
    assert set(comparison["measured_delta"]) == {
        "lost_load_reduction_mw",
        "tripped_event_reduction",
    }
    assert "not a physical siting" in comparison["limitations"][0]


def test_persistence_requires_real_schema_and_writes_copilot_shape(tmp_path) -> None:
    db = tmp_path / "grid.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE cascade_runs (run_id TEXT, scenario_id TEXT, hour INTEGER, "
        "tripped_element_ids_json JSON, lost_load_mw DOUBLE, counties_dark_json JSON, "
        "critical_loads_lost_json JSON, source_name TEXT, source_ref TEXT, source_version TEXT, "
        "source_retrieved_at TIMESTAMP, fixture_batch_id TEXT)"
    )
    con.close()
    run_cascade(
        ["load:1"], "storm", 2, net=_overloaded_impedance_net(), db_path=db, write=True
    )
    con = duckdb.connect(str(db), read_only=True)
    stored = con.execute(
        "SELECT lost_load_mw, source_name, source_ref FROM cascade_runs"
    ).fetchone()
    assert stored[0:2] == (10.0, "twin.cascade")
    assert "scenario_identity=v1:" in stored[2]
    con.close()
    with pytest.raises(SimulationUnavailableError, match="write=True"):
        run_cascade([], "storm", 0, net=_overloaded_impedance_net(), write=True)


@pytest.mark.skipif(
    not Path("data/raw/activsg2000_current/case_ACTIVSg2000.m").is_file(),
    reason="SKIPPED-ENV: current ACTIVSg2000 case is not installed in this checkout",
)
def test_real_activsg2000_import_solve_and_generator_line_outages() -> None:
    net = build_network("data/raw/activsg2000_current/case_ACTIVSg2000.m")
    result = run_cascade(
        ["line:1", "generator:1"], "uri_2021", 0, net=net, max_stages=4
    )
    kinds = {(event["kind"], event["cause"]) for event in result["tripped_element_ids"]}
    assert ("line", "forced") in kinds
    assert ("generator", "forced") in kinds
    assert result["solver"] == "pandapower.rundcpp"

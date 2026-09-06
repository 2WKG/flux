from __future__ import annotations

from pathlib import Path

import duckdb
import pandapower as pp
import pytest

from twin.build import build_network
from twin.cascade import rank_candidate_placements, run_cascade
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


def test_cascade_trips_impedance_and_sheds_its_island_without_mutating_input() -> None:
    net = _overloaded_impedance_net()
    result = run_cascade([], "storm", 0, net=net, max_stages=4)
    events = result["tripped_element_ids"]
    assert any(event["kind"] == "impedance" and event["cause"] == "overload" for event in events)
    assert result["lost_load_mw"] == pytest.approx(10.0)
    assert net.impedance.at[0, "in_service"]
    assert result["topology"] == SYNTHETIC_TOPOLOGY_LABEL


def test_forced_load_outage_and_candidate_ranking_are_json_safe() -> None:
    net = _overloaded_impedance_net()
    result = run_cascade(["load:1"], "storm", 1, net=net)
    assert result["lost_load_mw"] == pytest.approx(10.0)
    assert result["tripped_element_ids"][0]["cause"] == "forced"
    placements = rank_candidate_placements(net, [0, 1], max_hops=2)
    assert placements[0]["topology"] == SYNTHETIC_TOPOLOGY_LABEL
    with pytest.raises(SimulationInputError, match="unknown"):
        run_cascade(["physical:1"], "storm", 1, net=net)


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
    run_cascade(["load:1"], "storm", 2, net=_overloaded_impedance_net(), db_path=db, write=True)
    con = duckdb.connect(str(db), read_only=True)
    assert con.execute("SELECT lost_load_mw, source_name FROM cascade_runs").fetchone() == (10.0, "twin.cascade")
    con.close()
    with pytest.raises(SimulationUnavailableError, match="write=True"):
        run_cascade([], "storm", 0, net=_overloaded_impedance_net(), write=True)


@pytest.mark.skipif(
    not Path("data/raw/activsg2000_current/case_ACTIVSg2000.m").is_file(),
    reason="SKIPPED-ENV: current ACTIVSg2000 case is not installed in this checkout",
)
def test_real_activsg2000_import_solve_and_generator_line_outages() -> None:
    net = build_network("data/raw/activsg2000_current/case_ACTIVSg2000.m")
    result = run_cascade(["line:1", "generator:1"], "uri_2021", 0, net=net, max_stages=4)
    kinds = {(event["kind"], event["cause"]) for event in result["tripped_element_ids"]}
    assert ("line", "forced") in kinds
    assert ("generator", "forced") in kinds
    assert result["solver"] == "pandapower.rundcpp"

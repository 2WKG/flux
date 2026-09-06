from __future__ import annotations

import duckdb
import pytest

from twin.build import build_network, network_summary
from twin.cascade import island_primitives, run_cascade
from twin.contracts import SimulationInputError, SimulationUnavailableError
from twin.edits import add_generator, add_line, add_load, apply_edits, edit_hash, outage


def _fixture_db(tmp_path):
    path = tmp_path / "grid.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE buses(bus_id BIGINT, name TEXT, base_kv DOUBLE, lon DOUBLE, lat DOUBLE, county_fips TEXT)")
        con.execute("CREATE TABLE lines(line_id BIGINT, from_bus BIGINT, to_bus BIGINT, base_kv DOUBLE, r_pu DOUBLE, x_pu DOUBLE, rate_a_mw DOUBLE, length_km DOUBLE, is_transformer BOOLEAN)")
        con.execute("CREATE TABLE gens(gen_id BIGINT, bus_id BIGINT, fuel TEXT, pmax_mw DOUBLE)")
        con.execute("CREATE TABLE synthetic_bus_electrical(bus_id BIGINT, bus_type INTEGER, pd_mw DOUBLE, qd_mvar DOUBLE, gs_mw DOUBLE, bs_mvar DOUBLE, vm_pu DOUBLE, va_deg DOUBLE, vmin_pu DOUBLE, vmax_pu DOUBLE)")
        con.execute("CREATE TABLE synthetic_branch_electrical(line_id BIGINT, b_pu DOUBLE, tap_ratio DOUBLE, shift_deg DOUBLE, status INTEGER)")
        con.execute("CREATE TABLE synthetic_generator_electrical(gen_id BIGINT, p_mw DOUBLE, q_mvar DOUBLE, qmax_mvar DOUBLE, qmin_mvar DOUBLE, pmin_mw DOUBLE, status INTEGER)")
        con.execute("CREATE TABLE loads(load_id BIGINT, bus_id BIGINT, p_mw_nominal DOUBLE)")
        con.execute("CREATE TABLE critical_loads(cl_id BIGINT, kind TEXT, name TEXT, bus_id BIGINT)")
        con.execute("INSERT INTO buses VALUES (10, 'slack', 110, -97, 30, '48001'), (20, 'load', 110, -97.1, 30.1, '48003'), (30, 'island', 220, -97.2, 30.2, '48003')")
        con.execute("INSERT INTO lines VALUES (1, 10, 20, 110, 0.01, 0.1, 100, 2, false), (2, 20, 30, 220, 0.01, 0.1, 30, 1, true)")
        con.execute("INSERT INTO gens VALUES (1, 10, 'ng', 100), (2, 20, 'solar', 20)")
        con.execute("INSERT INTO synthetic_bus_electrical VALUES (10, 3, 0, 0, 0, 0, 1, 0, .9, 1.1), (20, 2, 10, 0, 0, 0, 1, 0, .9, 1.1), (30, 1, 20, 0, 0, 0, 1, 0, .9, 1.1)")
        con.execute("INSERT INTO synthetic_branch_electrical VALUES (1, 0, 0, 0, 1), (2, 0, 0, 0, 1)")
        con.execute("INSERT INTO synthetic_generator_electrical VALUES (1, 10, 0, 10, -10, 0, 1), (2, 20, 0, 20, -20, 0, 1)")
        con.execute("INSERT INTO loads VALUES (1, 20, 10), (2, 30, 20)")
        con.execute("INSERT INTO critical_loads VALUES (7, 'hospital', 'fixture hospital', 30)")
    return path


def test_builds_lines_impedances_and_source_identity_from_duckdb(tmp_path):
    net = build_network(_fixture_db(tmp_path))
    assert network_summary(net) | {"buses": 3, "lines": 1, "impedance_branches": 1, "generators": 2, "loads": 2} == network_summary(net)
    assert net.flux_element_lookup["line:1"] == ("line", 0)
    assert net.flux_element_lookup["impedance:2"] == ("impedance", 0)
    assert net.impedance.at[0, "sn_mva"] == 30
    assert net.impedance.at[0, "xft_pu"] == pytest.approx(0.03)
    assert net.flux_bus_index[30] == 30
    assert net.ext_grid.at[0, "flux_element_id"] == "generator:1"
    assert net.gen.at[0, "flux_element_id"] == "generator:2"


def test_edits_are_immutable_order_sensitive_and_validate_identity(tmp_path):
    net = build_network(_fixture_db(tmp_path))
    edits = (outage("line:1"), add_generator("generator:new", 20, 5), add_load("load:new", 20, 2))
    changed = apply_edits(net, edits)
    assert net.line.at[0, "in_service"]
    assert not changed.line.at[0, "in_service"]
    assert edit_hash(edits) != edit_hash(tuple(reversed(edits)))
    with pytest.raises(SimulationInputError, match="unknown"):
        apply_edits(net, (outage("line:missing"),))
    changed = apply_edits(net, (add_line("line:new", 10, 30, r_pu=0.01, x_pu=0.1, rate_a_mw=50, base_kv=110),))
    assert "line:new" in changed.flux_element_lookup


def test_cascade_sheds_island_and_attributes_modeled_load_without_customers(tmp_path):
    net = build_network(_fixture_db(tmp_path))
    baseline = run_cascade(net)
    assert baseline["lost_load_mw"] == pytest.approx(0.0)
    assert baseline["served_load_mw"] == pytest.approx(30.0)
    assert net.gen.at[0, "p_mw"] == pytest.approx(20.0)
    result = run_cascade(net, (outage("impedance:2"),))
    assert result["lost_load_mw"] == pytest.approx(20.0)
    assert result["served_load_mw"] == pytest.approx(10.0)
    assert {event["element_id"] for event in result["tripped_element_ids"]} >= {"impedance:2", "load:2"}
    assert result["critical_loads_lost"] == [{"cl_id": "7", "kind": "hospital", "name": "fixture hospital"}]
    assert result["county_impacts"] == [{"county_fips": "48003", "lost_mw": 20.0, "fraction_dark": 0.666667, "basis": "synthetic modeled load; customer count unavailable"}]
    assert island_primitives(net, (outage("impedance:2"),))[1]["has_grid_forming_source"] is False


def test_build_fails_closed_on_missing_artifact_or_schema(tmp_path):
    with pytest.raises(SimulationUnavailableError, match="unavailable"):
        build_network(tmp_path / "missing.duckdb")
    path = tmp_path / "partial.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE buses(bus_id BIGINT)")
    with pytest.raises(SimulationUnavailableError, match="missing tables"):
        build_network(path)

from __future__ import annotations

import duckdb
import pandapower as pp
import pytest

from twin.build import _resolve_geometry_element, attach_current_bus_coordinates, build_network, network_summary
from twin.contracts import SYNTHETIC_TOPOLOGY_LABEL, SimulationUnavailableError


def test_build_network_imports_a_matpower_case(tmp_path) -> None:
    case = tmp_path / "case3.m"
    case.write_text(
        "function mpc = case3\nmpc.version='2';\nmpc.baseMVA=100;\n"
        "mpc.bus=[\n1 3 0 0 0 0 1 1 0 110 1 1.1 0.9;\n2 1 10 0 0 0 1 1 0 110 1 1.1 0.9;\n];\n"
        "mpc.gen=[\n1 10 0 10 -10 1 100 1 100 0;\n];\n"
        "mpc.branch=[\n1 2 0.01 0.1 0 100 100 100 0 0 1 -360 360;\n];\n"
    )
    net = build_network(case)
    assert network_summary(net) == {
        "topology": SYNTHETIC_TOPOLOGY_LABEL,
        "buses": 2,
        "lines": 1,
        "impedance_branches": 0,
        "loads": 1,
        "generators": 0,
    }
    assert net.line.at[0, "flux_element_id"] == "line:1"


def test_coordinate_hydration_rejects_noncurrent_or_partial_records(tmp_path) -> None:
    case = tmp_path / "case3.m"
    case.write_text(
        "function mpc = case3\nmpc.version='2';\nmpc.baseMVA=100;\n"
        "mpc.bus=[\n1 3 0 0 0 0 1 1 0 110 1 1.1 0.9;\n2 1 10 0 0 0 1 1 0 110 1 1.1 0.9;\n];\n"
        "mpc.gen=[\n1 10 0 10 -10 1 100 1 100 0;\n];\n"
        "mpc.branch=[\n1 2 0.01 0.1 0 100 100 100 0 0 1 -360 360;\n];\n"
    )
    db = tmp_path / "grid.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE buses(bus_id BIGINT, name TEXT, base_kv DOUBLE, lon DOUBLE, lat DOUBLE, coord_source TEXT)")
    con.execute("INSERT INTO buses VALUES (1, 'one', 110, -97, 30, 'old_2016_aux')")
    con.close()
    with pytest.raises(SimulationUnavailableError, match="current AUX"):
        attach_current_bus_coordinates(build_network(case), db)


def test_geometry_resolves_same_one_based_impedance_alias_as_cascade() -> None:
    net = pp.create_empty_network()
    first, second = pp.create_bus(net, 110), pp.create_bus(net, 110)
    pp.create_impedance(net, first, second, rft_pu=0.01, xft_pu=0.1, sn_mva=10)
    net.impedance["flux_element_id"] = ["impedance:7"]
    canonical, resolved = _resolve_geometry_element(net, {"impedance:7": ("impedance", 0)}, "impedance:1")
    assert canonical == "impedance:7"
    assert resolved == ("impedance", 0)

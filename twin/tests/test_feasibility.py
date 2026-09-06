from types import SimpleNamespace

import duckdb
import pandas as pd

from twin.build import build_network
from twin.contracts import GridEdit
from twin.feasibility import evaluate_feasibility


def _net(*, kv: float = 345.0, generated: bool = True, loading: float | None = None):
    result = SimpleNamespace(
        bus=pd.DataFrame({"vn_kv": [kv]}, index=[1]),
        line=pd.DataFrame(columns=["from_bus", "to_bus", "in_service"]),
        gen=pd.DataFrame(columns=["bus", "max_p_mw", "in_service"]),
        sgen=pd.DataFrame(columns=["bus", "max_p_mw", "in_service"]),
        ext_grid=pd.DataFrame({"bus": [1], "in_service": [generated]})
        if generated
        else pd.DataFrame(columns=["bus", "in_service"]),
    )
    if loading is not None:
        result.res_line = pd.DataFrame({"loading_percent": [loading]}, index=[22])
        result.line = pd.DataFrame(
            {"from_bus": [1], "to_bus": [1], "in_service": [True]}, index=[22]
        )
    return result


def _load(**overrides):
    edit = {"kind": "add_load", "bus_id": 1, "p_mw": 200.0, "length_km": 12.0}
    edit.update(overrides)
    return edit


def test_far_interconnection_is_invalid_with_p1_reason():
    result = evaluate_feasibility(_net(), _load(length_km=80.0))

    assert result["status"] == "invalid"
    assert result["rule"] == "P1"
    assert result["reason"] == "interconnect_distance_exceeds_40_km"


def _foundation_net(tmp_path):
    path = tmp_path / "grid.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE buses(bus_id BIGINT, name TEXT, base_kv DOUBLE, "
            "lon DOUBLE, lat DOUBLE, county_fips TEXT)"
        )
        con.execute(
            "CREATE TABLE lines(line_id BIGINT, from_bus BIGINT, to_bus BIGINT, "
            "base_kv DOUBLE, r_pu DOUBLE, x_pu DOUBLE, rate_a_mw DOUBLE, "
            "length_km DOUBLE, is_transformer BOOLEAN)"
        )
        con.execute(
            "CREATE TABLE gens(gen_id BIGINT, bus_id BIGINT, fuel TEXT, pmax_mw DOUBLE)"
        )
        con.execute(
            "CREATE TABLE loads(load_id BIGINT, bus_id BIGINT, p_mw_nominal DOUBLE)"
        )
        con.execute("INSERT INTO buses VALUES (101, 'source', 345, -97, 30, '48001')")
        con.execute("INSERT INTO gens VALUES (1, 101, 'ng', 500)")
    return build_network(path)


def test_12_km_345_kv_connection_is_valid_on_immutable_foundation(tmp_path):
    net = _foundation_net(tmp_path)
    edit = GridEdit("add_load", "load:proposal", bus_id=101, p_mw=200.0, length_km=12.0)

    result = evaluate_feasibility(net, edit)

    assert result["status"] == "valid"
    assert result["reason"] == "placement_screen_passed"
    assert len(net.load) == 0  # feasibility applied the immutable edit to a copy


def test_outside_ercot_is_unknown_not_a_fabricated_verdict():
    result = evaluate_feasibility(_net(), _load(interconnection="SPP"))

    assert result == {
        "status": "unknown",
        "rule": "P5",
        "reason": "outside_ercot_interconnection",
        "evidence": {"interconnection": "SPP"},
    }


def test_large_unit_on_low_voltage_bus_fails_p2_screening_choice():
    result = evaluate_feasibility(_net(kv=138.0), _load(p_mw=301.0))

    assert result["status"] == "invalid"
    assert result["rule"] == "P2"
    assert result["reason"] == "large_unit_requires_230_kv_screening_choice"
    assert result["evidence"]["basis"] == "unverified_screening_choice"


def test_radial_spur_screen_is_named_p3_rule():
    result = evaluate_feasibility(_net(), _load(spur_length_km=41.0))

    assert result["status"] == "invalid"
    assert result["rule"] == "P3"
    assert result["reason"] == "radial_spur_exceeds_40_km_screening_choice"


def test_corridor_overload_is_invalid_p4():
    result = evaluate_feasibility(_net(loading=100.1), _load())

    assert result["status"] == "invalid"
    assert result["rule"] == "P4"
    assert result["reason"] == "corridor_loading_exceeds_100_percent"
    assert result["evidence"]["line_indices"] == [22]


def test_attach_island_without_generation_is_invalid_p6():
    result = evaluate_feasibility(_net(generated=False), _load())

    assert result["status"] == "invalid"
    assert result["rule"] == "P6"
    assert result["reason"] == "attach_island_has_no_generation"


def test_ordered_edits_keep_individual_outcomes():
    results = evaluate_feasibility(_net(), [_load(), _load(length_km=80.0)])

    assert [row["status"] for row in results] == ["valid", "invalid"]

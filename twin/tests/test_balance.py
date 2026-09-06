from __future__ import annotations

import math

import pandapower as pp
import pytest

from twin.balance import balance_report
from twin.contracts import SimulationInputError
from twin.edits import outage


def _net():
    net = pp.create_empty_network(sn_mva=100.0)
    buses = [
        pp.create_bus(net, 230.0, name=f"bus-{source_id}")
        for source_id in (101, 102, 103)
    ]
    net["flux_bus_index"] = {101: buses[0], 102: buses[1], 103: buses[2]}
    net["flux_bus_metadata"] = {
        buses[0]: {
            "bus_id": 101,
            "state": "TX",
            "ba_code": "ERCO",
            "county_fips": "48001",
        },
        buses[1]: {
            "bus_id": 102,
            "state": "TX",
            "ba_code": "ERCO",
            "county_fips": "48003",
        },
        buses[2]: {
            "bus_id": 103,
            "state": "TX",
            "ba_code": "ERCO",
            "county_fips": "48005",
        },
    }
    net["flux_element_lookup"] = {}

    line_101_102 = pp.create_line_from_parameters(
        net, buses[0], buses[1], 1.0, 0.01, 0.1, 0.0, 1.0, name="line:10"
    )
    line_102_103 = pp.create_line_from_parameters(
        net, buses[1], buses[2], 1.0, 0.01, 0.1, 0.0, 1.0, name="line:11"
    )
    for index, element_id in ((line_101_102, "line:10"), (line_102_103, "line:11")):
        net.line.at[index, "flux_element_id"] = element_id
        net.flux_element_lookup[element_id] = ("line", index)

    ext = pp.create_ext_grid(net, buses[0], name="generator:1")
    net.ext_grid.at[ext, "pmax_mw"] = 20.0
    net.ext_grid.at[ext, "fuel"] = "natural gas"
    coal = pp.create_gen(
        net, buses[0], p_mw=40.0, vm_pu=1.0, max_p_mw=100.0, name="generator:2"
    )
    wind = pp.create_gen(
        net, buses[1], p_mw=10.0, vm_pu=1.0, max_p_mw=50.0, name="generator:3"
    )
    solar = pp.create_sgen(net, buses[2], p_mw=0.0, max_p_mw=30.0, name="generator:4")
    net.gen.at[coal, "fuel"] = "coal"
    net.gen.at[wind, "fuel"] = "wind"
    net.sgen.at[solar, "fuel"] = "solar"
    pp.create_load(net, buses[0], p_mw=100.0, q_mvar=0.0, name="load:1")
    pp.create_load(net, buses[1], p_mw=30.0, q_mvar=0.0, name="load:2")
    pp.create_load(net, buses[2], p_mw=20.0, q_mvar=0.0, name="load:3")
    return net


def test_state_balance_is_checkable_nameplate_accounting_with_fuel_split():
    result = balance_report(_net())

    assert result["scope"] == "state"
    assert result["scope_id"] is None
    assert result["bus_ids"] == [101, 102, 103]
    assert result["draw_mw"] == 150.0
    assert result["capability_mw"] == 200.0
    assert result["dispatch_mw"] == 50.0
    assert result["headroom_mw"] == 50.0
    assert result["reserve_margin"] == pytest.approx(1 / 3)
    assert result["firm_capability_mw"] == 120.0
    assert result["wind_capability_mw"] == 50.0
    assert result["solar_capability_mw"] == 30.0
    assert result["unclassified_capability_mw"] == 0.0
    assert result["capability_basis"] == "nameplate; not availability-derated"


@pytest.mark.parametrize(
    ("scope", "scope_id", "expected_draw", "expected_capability"),
    [
        ("state", "TX", 150.0, 200.0),
        ("ba", "ERCO", 150.0, 200.0),
        ("county", "48003", 30.0, 50.0),
    ],
)
def test_state_ba_and_county_scopes_use_only_declared_bus_identity(
    scope, scope_id, expected_draw, expected_capability
):
    result = balance_report(_net(), scope=scope, scope_id=scope_id)

    assert result["draw_mw"] == expected_draw
    assert result["capability_mw"] == expected_capability
    assert result["headroom_mw"] == expected_capability - expected_draw


def test_edited_island_scope_uses_same_in_service_connectivity_as_cascade():
    net = _net()
    result = balance_report(
        net, scope="island", scope_id=101, edits=[outage("line:10")]
    )

    assert result["bus_ids"] == [101]
    assert result["draw_mw"] == 100.0
    assert result["capability_mw"] == 120.0
    assert result["dispatch_mw"] == 40.0
    assert result["headroom_mw"] == 20.0
    assert result["reserve_margin"] == pytest.approx(0.2)
    assert (
        result["edit_hash"]
        != balance_report(net, scope="island", scope_id=101)["edit_hash"]
    )
    assert net.line.at[0, "in_service"]


def test_zero_draw_has_no_reserve_ratio_and_unknown_fuel_is_not_firm():
    net = _net()
    net.load["in_service"] = False
    net.gen.at[0, "fuel"] = "not-source-qualified"

    result = balance_report(net)

    assert result["reserve_margin"] is None
    assert result["firm_capability_mw"] == 20.0
    assert result["unclassified_capability_mw"] == 100.0
    assert math.isclose(result["headroom_mw"], result["capability_mw"])


def test_scope_without_declared_identity_fails_instead_of_using_all_buses():
    net = _net()
    for metadata in net.flux_bus_metadata.values():
        metadata.pop("ba_code")

    with pytest.raises(SimulationInputError, match="no declared ba identity"):
        balance_report(net, scope="ba", scope_id="ERCO")

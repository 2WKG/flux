"""Behavioural tests for the invariants the synthetic cascade core exists to hold.

Every assertion here is written against a *literal*, never against the constant
the production code emits, so that changing the constant is detectable.
"""

from __future__ import annotations

import duckdb
import pandapower as pp
import pytest

from twin.build import (
    build_network,
    cached_base_network,
    model_geometry,
    network_summary,
)
from twin.cascade import (
    balance_report,
    control_room_payload,
    feasibility_report,
    rank_candidate_placements,
    redundancy_report,
    run_cascade,
    texas_stress_preset,
)
from twin.contracts import (
    SYNTHETIC_TOPOLOGY_LABEL,
    SimulationInputError,
    SimulationSolveError,
    SimulationUnavailableError,
)

# The exact string CLAUDE.md and docs/specs/00-overview.md require every
# user-visible synthetic result to carry.  Written out, not imported.
CANONICAL_LABEL = "synthetic (ACTIVSg2000)"

_CASE_TEXT = (
    "function mpc = case3\nmpc.version='2';\nmpc.baseMVA=100;\n"
    "mpc.bus=[\n1 3 0 0 0 0 1 1 0 110 1 1.1 0.9;\n2 1 10 0 0 0 1 1 0 110 1 1.1 0.9;\n];\n"
    "mpc.gen=[\n1 10 0 10 -10 1 100 1 100 0;\n];\n"
    "mpc.branch=[\n1 2 0.01 0.1 0 100 100 100 0 0 1 -360 360;\n];\n"
    "mpc.bus_name = {\n'ALPHA';\n'BRAVO';\n};\n"
)


def _case(tmp_path):
    case = tmp_path / "case3.m"
    case.write_text(_CASE_TEXT)
    return case


def _current_aux_db(tmp_path, net):
    db = tmp_path / "grid.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE buses(bus_id BIGINT, name TEXT, base_kv DOUBLE, "
        "lon DOUBLE, lat DOUBLE, coord_source TEXT)"
    )
    for offset, bus_id in enumerate(net.bus.index):
        con.execute(
            "INSERT INTO buses VALUES (?, ?, ?, ?, ?, 'tamu_aux')",
            [
                7000 + offset,
                str(net.bus.at[bus_id, "name"]),
                float(net.bus.at[bus_id, "vn_kv"]),
                -97.0 - offset,
                30.0 + offset,
            ],
        )
    con.close()
    return db


def _overloaded_impedance_net():
    net = pp.create_empty_network(sn_mva=100)
    buses = [pp.create_bus(net, 110) for _ in range(3)]
    pp.create_ext_grid(net, buses[0])
    pp.create_line_from_parameters(net, buses[0], buses[1], 1, 0.01, 0.1, 0, 1.0)
    pp.create_impedance(net, buses[1], buses[2], rft_pu=0.001, xft_pu=0.01, sn_mva=5)
    pp.create_load(net, buses[2], p_mw=10)
    return net


def test_synthetic_topology_label_is_pinned_to_its_exact_literal() -> None:
    """CLAUDE.md: 'ACTIVSg2000 is synthetic topology; label it in user-visible results.'"""
    assert SYNTHETIC_TOPOLOGY_LABEL == "synthetic (ACTIVSg2000)"


def test_every_user_visible_payload_carries_the_literal_synthetic_label(
    tmp_path,
) -> None:
    net = _overloaded_impedance_net()
    pp.create_gen(net, 0, p_mw=1, vm_pu=1, max_p_mw=20, min_p_mw=0)

    cascade = run_cascade(["load:1"], "storm", 1, net=net)
    assert cascade["topology"] == CANONICAL_LABEL
    assert cascade["synthetic"] is True

    assert rank_candidate_placements(net, [0, 1])[0]["topology"] == CANONICAL_LABEL
    assert redundancy_report(net, [0, 2])[0]["topology"] == CANONICAL_LABEL
    assert balance_report(net)["topology"] == CANONICAL_LABEL
    assert any(
        CANONICAL_LABEL in line for line in feasibility_report(net)["limitations"]
    )

    case = _case(tmp_path)
    built = build_network(case)
    assert network_summary(built)["topology"] == CANONICAL_LABEL

    hydrated = build_network(case, db_path=_current_aux_db(tmp_path, built))
    geometry = model_geometry(hydrated, ["line:1"])
    assert geometry["data"]["topology"]["label"] == CANONICAL_LABEL
    assert geometry["data"]["elements"][0]["provenance"]["topology"] == CANONICAL_LABEL


def test_a_failed_dc_solve_refuses_by_name_instead_of_returning_a_cascade() -> None:
    """CLAUDE.md: failed solves produce explicit errors, never plausible defaults."""
    unsolvable = pp.create_empty_network(sn_mva=100)
    first, second = pp.create_bus(unsolvable, 110), pp.create_bus(unsolvable, 110)
    pp.create_line_from_parameters(unsolvable, first, second, 1, 0.01, 0.1, 0, 1.0)
    pp.create_load(unsolvable, second, p_mw=10)
    pp.create_gen(unsolvable, first, p_mw=10, vm_pu=1, max_p_mw=10, min_p_mw=0)

    with pytest.raises(SimulationSolveError, match="rundcpp"):
        balance_report(unsolvable)
    with pytest.raises(SimulationSolveError, match="rundcpp"):
        run_cascade([], "storm", 0, net=unsolvable)

    report = feasibility_report(unsolvable)
    assert report["status"] == "solver_failed"
    assert report["dc_solve_converged"] is False


def test_a_nonconverged_dc_solve_refuses_by_name(monkeypatch) -> None:
    """A silent ``converged=False`` must not yield a cascade off stale res_* frames."""
    import twin.cascade as cascade_module

    def _nonconverging(net, *args, **kwargs):
        net["converged"] = False

    monkeypatch.setattr(cascade_module.pp, "rundcpp", _nonconverging)
    with pytest.raises(SimulationSolveError, match="did not converge"):
        run_cascade([], "storm", 0, net=_overloaded_impedance_net())


def test_public_build_hydrates_current_aux_coordinates(tmp_path) -> None:
    """``build_network(case, db_path=...)`` must reach the hydration call site."""
    case = _case(tmp_path)
    db = _current_aux_db(tmp_path, build_network(case))

    net = build_network(case, db_path=db)

    assert net["flux_coordinate_source"] == "tamu_aux"
    assert net.bus.flux_source_bus_id.tolist() == [7000, 7001]
    assert '"type": "Point"' in str(net.bus.at[0, "geo"])
    # Without the db the hydration must not happen (and must not be faked).
    assert "flux_source_bus_id" not in build_network(case).bus


def test_cached_base_network_reuses_one_baseline_and_fails_closed(tmp_path) -> None:
    case = _case(tmp_path)
    first = cached_base_network(case)
    assert cached_base_network(case) is first
    assert network_summary(first)["buses"] == 2

    with pytest.raises(
        SimulationUnavailableError, match="MATPOWER case is unavailable"
    ):
        cached_base_network(tmp_path / "absent.m")
    with pytest.raises(
        SimulationUnavailableError, match="coordinate database is unavailable"
    ):
        cached_base_network(case, db_path=tmp_path / "absent.duckdb")


def test_persistence_guard_refuses_counterfactual_and_nondefault_settings(
    tmp_path,
) -> None:
    db = tmp_path / "grid.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE cascade_runs (run_id TEXT, scenario_id TEXT, hour INTEGER, "
        "tripped_element_ids_json JSON, lost_load_mw DOUBLE, counties_dark_json JSON, "
        "critical_loads_lost_json JSON, source_name TEXT, source_ref TEXT, "
        "source_version TEXT, source_retrieved_at TIMESTAMP, fixture_batch_id TEXT)"
    )
    con.close()

    def _net_with_generation():
        net = _overloaded_impedance_net()
        pp.create_gen(net, 0, p_mw=10, vm_pu=1, max_p_mw=20, min_p_mw=0)
        return net

    for kwargs in (
        {"max_stages": 4},
        {"overload_limit_pct": 150.0},
        {"unit_mw": 5.0, "site_bus": 0},
    ):
        with pytest.raises(SimulationInputError, match="counterfactual workflow"):
            run_cascade(
                ["load:1"],
                "storm",
                2,
                net=_net_with_generation(),
                db_path=db,
                write=True,
                **kwargs,
            )

    con = duckdb.connect(str(db), read_only=True)
    assert con.execute("SELECT count(*) FROM cascade_runs").fetchone()[0] == 0
    con.close()


def test_texas_stress_preset_is_derived_from_solved_loadings() -> None:
    net = _overloaded_impedance_net()
    preset = texas_stress_preset("storm", 3, net=net, force_count=1)

    assert preset["preset_id"].startswith("synthetic_texas_n")
    assert preset["topology"] == CANONICAL_LABEL
    assert preset["source_kind"] == "simulated"
    assert preset["forced_element_ids"][0] == "line:1"
    selected = preset["selection"]["baseline_line_loading_percent"]
    assert [row["element_id"] for row in selected] == ["line:1"]
    assert selected[0]["loading_percent"] > 0
    assert preset["cascade"]["topology"] == CANONICAL_LABEL
    assert preset["timeline"] == preset["cascade"]["tripped_element_ids"]
    assert any(event["cause"] == "forced" for event in preset["timeline"])

    with pytest.raises(SimulationInputError, match="force_count"):
        texas_stress_preset("storm", 3, net=net, force_count=0)


def test_control_room_payload_refuses_to_qualify_playback_without_receipts(
    tmp_path,
) -> None:
    result = run_cascade(["load:1"], "storm", 1, net=_overloaded_impedance_net())

    with pytest.raises(SimulationUnavailableError, match="control-room database"):
        control_room_payload(result, tmp_path / "absent.duckdb")
    with pytest.raises(SimulationInputError, match="missing run_id"):
        control_room_payload({}, tmp_path / "absent.duckdb")

    empty = tmp_path / "empty.duckdb"
    duckdb.connect(str(empty)).close()
    unqualified = control_room_payload(result, empty)
    assert unqualified["qualification"]["playback_qualified"] is False
    assert "missing tables" in unqualified["qualification"]["reasons"][0]
    assert unqualified["topology"]["label"] == CANONICAL_LABEL
    assert unqualified["persisted_provenance"] is None

    db = tmp_path / "grid.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE ingest_log(source TEXT, source_release TEXT, source_file TEXT, sha256 TEXT)"
    )
    con.execute(
        "CREATE TABLE scenarios(scenario_id TEXT, source_name TEXT, source_ref TEXT, source_version TEXT)"
    )
    con.execute(
        "CREATE TABLE weather_source_runs(scenario_id TEXT, source TEXT, source_release TEXT, "
        "receipt_path TEXT, grid_signature TEXT, valid_ts TIMESTAMP)"
    )
    con.execute(
        "CREATE TABLE cascade_runs(run_id TEXT, hour INTEGER, source_name TEXT, source_ref TEXT, "
        "source_version TEXT, fixture_batch_id TEXT)"
    )
    con.close()
    payload = control_room_payload(result, db)
    assert payload["qualification"]["playback_qualified"] is False
    assert set(payload["qualification"]["reasons"]) == {
        "current MATPOWER/AUX receipts are incomplete",
        "scenario is unavailable",
        "weather source-run receipt is unavailable",
        "cascade result is not persisted",
    }


def test_model_geometry_reports_unresolved_elements_instead_of_guessing(
    tmp_path,
) -> None:
    case = _case(tmp_path)
    db = _current_aux_db(tmp_path, build_network(case))
    net = build_network(case, db_path=db)

    geometry = model_geometry(net, ["line:1", "line:99"])
    assert geometry["status"] == "partial"
    assert "could not be resolved" in geometry["reason"]
    resolved, unresolved = geometry["data"]["elements"]
    assert resolved["resolved"] is True
    assert resolved["role"] == "line"
    assert resolved["geometry"]["type"] == "LineString"
    assert resolved["source_bus_ids"] == [7000, 7001]
    assert unresolved == {
        "element_id": "line:99",
        "resolved": False,
        "reason": "unknown synthetic model element",
    }
    assert geometry["data"]["provenance"]["physical_inventory_equivalence"] is False

    with pytest.raises(SimulationUnavailableError, match="model geometry requires"):
        model_geometry(build_network(case))

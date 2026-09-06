"""Exercise topology/county write ordering with a small synthetic electrical fixture."""

import numpy as np
import pandas as pd
from shapely.geometry import box

from pipelines import activsg
from pipelines.db import connect, replace_frame


def test_topology_links_counties_before_children_and_reloads(tmp_path, monkeypatch):
    # The parser's 2,000-bus contract stays intact; only one branch and generator
    # are needed to enforce the real DuckDB foreign keys.
    buses = np.zeros((2000, 13))
    buses[:, 0] = np.arange(1, 2001)
    buses[:, 2] = 1
    buses[:, 9] = 230
    branch = np.array([[1, 2, 0.01, 0.1, 0, 100, 0, 0, 0, 0, 1]])
    gen = np.array([[1, 1, 0, 0, 0, 0, 0, 1, 100, 0]])
    matrices = {"bus": buses, "branch": branch, "gen": gen}
    monkeypatch.setattr(activsg, "_numeric_matrix", lambda _text, name: matrices[name])
    monkeypatch.setattr(
        activsg,
        "_string_cell",
        lambda _text, name: (
            [str(i) for i in range(2000)] if name == "bus_name" else ["gas"]
        ),
    )
    coords = pd.DataFrame(
        {
            "bus_id": np.arange(1, 2001),
            "base_kv_aux": 230,
            "lon": -95.0,
            "lat": 30.0,
            "sub_num": np.arange(1, 2001),
            "sub_name": "fixture",
            "sub_id": np.arange(1, 2001),
        }
    )
    monkeypatch.setattr(activsg, "read_aux_coords", lambda _path: coords)
    case, aux = tmp_path / "case.m", tmp_path / "case.aux"
    case.write_text("synthetic test fixture")
    aux.write_text("synthetic test fixture")
    con = connect(tmp_path / "grid.duckdb")
    try:
        county = pd.DataFrame(
            [
                {
                    "county_fips": "48001",
                    "name": "fixture",
                    "state": "TX",
                    "pop": 1,
                    "geom_wkb": box(-96, 29, -94, 31).wkb,
                }
            ]
        )
        for _ in range(2):
            replace_frame(
                con,
                "counties",
                county,
                source_name="test",
                source_ref="fixture",
                fixture_batch_id="test",
            )
            counts = activsg.load_activsg(con, str(aux), str(case))
            assert counts["loads"] == 2000
            assert con.execute(
                "SELECT count(*) FROM buses WHERE county_fips = '48001'"
            ).fetchone() == (2000,)
            assert con.execute("SELECT count(*) FROM lines").fetchone() == (1,)
    finally:
        con.close()


def test_load_activsg_classifies_transformers_by_base_kv_only(tmp_path, monkeypatch):
    # Wire test for the P0 impedance-branch rule at the call site: a base-kV
    # transition is a transformer; a same-kV branch with a MATPOWER tap of 1.0
    # is a phase-shifting line.  The `base_kv OR tap != 0` heuristic marks both
    # as transformers (861 instead of 847 on the real case).
    buses = np.zeros((2000, 13))
    buses[:, 0] = np.arange(1, 2001)
    buses[:, 2] = 1
    buses[:, 9] = 230
    buses[1, 9] = 138
    branch = np.array(
        [
            [1, 2, 0.01, 0.1, 0, 100, 0, 0, 1.0, 0, 1],
            [1, 3, 0.01, 0.1, 0, 100, 0, 0, 1.0, 0, 1],
        ]
    )
    gen = np.array([[1, 1, 0, 0, 0, 0, 0, 1, 100, 0]])
    matrices = {"bus": buses, "branch": branch, "gen": gen}
    monkeypatch.setattr(activsg, "_numeric_matrix", lambda _text, name: matrices[name])
    monkeypatch.setattr(
        activsg,
        "_string_cell",
        lambda _text, name: (
            [str(i) for i in range(2000)] if name == "bus_name" else ["gas"]
        ),
    )
    coords = pd.DataFrame(
        {
            "bus_id": np.arange(1, 2001),
            "base_kv_aux": buses[:, 9],
            "lon": -95.0,
            "lat": 30.0,
            "sub_num": np.arange(1, 2001),
            "sub_name": "fixture",
            "sub_id": np.arange(1, 2001),
        }
    )
    monkeypatch.setattr(activsg, "read_aux_coords", lambda _path: coords)
    case, aux = tmp_path / "case.m", tmp_path / "case.aux"
    case.write_text("synthetic test fixture")
    aux.write_text("synthetic test fixture")
    con = connect(tmp_path / "grid.duckdb")
    try:
        county = pd.DataFrame(
            [
                {
                    "county_fips": "48001",
                    "name": "fixture",
                    "state": "TX",
                    "pop": 1,
                    "geom_wkb": box(-96, 29, -94, 31).wkb,
                }
            ]
        )
        replace_frame(
            con,
            "counties",
            county,
            source_name="test",
            source_ref="fixture",
            fixture_batch_id="test",
        )
        activsg.load_activsg(con, str(aux), str(case))
        observed = con.execute(
            "SELECT line_id, is_transformer, length_km FROM lines ORDER BY line_id"
        ).fetchall()
    finally:
        con.close()
    assert observed == [(1, True, 0.0), (2, False, 0.0)]

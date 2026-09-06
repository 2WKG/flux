from __future__ import annotations

import duckdb

from pipelines.node_annotations import read_node_annotations


def test_node_annotations_are_deterministic_and_do_not_hide_both_roles() -> None:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE buses (bus_id BIGINT, county_fips TEXT, ba_code TEXT)")
    con.execute("CREATE TABLE gens (bus_id BIGINT, fuel TEXT, pmax_mw DOUBLE)")
    con.execute("CREATE TABLE loads (bus_id BIGINT, p_mw_nominal DOUBLE)")
    con.execute("CREATE TABLE counties (county_fips TEXT, name TEXT)")
    con.execute(
        "CREATE TABLE critical_loads (cl_id BIGINT, kind TEXT, name TEXT, bus_id BIGINT)"
    )
    con.execute(
        "INSERT INTO buses VALUES (4, NULL, NULL), (3, '48453', 'ERCO'), (2, '48453', 'ERCO'), (1, '48453', 'ERCO')"
    )
    con.execute("INSERT INTO counties VALUES ('48453', 'Travis')")
    con.execute(
        "INSERT INTO gens VALUES (1, 'solar', 10), (1, 'gas', 20), (3, 'wind', 30)"
    )
    con.execute("INSERT INTO loads VALUES (1, 5), (2, 8), (3, 0)")
    con.execute(
        "INSERT INTO critical_loads VALUES (9, 'hospital', 'A', 1), (2, 'water', 'B', 1)"
    )

    annotations = read_node_annotations(con)

    assert [node.bus_id for node in annotations] == [1, 2, 3, 4]
    assert [node.role for node in annotations] == [
        "both",
        "consumer",
        "producer",
        "transmission",
    ]
    both = annotations[0]
    assert both.generation_capacity_mw == 30
    assert both.fuel_mix == ("gas", "solar")
    assert both.nominal_draw_mw == 5
    assert both.county_name == "Travis"
    assert both.critical_loads == (
        {"cl_id": 2, "name": "B", "kind": "water"},
        {"cl_id": 9, "name": "A", "kind": "hospital"},
    )
    assert both.field_provenance["role"] == "derived"
    assert annotations[-1].field_provenance["county_name"] == "unavailable"
    assert annotations[-1].field_provenance["critical_loads"] == "unavailable"

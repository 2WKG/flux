from __future__ import annotations

import duckdb
import pytest

from pipelines.labels import NODE_ROLES, SYNTHETIC_TOPOLOGY_LABEL
from pipelines.node_annotations import read_node_annotations


def _schema(con: duckdb.DuckDBPyConnection, *, with_receipts: bool = True) -> None:
    con.execute("CREATE TABLE buses (bus_id BIGINT, county_fips TEXT, ba_code TEXT)")
    con.execute("CREATE TABLE gens (bus_id BIGINT, fuel TEXT, pmax_mw DOUBLE)")
    con.execute("CREATE TABLE loads (bus_id BIGINT, p_mw_nominal DOUBLE)")
    con.execute("CREATE TABLE counties (county_fips TEXT, name TEXT)")
    con.execute(
        "CREATE TABLE critical_loads (cl_id BIGINT, kind TEXT, name TEXT, bus_id BIGINT)"
    )
    if with_receipts:
        con.execute(
            "CREATE TABLE critical_load_bus_dist (cl_id BIGINT, bus_id BIGINT,"
            " distance_km DOUBLE, match_method TEXT)"
        )


def _fixture(con: duckdb.DuckDBPyConnection) -> None:
    """Four buses covering every role and every provenance branch.

    Bus 1: generation + a positive load (both), a county, two facilities.
    Bus 2: a positive load only (consumer), a county, no `ba_code`.
    Bus 3: generation + a **0 MW** load row (producer), a county.
    Bus 4: no gens, no load row, no county, but a `ba_code`.
    Bus 5: a `county_fips` with no `counties` row (a broken foreign key).
    """
    con.execute(
        "INSERT INTO buses VALUES (5, '48999', 'ERCO'), (4, NULL, 'ERCO'),"
        " (3, '48453', 'ERCO'), (2, '48453', NULL), (1, '48453', 'ERCO')"
    )
    con.execute("INSERT INTO counties VALUES ('48453', 'Travis')")
    # Inserted worst-first on purpose: without `list_sort` the aggregate keeps
    # insertion order and the assertion below flips.
    con.execute(
        "INSERT INTO gens VALUES (1, 'wind', 10), (1, 'gas', 20), (3, 'solar', 30)"
    )
    con.execute("INSERT INTO loads VALUES (1, 5), (2, 8), (3, 0)")
    con.execute(
        "INSERT INTO critical_loads VALUES (9, 'hospital', 'A', 1), (2, 'water', 'B', 1)"
    )
    con.execute("INSERT INTO critical_load_bus_dist VALUES (9, 1, 3.5, 'same_county')")


def test_node_annotations_are_deterministic_and_do_not_hide_both_roles() -> None:
    con = duckdb.connect(":memory:")
    _schema(con)
    _fixture(con)

    annotations = read_node_annotations(con)

    assert [node.bus_id for node in annotations] == [1, 2, 3, 4, 5]
    assert [node.role for node in annotations] == [
        "both",
        "consumer",
        "producer",
        "transmission",
        "transmission",
    ]
    assert {node.role for node in annotations} <= set(NODE_ROLES)
    both = annotations[0]
    assert both.generation_capacity_mw == 30
    # `wind` was inserted before `gas`; only `list_sort` makes this order true.
    assert both.fuel_mix == ("gas", "wind")
    assert both.nominal_draw_mw == 5
    assert both.county_name == "Travis"
    assert both.field_provenance["role"] == "derived"
    assert annotations[-2].field_provenance["county_name"] == "unavailable"
    assert annotations[-2].field_provenance["critical_loads"] == "unavailable"


def test_every_record_carries_the_synthetic_topology_label() -> None:
    con = duckdb.connect(":memory:")
    _schema(con)
    _fixture(con)

    annotations = read_node_annotations(con)

    assert {node.topology for node in annotations} == {SYNTHETIC_TOPOLOGY_LABEL}
    assert {node.field_provenance["topology"] for node in annotations} == {"synthetic"}
    assert annotations[0].as_dict()["topology"] == SYNTHETIC_TOPOLOGY_LABEL


def test_spatially_joined_bindings_are_labelled_synthetic_not_source_backed() -> None:
    """`county_*` and `critical_loads` bind to a bus through a spatial guess.

    `join_bus_county` drops a synthetic ACTIVSg2000 coordinate into TIGER
    polygons with a 30 km fallback and `join_critical_loads_to_bus` takes the
    nearest eligible bus, so neither binding may claim `source_backed`.
    """
    con = duckdb.connect(":memory:")
    _schema(con)
    _fixture(con)

    annotations = {node.bus_id: node for node in read_node_annotations(con)}

    assert annotations[1].field_provenance["county_name"] == "synthetic"
    assert annotations[1].field_provenance["county_fips"] == "synthetic"
    assert annotations[1].field_provenance["critical_loads"] == "synthetic"
    assert "source_backed" not in set(annotations[1].field_provenance.values())


def test_critical_loads_carry_their_spatial_join_receipt() -> None:
    con = duckdb.connect(":memory:")
    _schema(con)
    _fixture(con)

    annotations = {node.bus_id: node for node in read_node_annotations(con)}

    assert annotations[1].critical_loads == (
        {
            "id": 2,
            "name": "B",
            "kind": "water",
            "bus_id": 1,
            # No `critical_load_bus_dist` row for facility 2: named, not guessed.
            "binding_method": "receipt_missing",
            "binding_distance_km": None,
        },
        {
            "id": 9,
            "name": "A",
            "kind": "hospital",
            "bus_id": 1,
            "binding_method": "same_county",
            "binding_distance_km": 3.5,
        },
    )


def test_a_missing_receipt_table_is_named_rather_than_defaulted() -> None:
    con = duckdb.connect(":memory:")
    _schema(con, with_receipts=False)
    con.execute("INSERT INTO buses VALUES (1, NULL, NULL)")
    con.execute("INSERT INTO critical_loads VALUES (9, 'hospital', 'A', 1)")

    (annotation,) = read_node_annotations(con)

    assert annotation.critical_loads[0]["binding_method"] == "receipt_table_absent"
    assert annotation.critical_loads[0]["binding_distance_km"] is None


def test_generation_attributes_are_labelled_synthetic() -> None:
    con = duckdb.connect(":memory:")
    _schema(con)
    _fixture(con)

    annotations = {node.bus_id: node for node in read_node_annotations(con)}

    assert annotations[1].field_provenance["generation_capacity_mw"] == "synthetic"
    assert annotations[1].field_provenance["fuel_mix"] == "synthetic"


def test_a_zero_mw_load_row_is_distinguishable_from_no_load_row() -> None:
    con = duckdb.connect(":memory:")
    _schema(con)
    _fixture(con)

    annotations = {node.bus_id: node for node in read_node_annotations(con)}

    zero_mw, no_row = annotations[3], annotations[4]
    assert zero_mw.role == "producer" and zero_mw.nominal_draw_mw is None
    assert no_row.role == "transmission" and no_row.nominal_draw_mw is None
    assert zero_mw.field_provenance["nominal_draw_mw"] == "synthetic"
    assert no_row.field_provenance["nominal_draw_mw"] == "unavailable"


def test_absent_county_and_ba_code_branches_are_each_labelled() -> None:
    con = duckdb.connect(":memory:")
    _schema(con)
    _fixture(con)

    annotations = {node.bus_id: node for node in read_node_annotations(con)}

    # ba_code present, county absent.
    assert annotations[4].field_provenance["ba_code"] == "synthetic"
    assert annotations[4].field_provenance["county_fips"] == "unavailable"
    assert annotations[4].field_provenance["county_name"] == "unavailable"
    # county present, ba_code absent.
    assert annotations[2].field_provenance["ba_code"] == "unavailable"
    assert annotations[2].field_provenance["county_fips"] == "synthetic"


def test_a_dangling_county_fips_is_a_broken_reference_not_absent_data() -> None:
    con = duckdb.connect(":memory:")
    _schema(con)
    _fixture(con)

    annotations = {node.bus_id: node for node in read_node_annotations(con)}

    dangling = annotations[5]
    assert dangling.county_fips == "48999" and dangling.county_name is None
    assert dangling.field_provenance["county_name"] == "broken_reference"


def test_one_annotation_per_bus_is_asserted_rather_than_assumed() -> None:
    con = duckdb.connect(":memory:")
    _schema(con)
    _fixture(con)

    annotations = read_node_annotations(con)
    bus_count = con.execute("SELECT count(*) FROM buses").fetchone()[0]
    assert len(annotations) == bus_count
    assert len({node.bus_id for node in annotations}) == bus_count

    # A duplicated `loads` row (the UNIQUE(bus_id) constraint removed) fans the
    # join out; the adapter must refuse instead of dropping a bus silently.
    con.execute("INSERT INTO loads VALUES (1, 6)")
    with pytest.raises(ValueError, match="one row per bus"):
        read_node_annotations(con)

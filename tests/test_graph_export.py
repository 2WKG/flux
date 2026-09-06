from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from pipelines.db import connect
from pipelines.graph_export import export_texas_graph_dataset


def _fixture_db(path: Path, *, reverse: bool = False) -> None:
    con = connect(path)
    try:
        con.execute(
            """
            INSERT INTO counties (
                county_fips, name, state, pop, geom_wkb, source_name, source_ref,
                source_version, source_retrieved_at, fixture_batch_id
            ) VALUES ('48001', 'Anderson', 'TX', 1, ?, 'activsg2000', 'test',
                      NULL, NULL, 'fixture')
            """,
            [b"geometry"],
        )
        buses = [
            (1, "one", 230, -95, 31),
            (2, "two", 115, -96, 32),
            (3, "three", 115, -97, 33),
        ]
        lines = [
            (1, 1, 2, 230, True),
            (2, 2, 3, 115, False),
        ]
        for bus_id, name, base_kv, lon, lat in reversed(buses) if reverse else buses:
            con.execute(
                """
                INSERT INTO buses (
                    bus_id, name, base_kv, lon, lat, county_fips, ba_code,
                    coord_source, zone, area, source_name, source_ref,
                    source_version, source_retrieved_at, fixture_batch_id
                ) VALUES (?, ?, ?, ?, ?, '48001', NULL, 'tamu_aux', 1, 1,
                          'activsg2000', 'test', NULL, NULL, 'fixture')
                """,
                [bus_id, name, base_kv, lon, lat],
            )
        for line_id, from_bus, to_bus, base_kv, is_transformer in (
            reversed(lines) if reverse else lines
        ):
            con.execute(
                """
                INSERT INTO lines (
                    line_id, from_bus, to_bus, circuit, base_kv, r_pu, x_pu,
                    rate_a_mw, length_km, geom_wkb, is_transformer, source_name,
                    source_ref, source_version, source_retrieved_at, fixture_batch_id
                ) VALUES (?, ?, ?, '1', ?, 0.01, 0.1, NULL, 0, NULL, ?,
                          'activsg2000', 'test', NULL, NULL, 'fixture')
                """,
                [line_id, from_bus, to_bus, base_kv, is_transformer],
            )
        con.execute(
            """
            INSERT INTO synthetic_bus_electrical (
                bus_id, bus_type, pd_mw, qd_mvar, gs_mw, bs_mvar, vm_pu,
                va_deg, vmin_pu, vmax_pu
            ) VALUES (1, 1, 10, NULL, 0, 0, 1, 0, 0.9, 1.1)
            """
        )
        for line_id in (2, 1) if reverse else (1, 2):
            con.execute(
                """
                INSERT INTO synthetic_branch_electrical (
                    line_id, b_pu, tap_ratio, shift_deg, status
                ) VALUES (?, 0, 1, 0, 1)
                """,
                [line_id],
            )
        con.execute(
            """
            INSERT INTO loads (
                load_id, bus_id, p_mw_nominal, source_name, source_ref,
                source_version, source_retrieved_at, fixture_batch_id
            ) VALUES
                (1, 1, 10, 'activsg2000', 'test', NULL, NULL, 'fixture'),
                (2, 3, 0, 'activsg2000', 'test', NULL, NULL, 'fixture')
            """
        )
        con.execute(
            """
            INSERT INTO gens (
                gen_id, bus_id, fuel, pmax_mw, eia_plant_id, source_unit_id,
                source_name, source_ref, source_version, source_retrieved_at,
                fixture_batch_id
            ) VALUES
                (1, 2, 'wind', 25, NULL, 'unit-1', 'activsg2000', 'test',
                 NULL, NULL, 'fixture'),
                (2, 1, 'solar', 0, NULL, 'unit-2', 'activsg2000', 'test',
                 NULL, NULL, 'fixture')
            """
        )
    finally:
        con.close()


def _files(path: Path) -> dict[str, bytes]:
    return {item.name: item.read_bytes() for item in path.iterdir()}


def test_export_is_content_hashed_and_byte_identical(tmp_path: Path) -> None:
    first_database = tmp_path / "first.duckdb"
    second_database = tmp_path / "second.duckdb"
    _fixture_db(first_database)
    _fixture_db(second_database, reverse=True)
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_manifest = export_texas_graph_dataset(first_database, first)
    second_manifest = export_texas_graph_dataset(second_database, second)

    assert _files(first) == _files(second)
    assert first_manifest == second_manifest
    assert (
        first_manifest["files"]["nodes.json"]
        == hashlib.sha256((first / "nodes.json").read_bytes()).hexdigest()
    )
    assert first_manifest["topology_label"] == "synthetic (ACTIVSg2000)"
    assert first_manifest["edge_counts"] == {
        "source_edge_type": {"line": 1, "transformer": 1},
        "solver_edge_type": {"impedance_branch": 1, "line": 1},
    }


def test_export_keeps_missing_values_explicit(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _fixture_db(database)
    target = tmp_path / "dataset"
    export_texas_graph_dataset(database, target)

    nodes = json.loads((target / "nodes.json").read_text())
    edges = json.loads((target / "edges.json").read_text())

    assert "lon" not in nodes[0]["features"]
    assert "lat" not in nodes[0]["features"]
    assert nodes[0]["features"]["p_mw_nominal"] == 10.0
    assert nodes[0]["categorical_features"]["role"] == "both"
    assert nodes[1]["features"]["pmax_mw"] == 25.0
    assert nodes[1]["fuel_capacity_mw"] == {"wind": 25.0}
    assert nodes[1]["categorical_features"]["role"] == "producer"
    assert nodes[2]["features"]["p_mw_nominal"] == 0.0
    assert nodes[2]["fuel_capacity_mw"] == {}
    assert nodes[2]["categorical_features"]["role"] == "consumer"
    assert edges[0]["features"]["rate_a_mw"] is None
    assert not (target / "normalization.json").exists()


def test_export_rejects_source_parent_as_output_without_deleting_db(
    tmp_path: Path,
) -> None:
    database = tmp_path / "grid.duckdb"
    _fixture_db(database)
    original = database.read_bytes()

    try:
        export_texas_graph_dataset(database, tmp_path)
    except ValueError as error:
        assert "must not" in str(error)
    else:
        raise AssertionError("source parent must be rejected as graph output")

    assert database.read_bytes() == original


def test_export_rejects_output_symlink_to_source_parent(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _fixture_db(database)
    output_link = tmp_path / "output-link"
    try:
        output_link.symlink_to(tmp_path, target_is_directory=True)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise

    try:
        export_texas_graph_dataset(database, output_link)
    except ValueError as error:
        assert "symlink" in str(error)
    else:
        raise AssertionError("symlinked graph output must be rejected")

    assert database.exists()


def test_export_refuses_any_existing_directory(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _fixture_db(database)
    target = tmp_path / "dataset"
    target.mkdir()
    (target / "stale.txt").write_text("old")
    original = database.read_bytes()

    try:
        export_texas_graph_dataset(database, target)
    except ValueError as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("existing directory must not be replaced")

    assert database.read_bytes() == original
    assert (target / "stale.txt").is_file()


def test_export_requires_tables(tmp_path: Path) -> None:
    database = tmp_path / "bare.duckdb"
    duckdb.connect(database).close()

    with pytest.raises(RuntimeError, match="requires tables"):
        export_texas_graph_dataset(database, tmp_path / "dataset")


def test_export_requires_at_least_one_bus(tmp_path: Path) -> None:
    database = tmp_path / "empty.duckdb"
    connect(database).close()

    with pytest.raises(RuntimeError, match="at least one bus"):
        export_texas_graph_dataset(database, tmp_path / "dataset")


def test_export_does_not_change_source_bytes(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _fixture_db(database)
    before = database.read_bytes()

    export_texas_graph_dataset(database, tmp_path / "dataset")

    assert database.read_bytes() == before


def test_export_rejects_non_activsg_sources(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _fixture_db(database)
    con = duckdb.connect(database)
    try:
        con.execute("UPDATE lines SET source_name = 'other'")
    finally:
        con.close()

    with pytest.raises(RuntimeError, match=r"lines\.source_name.*activsg2000"):
        export_texas_graph_dataset(database, tmp_path / "dataset")


def _wide_fixture_db(path: Path, *, reverse: bool) -> None:
    """A grid wide enough that an unordered scan really is unordered.

    With five buses, loads on every bus and generators on the odd ones, DuckDB's
    join returns the rows out of bus_id order, so the exporter's `ORDER BY` is
    the only thing making the output stable.
    """
    con = connect(path)
    try:
        con.execute(
            """
            INSERT INTO counties (
                county_fips, name, state, pop, geom_wkb, source_name, source_ref,
                source_version, source_retrieved_at, fixture_batch_id
            ) VALUES ('48001', 'Anderson', 'TX', 1, ?, 'activsg2000', 'test',
                      NULL, NULL, 'fixture')
            """,
            [b"geometry"],
        )
        order = (lambda values: list(reversed(values))) if reverse else list
        for bus_id in order(range(1, 6)):
            con.execute(
                """
                INSERT INTO buses (
                    bus_id, name, base_kv, lon, lat, county_fips, ba_code,
                    coord_source, zone, area, source_name, source_ref,
                    source_version, source_retrieved_at, fixture_batch_id
                ) VALUES (?, ?, 230, -95, 31, '48001', NULL, 'tamu_aux', 1, 1,
                          'activsg2000', 'test', NULL, NULL, 'fixture')
                """,
                [bus_id, f"bus-{bus_id}"],
            )
        for line_id in order(range(1, 5)):
            con.execute(
                """
                INSERT INTO lines (
                    line_id, from_bus, to_bus, circuit, base_kv, r_pu, x_pu,
                    rate_a_mw, length_km, geom_wkb, is_transformer, source_name,
                    source_ref, source_version, source_retrieved_at, fixture_batch_id
                ) VALUES (?, ?, ?, '1', 230, 0.01, 0.1, NULL, 0, NULL, ?,
                          'activsg2000', 'test', NULL, NULL, 'fixture')
                """,
                [line_id, line_id, line_id + 1, line_id % 2 == 0],
            )
            con.execute(
                """
                INSERT INTO synthetic_branch_electrical (
                    line_id, b_pu, tap_ratio, shift_deg, status
                ) VALUES (?, 0, 1, 0, 1)
                """,
                [line_id],
            )
        for bus_id in order(range(1, 6)):
            con.execute(
                """
                INSERT INTO synthetic_bus_electrical (
                    bus_id, bus_type, pd_mw, qd_mvar, gs_mw, bs_mvar, vm_pu,
                    va_deg, vmin_pu, vmax_pu
                ) VALUES (?, 1, 10, NULL, 0, 0, 1, 0, 0.9, 1.1)
                """,
                [bus_id],
            )
            con.execute(
                """
                INSERT INTO loads (
                    load_id, bus_id, p_mw_nominal, source_name, source_ref,
                    source_version, source_retrieved_at, fixture_batch_id
                ) VALUES (?, ?, ?, 'activsg2000', 'test', NULL, NULL, 'fixture')
                """,
                [bus_id, bus_id, float(bus_id)],
            )
            if bus_id % 2:
                con.execute(
                    """
                    INSERT INTO gens (
                        gen_id, bus_id, fuel, pmax_mw, eia_plant_id, source_unit_id,
                        source_name, source_ref, source_version, source_retrieved_at,
                        fixture_batch_id
                    ) VALUES (?, ?, 'wind', ?, NULL, ?, 'activsg2000', 'test',
                              NULL, NULL, 'fixture')
                    """,
                    [bus_id, bus_id, float(bus_id), f"unit-{bus_id}"],
                )
    finally:
        con.close()


def _export_in_subprocess(database: Path, target: Path) -> dict[str, object]:
    """Export through the CLI so the two exports share no interpreter state."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pipelines.graph_export",
            "--db",
            str(database),
            "--out",
            str(target),
        ],
        capture_output=True,
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _canonical_form(payload: bytes) -> bytes:
    """Re-serialize with sorted keys; canonical output must already equal this."""
    return (
        json.dumps(
            json.loads(payload),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def test_export_is_canonical_across_separate_processes(tmp_path: Path) -> None:
    """Two databases with rows inserted in opposite order, exported by two
    separate interpreters, produce byte-identical canonical files."""
    ascending = tmp_path / "ascending.duckdb"
    descending = tmp_path / "descending.duckdb"
    _wide_fixture_db(ascending, reverse=False)
    _wide_fixture_db(descending, reverse=True)

    ascending_out = tmp_path / "ascending-out"
    descending_out = tmp_path / "descending-out"
    ascending_manifest = _export_in_subprocess(ascending, ascending_out)
    descending_manifest = _export_in_subprocess(descending, descending_out)

    ascending_files = _files(ascending_out)
    assert ascending_files == _files(descending_out)
    assert ascending_manifest["dataset_sha256"] == descending_manifest["dataset_sha256"]

    for name, payload in sorted(ascending_files.items()):
        assert payload == _canonical_form(payload), f"{name} is not canonical JSON"

    nodes = json.loads(ascending_files["nodes.json"])
    edges = json.loads(ascending_files["edges.json"])
    assert [node["node_id"] for node in nodes] == [1, 2, 3, 4, 5]
    assert [edge["edge_id"] for edge in edges] == [1, 2, 3, 4]


def test_every_record_carries_the_topology_label(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _fixture_db(database)
    target = tmp_path / "dataset"
    export_texas_graph_dataset(database, target)

    nodes = json.loads((target / "nodes.json").read_text())
    edges = json.loads((target / "edges.json").read_text())
    assert nodes and edges
    for record in [*nodes, *edges]:
        assert record["topology_label"] == "synthetic (ACTIVSg2000)"


def test_export_opens_a_write_protected_source_database(tmp_path: Path) -> None:
    """A source this process cannot write is exportable only via a read-only open."""
    database = tmp_path / "grid.duckdb"
    _fixture_db(database)
    database.chmod(0o444)
    if os.access(database, os.W_OK):
        pytest.skip("this process can write a mode 0444 file (root or Windows)")

    manifest = export_texas_graph_dataset(database, tmp_path / "dataset")

    assert manifest["node_count"] == 3

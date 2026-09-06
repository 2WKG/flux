from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipelines.db import connect
from pipelines.graph_export import export_texas_graph_dataset


def _fixture_db(path: Path) -> None:
    con = connect(path)
    try:
        con.execute(
            "INSERT INTO counties VALUES ('48001', 'Anderson', 'TX', 1, ?, 'fixture', 'test', NULL, NULL, 'fixture')",
            [b"geometry"],
        )
        con.execute(
            "INSERT INTO buses VALUES (1, 'one', 230, -95, 31, '48001', NULL, 'fixture', 1, 1, 'fixture', 'test', NULL, NULL, 'fixture')"
        )
        con.execute(
            "INSERT INTO buses VALUES (2, 'two', 115, -96, 32, '48001', NULL, 'fixture', 1, 1, 'fixture', 'test', NULL, NULL, 'fixture')"
        )
        con.execute(
            "INSERT INTO lines VALUES (1, 1, 2, '1', 230, 0.01, 0.1, NULL, 0, NULL, TRUE, 'fixture', 'test', NULL, NULL, 'fixture')"
        )
        con.execute(
            "INSERT INTO synthetic_bus_electrical VALUES (1, 1, 10, NULL, 0, 0, 1, 0, 1.1, 0.9)"
        )
        con.execute("INSERT INTO synthetic_branch_electrical VALUES (1, 0, 1, 0, 1)")
    finally:
        con.close()


def _files(path: Path) -> dict[str, bytes]:
    return {item.name: item.read_bytes() for item in path.iterdir()}


def test_export_is_content_hashed_and_byte_identical(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _fixture_db(database)
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_manifest = export_texas_graph_dataset(database, first)
    second_manifest = export_texas_graph_dataset(database, second)

    assert _files(first) == _files(second)
    assert first_manifest == second_manifest
    assert (
        first_manifest["files"]["nodes.json"]
        == hashlib.sha256((first / "nodes.json").read_bytes()).hexdigest()
    )
    assert first_manifest["topology_label"] == "synthetic (ACTIVSg2000)"
    assert first_manifest["edge_counts"] == {
        "source_edge_type": {"transformer": 1},
        "solver_edge_type": {"impedance_branch": 1},
    }


def test_export_keeps_missing_values_explicit_and_persists_stats(
    tmp_path: Path,
) -> None:
    database = tmp_path / "grid.duckdb"
    _fixture_db(database)
    target = tmp_path / "dataset"
    export_texas_graph_dataset(database, target)

    nodes = json.loads((target / "nodes.json").read_text())
    edges = json.loads((target / "edges.json").read_text())
    stats = json.loads((target / "normalization.json").read_text())

    assert nodes[0]["features"]["qd_mvar"] is None
    assert nodes[0]["normalized_features"]["qd_mvar"] is None
    assert nodes[1]["features"]["pd_mw"] is None
    assert edges[0]["features"]["rate_a_mw"] is None
    assert edges[0]["normalized_features"]["rate_a_mw"] is None
    assert stats["node_features"]["pd_mw"] == {
        "count": 1,
        "mean": 10.0,
        "missing_count": 1,
        "std": 0.0,
        "zero_variance": True,
    }
    assert stats["edge_features"]["rate_a_mw"]["count"] == 0
    assert stats["edge_features"]["rate_a_mw"]["mean"] is None

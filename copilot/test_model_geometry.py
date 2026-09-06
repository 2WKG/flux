"""HTTP contract for the full synthetic model renderer projection."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings


def _database(path: Path) -> None:
    with duckdb.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE buses(bus_id BIGINT, lon DOUBLE, lat DOUBLE, coord_source TEXT)"
        )
        con.execute(
            "CREATE TABLE lines(line_id BIGINT, from_bus BIGINT, to_bus BIGINT, is_transformer BOOLEAN)"
        )
        con.execute("CREATE TABLE gens(gen_id BIGINT, bus_id BIGINT)")
        con.execute("CREATE TABLE loads(load_id BIGINT, bus_id BIGINT)")
        con.execute(
            "INSERT INTO buses VALUES (10, -97.0, 30.0, 'tamu_aux'), (20, -96.0, 31.0, 'tamu_aux')"
        )
        con.execute("INSERT INTO lines VALUES (1, 10, 20, false), (2, 20, 10, true)")
        con.execute("INSERT INTO gens VALUES (1, 10)")
        con.execute("INSERT INTO loads VALUES (1, 20)")


def test_model_returns_bus_and_branch_geometry_from_synthetic_db(
    tmp_path: Path,
) -> None:
    path = tmp_path / "grid.duckdb"
    _database(path)
    response = TestClient(create_app(Settings(duckdb_path=path))).get("/demo/model")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["data"]["topology"] == {
        "label": "synthetic (ACTIVSg2000)",
        "synthetic": True,
        "model_mode": "static_topology",
        "solver": "not_run",
    }
    assert body["data"]["counts"] == {
        "buses": 2,
        "branches": 2,
        "lines": 1,
        "impedance_branches": 1,
    }
    elements = {item["element_id"]: item for item in body["data"]["elements"]}
    assert elements["bus:10"]["geometry"] == {
        "type": "Point",
        "coordinates": [-97.0, 30.0],
    }
    assert elements["line:1"]["geometry"]["type"] == "LineString"
    assert elements["impedance:2"]["role"] == "impedance_branch"
    assert body["data"]["provenance"]["physical_inventory_equivalence"] is False


def test_model_missing_database_and_packaged_artifact_is_named_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    from copilot.routes import model_geometry

    monkeypatch.setattr(model_geometry, "_artifact_path", tmp_path / "missing.json.gz")
    response = TestClient(
        create_app(Settings(duckdb_path=tmp_path / "missing.duckdb"))
    ).get("/demo/model")
    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "synthetic_model_geometry",
        "reason": "unavailable",
    }


def test_model_rejects_more_than_64_requested_elements(tmp_path: Path) -> None:
    path = tmp_path / "grid.duckdb"
    _database(path)
    response = TestClient(create_app(Settings(duckdb_path=path))).get(
        "/demo/model", params=[("element_id", str(index)) for index in range(65)]
    )
    assert response.status_code == 422


def test_packaged_texas_topology_fallback_is_complete(tmp_path: Path) -> None:
    response = TestClient(
        create_app(Settings(duckdb_path=tmp_path / "missing.duckdb"))
    ).get("/demo/model")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["data"]["counts"] == {
        "buses": 2000,
        "branches": 3206,
        "lines": 2359,
        "impedance_branches": 847,
    }
    assert len(body["data"]["elements"]) == 6875
    assert body["data"]["topology"]["synthetic"] is True
    assert body["data"]["provenance"]["coordinate_source"] == "tamu_aux"


def test_model_rejects_tampered_packaged_topology(monkeypatch, tmp_path: Path) -> None:
    from copilot.routes import model_geometry

    artifact_path = tmp_path / "topology.json.gz"
    source_manifest = model_geometry._artifact_path.with_suffix(".manifest.json")
    artifact_path.write_bytes(model_geometry._artifact_path.read_bytes())
    manifest = json.loads(source_manifest.read_text())
    manifest["compressed_sha256"] = "0" * 64
    artifact_path.with_suffix(".manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(model_geometry, "_artifact_path", artifact_path)

    response = TestClient(
        create_app(Settings(duckdb_path=tmp_path / "missing.duckdb"))
    ).get("/demo/model")
    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "synthetic_model_geometry",
        "reason": "unavailable",
    }

"""Focused behavioral tests for static map-layer reads."""

from __future__ import annotations

from pathlib import Path

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copilot.api import install_error_handlers
from copilot.config import Settings
from copilot.routes.layers import router


def _client(database: Path) -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(duckdb_path=database)
    install_error_handlers(app)
    app.include_router(router)
    return TestClient(app)


def _fixture_database(path: Path) -> None:
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE buses (
            bus_id VARCHAR,
            name VARCHAR,
            base_kv DOUBLE,
            lon DOUBLE,
            lat DOUBLE,
            county_fips VARCHAR,
            ba_code VARCHAR
        )
        """
    )
    connection.execute(
        "INSERT INTO buses VALUES "
        "('bus-2', 'West', 230.0, -97.5, 30.1, '48453', 'ERCO'), "
        "('bus-1', 'East', 115.0, -96.1, 31.2, '48201', 'ERCO'), "
        "('unmapped', 'No geometry', 115.0, NULL, 31.2, '48201', 'ERCO')"
    )
    connection.close()


def test_buses_layer_declares_crs_attribute_units_and_sources(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get(
        "/layers/buses", headers={"X-Request-ID": "layer-1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["meta"]["request_id"] == "layer-1"
    assert body["meta"]["artifacts"] == [
        {
            "artifact_id": "buses",
            "artifact_version": "fixture-read-v1",
            "source_kind": "fixture",
        }
    ]
    data = body["data"]
    assert data["layer"] == "buses"
    assert data["crs"] == "EPSG:4326"
    assert data["attributes"]["kv"] == {"unit": "kV", "source": "buses.base_kv"}
    assert data["attributes"]["county_fips"] == {
        "unit": "FIPS code",
        "source": "buses.county_fips",
    }
    collection = data["feature_collection"]
    assert collection["crs"] == {"type": "name", "properties": {"name": "EPSG:4326"}}
    assert [feature["id"] for feature in collection["features"]] == ["bus-1", "bus-2"]
    assert collection["features"][0]["geometry"] == {
        "type": "Point",
        "coordinates": [-96.1, 31.2],
    }


def test_missing_buses_table_is_shared_unavailable_response(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    duckdb.connect(str(database)).close()

    response = _client(database).get("/layers/buses")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["data"] is None
    assert response.json()["error"] == {
        "code": "unavailable",
        "message": "The buses map-layer artifact is unavailable.",
        "retryable": True,
        "retry_after_s": 30,
        "details": {"artifact": "buses"},
    }


def test_layer_name_outside_the_allowlist_is_validation_error(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get("/layers/not-a-layer")

    assert response.status_code == 422
    assert response.json()["status"] == "error"
    assert response.json()["error"] == {
        "code": "invalid_input",
        "message": "Request parameters do not match the documented contract.",
        "retryable": False,
        "retry_after_s": None,
        "details": {"field": "path.layer_name"},
    }

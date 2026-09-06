"""Direct HTTP contract checks for the Minnesota SMR placement boundary."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copilot.api import install_error_handlers
from copilot.routes.minnesota_smr import router
from pipelines.minnesota_schema import ensure_minnesota_schema

ARTIFACT_ID = "mn:smr-route:evidence:v1"
SCENE_ID = f"{ARTIFACT_ID}:proposal-1"
PLACEMENT = {
    "scene_id": SCENE_ID,
    "source_artifact_id": ARTIFACT_ID,
    "longitude": -93.265,
    "latitude": 44.977,
    "crs": "EPSG:4326",
}


def _client(path: Path) -> TestClient:
    app = install_error_handlers(FastAPI())
    app.state.settings = SimpleNamespace(duckdb_path=path)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _evidence_database(path: Path) -> None:
    with duckdb.connect(str(path)) as con:
        ensure_minnesota_schema(con)
        con.execute(
            "INSERT INTO mn_artifact_manifests VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                ARTIFACT_ID,
                "smr_placement_evidence",
                "2.0.0-mn",
                "MN",
                "available",
                "not_applicable",
                "{}",
                "2026-09-06 00:00:00",
                "[]",
                "[]",
                "[]",
            ],
        )
        con.execute(
            "INSERT INTO mn_score_results VALUES (?,?,?,?,?,?)",
            [ARTIFACT_ID, "placement", 1.0, "count", "{}", "source_screened"],
        )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_validate_smr_returns_only_a_read_only_evidence_binding(tmp_path: Path) -> None:
    database = tmp_path / "evidence.duckdb"
    _evidence_database(database)
    before = _digest(database)

    response = _client(database).post("/minnesota/smr/validate", json=PLACEMENT)

    assert response.status_code == 200
    assert _digest(database) == before
    body = response.json()
    assert body["status"] == "valid"
    assert body["placement"]["render_mode"] == "placed"
    assert body["placement"]["material"]["status_label"] == "source_screened"
    assert body["placement"]["coordinates"] == {
        "longitude": -93.265,
        "latitude": 44.977,
        "crs": "EPSG:4326",
    }
    assert "no siting score, simulation, permitability" in body["limitations"][0]


def test_validate_smr_rejects_invalid_placement_context(tmp_path: Path) -> None:
    database = tmp_path / "evidence.duckdb"
    _evidence_database(database)

    response = _client(database).post(
        "/minnesota/smr/validate", json={**PLACEMENT, "latitude": 10.0}
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"reason": "invalid_placement"}


def test_validate_smr_returns_unknown_without_accepted_evidence(tmp_path: Path) -> None:
    database = tmp_path / "evidence.duckdb"
    _evidence_database(database)

    response = _client(database).post(
        "/minnesota/smr/validate",
        json={
            **PLACEMENT,
            "source_artifact_id": "mn:unknown:artifact:v1",
            "scene_id": "mn:unknown:artifact:v1:proposal-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unknown"
    assert body["placement"]["render_mode"] == "catalog_preview"
    assert "coordinates" not in body["placement"]


def test_validate_smr_reports_unavailable_when_evidence_cannot_open(
    tmp_path: Path,
) -> None:
    response = _client(tmp_path / "missing.duckdb").post(
        "/minnesota/smr/validate", json=PLACEMENT
    )

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "mn_artifact_manifests",
        "reason": "database_unavailable",
    }

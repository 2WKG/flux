"""HTTP proof for the exact persisted Minnesota aggregate artifact route."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copilot.api import install_error_handlers
from copilot.config import Settings
from copilot.routes.minnesota_aggregate import router
from pipelines.minnesota_aggregate_runtime import (
    FORMULA,
    METRIC_NAME,
    build_aggregate_runtime,
    load_aggregate_inputs,
)
from pipelines.minnesota_schema import ensure_minnesota_schema

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ID = "mn:model_result:665b5ac415912f3f"


def _client(database: Path) -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(duckdb_path=database)
    install_error_handlers(app)
    app.include_router(router)
    return TestClient(app)


def _source_db(path: Path) -> None:
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE retained_source (value TEXT)")
    finally:
        con.close()


def _runtime(database: Path) -> None:
    source = database.with_name("source.duckdb")
    _source_db(source)
    build_aggregate_runtime(source_db=source, output_db=database, repository_root=ROOT)


def _insert_matching_manifest(database: Path, artifact_id: str) -> None:
    inputs = load_aggregate_inputs(repository_root=ROOT)
    con = duckdb.connect(str(database))
    try:
        ensure_minnesota_schema(con)
        identity = {
            "artifact_kind": "model_result",
            "geography_id": "mn",
            "model_mode": "aggregate",
            "source_identity": "minnesota_aggregate_manifest_v1",
            "source_version": "v1",
            "content_sha256": inputs.manifest_sha256,
        }
        con.execute(
            "INSERT INTO mn_artifact_manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                artifact_id,
                "model_result",
                "2.0.0-mn",
                "mn",
                "available",
                "aggregate",
                json.dumps(identity),
                "2026-09-06 02:11:00",
                json.dumps(["fixture manifest only"]),
                json.dumps(["fixture manifest only"]),
                json.dumps([]),
            ],
        )
    finally:
        con.close()


def _details(response) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return response.json()["error"]["details"]


def test_aggregate_route_serves_the_real_verified_runtime(tmp_path: Path) -> None:
    database = tmp_path / "aggregate.duckdb"
    _runtime(database)

    response = _client(database).get("/minnesota/aggregate")

    assert response.status_code == 200
    body = response.json()
    inputs = load_aggregate_inputs(repository_root=ROOT)
    assert body["artifact_id"] == ARTIFACT_ID
    assert body["artifact_contract_version"] == "2.0.0-mn"
    assert body["artifact_identity"] == {
        "artifact_id": ARTIFACT_ID,
        "artifact_kind": "model_result",
        "geography_id": "mn",
        "model_mode": "aggregate",
        "source_identity": "minnesota_aggregate_manifest_v1",
        "source_version": "v1",
        "content_sha256": inputs.manifest_sha256,
    }
    assert body["availability"] == "available"
    assert body["model_mode"] == "aggregate"
    assert body["aggregate_manifest"] == {
        key: inputs.manifest[key]
        for key in (
            "format",
            "model_mode",
            "allocation_status",
            "allocation_limit",
            "sources",
        )
    }
    assert body["stress_metric"]["metric_name"] == METRIC_NAME
    assert body["stress_metric"]["metric_value"] == inputs.peak_demand_mw
    assert body["stress_metric"]["unit"] == "MW"
    assert body["stress_metric"]["formula"] == FORMULA
    assert len(body["provenance"]) == 4
    assert [row["content_sha256"] for row in body["provenance"]] == [
        item.content_sha256 for item in inputs.approved
    ]
    assert body["base_mva"] is None
    assert body["solver_version"] is None
    assert body["converter_version"] is None


def test_aggregate_route_refuses_missing_or_ambiguous_identity(tmp_path: Path) -> None:
    missing_database = tmp_path / "missing.duckdb"
    _source_db(missing_database)
    missing = _client(missing_database).get("/minnesota/aggregate")
    assert missing.status_code == 503
    assert _details(missing) == {
        "artifact": "mn_artifact_manifests",
        "reason": "missing",
    }

    ambiguous_database = tmp_path / "ambiguous.duckdb"
    _runtime(ambiguous_database)
    _insert_matching_manifest(ambiguous_database, "mn:model_result:1111111111111111")
    ambiguous = _client(ambiguous_database).get("/minnesota/aggregate")
    assert ambiguous.status_code == 503
    assert _details(ambiguous) == {
        "artifact": "mn_artifact_manifests",
        "reason": "ambiguous_identity",
    }


def test_aggregate_route_refuses_incomplete_persisted_artifact(tmp_path: Path) -> None:
    database = tmp_path / "incomplete.duckdb"
    _source_db(database)
    _insert_matching_manifest(database, ARTIFACT_ID)

    response = _client(database).get("/minnesota/aggregate")

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "mn_artifact_manifests",
        "reason": "invalid_persisted_artifact",
    }


def test_aggregate_route_refuses_a_coherent_tampered_metric(tmp_path: Path) -> None:
    database = tmp_path / "tampered.duckdb"
    _runtime(database)
    con = duckdb.connect(str(database))
    try:
        con.execute("UPDATE mn_model_results SET metric_value=1.0, formula='tampered'")
        con.execute(
            "UPDATE mn_score_results SET score_value=1.0, metric='tampered', score_unit='MW'"
        )
    finally:
        con.close()

    response = _client(database).get("/minnesota/aggregate")

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "mn_artifact_manifests",
        "reason": "invalid_persisted_artifact",
    }

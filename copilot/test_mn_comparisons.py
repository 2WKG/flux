from __future__ import annotations

import json
from pathlib import Path

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copilot.api import install_error_handlers
from copilot.config import Settings
from copilot.routes.mn_comparisons import router
from pipelines.minnesota_schema import ensure_minnesota_schema


def _client(path: Path) -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(duckdb_path=path)
    install_error_handlers(app)
    app.include_router(router)
    return TestClient(app)


def _add_context(con: duckdb.DuckDBPyConnection, context: str, value: float) -> None:
    artifact = f"artifact:{context}"
    identity = json.dumps(
        {
            "source_identity": {
                "context_id": context,
                "label": context,
                "highlight_ids": [f"scene:{context}"],
            }
        }
    )
    con.execute(
        "INSERT INTO mn_artifact_manifests VALUES (?, 'model', '2.0.0-mn', 'mn', 'available', 'aggregate', ?, CURRENT_TIMESTAMP, '[]', '[\"aggregate only\"]', '[]')",
        [artifact, identity],
    )
    con.execute(
        "INSERT INTO mn_artifact_provenance VALUES (?, 0, 'fixture:mn', 'fixture://mn', 'v1', CURRENT_TIMESTAMP, 'test', 'record', ?, FALSE)",
        [artifact, "0" * 64],
    )
    con.execute(
        "INSERT INTO mn_model_results VALUES (?, 'aggregate', 'v1', ?, ?, 'validated', 'customers_at_risk', ?, 'customers', 'persisted aggregate', NULL, NULL, NULL)",
        [artifact, context, "1" * 64, value],
    )


def test_aggregate_comparison_derives_signed_delta_from_two_persisted_results(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mn.duckdb"
    con = duckdb.connect(str(path))
    ensure_minnesota_schema(con)
    _add_context(con, "mn:baseline:v1", 12)
    _add_context(con, "mn:candidate:v1", 9)
    con.close()
    response = _client(path).post(
        "/mn/comparisons",
        json={
            "baseline_context_id": "mn:baseline:v1",
            "candidate_context_id": "mn:candidate:v1",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["metrics"][0]["delta_signed"] == -3
    assert body["metrics"][0]["unit"] == "customers"
    assert body["highlight_ids"] == ["scene:mn:baseline:v1", "scene:mn:candidate:v1"]


def test_missing_context_is_explicitly_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "mn.duckdb"
    con = duckdb.connect(str(path))
    ensure_minnesota_schema(con)
    con.close()
    response = _client(path).post(
        "/mn/comparisons",
        json={"baseline_context_id": "a", "candidate_context_id": "b"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "no_qualified_result"

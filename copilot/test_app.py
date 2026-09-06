"""Behavioral tests for the fixture-safe app scaffold and health route."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from copilot.api import API_VERSION
from copilot.app import create_app
from copilot.config import Settings


def _fixture_database(path: Path, *, with_corpus: bool = True) -> None:
    connection = duckdb.connect(str(path))
    connection.execute("CREATE TABLE fixture_marker (id INTEGER)")
    if with_corpus:
        connection.execute("CREATE TABLE corpus_chunks (embedding DOUBLE[])")
        connection.execute("INSERT INTO corpus_chunks VALUES ([0.5])")
    connection.close()


def test_settings_leave_the_model_unconfigured_when_copilot_model_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COPILOT_MODEL", raising=False)

    assert Settings(_env_file=None).copilot_model is None


def test_health_opens_a_fixture_database_without_claiming_model_availability(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)
    app = create_app(Settings(duckdb_path=database))

    response = TestClient(app).get("/health", headers={"X-Request-ID": "health-1"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "ok": True,
        "duckdb_path": str(database),
        "tables": ["corpus_chunks", "fixture_marker"],
        "corpus_chunks": 1,
        "dense": True,
        "model": {
            "status": "not_configured",
            "message": "No model provider credential is configured.",
        },
    }
    assert response.headers["X-Request-ID"] == "health-1"
    assert response.headers["X-Flux-Api-Version"] == API_VERSION
    assert "X-Flux-Artifact" not in response.headers


def test_health_reports_a_sparse_fixture_without_claiming_dense_retrieval(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database, with_corpus=False)
    app = create_app(Settings(duckdb_path=database))

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "duckdb_path": str(database),
        "tables": ["fixture_marker"],
        "corpus_chunks": 0,
        "dense": False,
        "model": {
            "status": "not_configured",
            "message": "No model provider credential is configured.",
        },
    }


def test_health_returns_the_shared_unavailable_envelope_for_a_missing_fixture(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(duckdb_path=tmp_path / "missing.duckdb"))

    response = TestClient(app).get("/health", headers={"X-Request-ID": "health-2"})

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["data"] is None
    assert response.json()["error"] == {
        "code": "unavailable",
        "message": "The configured database artifact is unavailable.",
        "retryable": True,
        "retry_after_s": 30,
        "details": {"artifact": "database", "model": "not_configured"},
    }
    assert not (tmp_path / "missing.duckdb").exists()
    assert response.headers["X-Request-ID"] == "health-2"
    assert response.headers["X-Flux-Api-Version"] == API_VERSION
    assert "X-Flux-Artifact" not in response.headers


def test_cors_exposes_response_metadata_headers(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)
    app = create_app(Settings(duckdb_path=database))

    response = TestClient(app).get(
        "/health", headers={"Origin": "http://localhost:5173"}
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Expose-Headers"] == (
        "X-Request-ID, X-Flux-Api-Version, X-Flux-Artifact"
    )


def test_health_does_not_treat_a_configured_credential_as_model_availability(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)
    app = create_app(
        Settings(
            duckdb_path=database,
            copilot_model="claude-sonnet-5",
            anthropic_api_key="configured-but-unchecked",
        )
    )

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["model"] == {
        "status": "not_verified",
        "message": "Model availability is not verified by this local health check.",
    }

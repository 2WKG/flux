"""Behavioral tests for the fixture-safe app scaffold and health route."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings


def _fixture_database(path: Path) -> None:
    connection = duckdb.connect(str(path))
    connection.execute("CREATE TABLE fixture_marker (id INTEGER)")
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
        "database": {
            "status": "available",
            "message": "The configured database artifact opened read-only.",
        },
        "model": {
            "status": "not_configured",
            "message": "No model provider credential is configured.",
        },
    }
    assert response.headers["X-Request-ID"] == "health-1"


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
    assert response.headers["X-Request-ID"] == "health-2"


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
    assert response.json()["model"] == {
        "status": "not_verified",
        "message": "Model availability is not verified by this local health check.",
    }

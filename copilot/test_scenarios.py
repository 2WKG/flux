"""Behavioral tests for DuckDB-backed scenario catalog and detail routes."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings


def _fixture_database(path: Path) -> None:
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE scenarios (
            scenario_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            ts_start TIMESTAMP NOT NULL,
            ts_end TIMESTAMP NOT NULL,
            source_name TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            source_version TEXT,
            source_retrieved_at TIMESTAMP,
            fixture_batch_id TEXT NOT NULL
        )
        """
    )
    connection.executemany(
        """
        INSERT INTO scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "fixture_b",
                "Second fixture",
                "synthetic",
                "2026-01-02T00:00:00",
                "2026-01-02T03:00:00",
                "fixture:flux-demo",
                "pipelines/fixtures/inputs/scenarios.json",
                "1.0.0",
                "2026-01-01T00:00:00",
                "fixture:flux-demo@1.0.0",
            ),
            (
                "fixture_a",
                "First fixture",
                "synthetic",
                "2026-01-01T00:00:00",
                "2026-01-01T06:00:00",
                "fixture:flux-demo",
                "pipelines/fixtures/inputs/scenarios.json",
                "1.0.0",
                "2026-01-01T00:00:00",
                "fixture:flux-demo@1.0.0",
            ),
        ],
    )
    connection.close()


def _client(database: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=database)))


def test_catalog_returns_deterministic_identity_assumptions_and_provenance(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get(
        "/scenarios", headers={"X-Request-ID": "scenarios-1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert [item["scenario_id"] for item in body["data"]["scenarios"]] == [
        "fixture_a",
        "fixture_b",
    ]
    scenario = body["data"]["scenarios"][0]
    assert scenario["name"] == "First fixture"
    assert scenario["assumptions"] == {
        "kind": "synthetic",
        "ts_start": "2026-01-01T00:00:00Z",
        "ts_end": "2026-01-01T06:00:00Z",
        "duration_hours": 6,
    }
    assert scenario["provenance"] == {
        "source_name": "fixture:flux-demo",
        "source_ref": "pipelines/fixtures/inputs/scenarios.json",
        "source_version": "1.0.0",
        "source_retrieved_at": "2026-01-01T00:00:00Z",
        "fixture_batch_id": "fixture:flux-demo@1.0.0",
    }
    assert body["meta"]["request_id"] == "scenarios-1"
    assert body["meta"]["artifacts"][0] == {
        "artifact_id": "scenario:fixture_a",
        "artifact_version": "1.0.0",
        "source_kind": "fixture",
    }


def test_detail_returns_the_requested_persisted_scenario(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get("/scenarios/fixture_b")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["scenario_id"] == "fixture_b"
    assert body["data"]["assumptions"]["duration_hours"] == 3
    assert body["meta"]["artifacts"] == [
        {
            "artifact_id": "scenario:fixture_b",
            "artifact_version": "1.0.0",
            "source_kind": "fixture",
        }
    ]


def test_detail_reports_not_found_for_an_absent_scenario_row(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get("/scenarios/unknown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["details"] == {"scenario_id": "unknown"}


@pytest.mark.parametrize(
    "scenario_id",
    ["invalid%20identifier", "a" * 65],
)
def test_detail_rejects_malformed_or_out_of_bounds_scenario_identifier(
    tmp_path: Path, scenario_id: str
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get(f"/scenarios/{scenario_id}")

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "invalid_input",
        "message": "Request parameters do not match the documented contract.",
        "retryable": False,
        "retry_after_s": None,
        "details": {"field": "path.scenario_id"},
    }


def test_catalog_returns_an_empty_selection_when_the_artifact_has_no_rows(
    tmp_path: Path,
) -> None:
    database = tmp_path / "empty.duckdb"
    _fixture_database(database)
    connection = duckdb.connect(str(database))
    connection.execute("DELETE FROM scenarios")
    connection.close()

    response = _client(database).get("/scenarios")

    assert response.status_code == 200
    assert response.json()["data"] == {"scenarios": []}


def test_routes_return_shared_unavailable_envelope_when_artifact_is_missing(
    tmp_path: Path,
) -> None:
    response = _client(tmp_path / "missing.duckdb").get("/scenarios")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["data"] is None
    assert body["error"] == {
        "code": "unavailable",
        "message": "The configured scenario artifact is unavailable.",
        "retryable": True,
        "retry_after_s": 30,
        "details": {"artifact": "scenarios"},
    }


def test_routes_return_shared_unavailable_envelope_when_scenario_table_is_missing(
    tmp_path: Path,
) -> None:
    database = tmp_path / "no-scenarios.duckdb"
    duckdb.connect(str(database)).close()

    response = _client(database).get("/scenarios")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "unavailable"
    assert response.json()["error"]["details"] == {"artifact": "scenarios"}

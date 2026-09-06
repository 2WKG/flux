"""HTTP coverage for qualified prediction and persisted cascade reads."""

from __future__ import annotations

from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from pipelines.minnesota_schema import SCHEMA_VERSION, ensure_minnesota_schema


def _client(path: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=path)))


def _prediction_database(
    path: Path,
    *,
    qualifications: tuple[bool, ...],
) -> None:
    """Build the persisted tables queried by the read route, without a write path."""
    con = duckdb.connect(str(path))
    try:
        con.execute(
            """CREATE TABLE outage_predictions (
                scenario_id TEXT, county_fips TEXT, ts TIMESTAMP, p_out DOUBLE,
                customers_at_risk BIGINT, driver TEXT
            )"""
        )
        con.execute(
            """CREATE TABLE prediction_provenance (
                scenario_id TEXT, county_fips TEXT, ts TIMESTAMP, model_kind TEXT,
                model_version TEXT, artifact_sha256 TEXT, split_id TEXT,
                feature_set_version TEXT, evaluation_sha256 TEXT, rule_id TEXT,
                rule_version TEXT, persisted_at TIMESTAMP
            )"""
        )
        con.execute(
            """CREATE TABLE evaluation_artifacts (
                evaluation_sha256 TEXT, status TEXT, qualified BOOLEAN,
                qualification_reason TEXT
            )"""
        )
        for index, qualified in enumerate(qualifications):
            evaluation = f"evaluation-{index}"
            con.execute(
                "INSERT INTO outage_predictions VALUES (?, ?, ?, ?, ?, ?)",
                [
                    "mn_winter_2023_snow",
                    f"270{index:02}",
                    f"2023-01-0{index + 1} 00:00:00",
                    0.4 + index / 10,
                    100 + index,
                    "ice",
                ],
            )
            con.execute(
                "INSERT INTO prediction_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    "mn_winter_2023_snow",
                    f"270{index:02}",
                    f"2023-01-0{index + 1} 00:00:00",
                    "lightgbm",
                    "model-v1",
                    "a" * 64,
                    "holdout-v1",
                    "features-v1",
                    evaluation,
                    None,
                    None,
                    "2026-09-05 00:00:00",
                ],
            )
            con.execute(
                "INSERT INTO evaluation_artifacts VALUES (?, ?, ?, ?)",
                [
                    evaluation,
                    "ready",
                    qualified,
                    None if qualified else "brier_above_acceptance",
                ],
            )
    finally:
        con.close()


def _cascade_database(path: Path, *, model_mode: str | None = "topology") -> None:
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE cascade_runs (run_id TEXT, scenario_id TEXT)")
        if model_mode is not None:
            ensure_minnesota_schema(con)
            con.execute(
                "INSERT INTO mn_artifact_manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    "mn:model:storm-run-1",
                    "model_result",
                    SCHEMA_VERSION,
                    "mn",
                    "available",
                    model_mode,
                    "{}",
                    "2026-09-05 00:00:00",
                    "[]",
                    '["Fixture topology evidence only."]',
                    "[]",
                ],
            )
            con.execute(
                "INSERT INTO mn_artifact_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    "mn:model:storm-run-1",
                    0,
                    "fixture:topology",
                    "fixtures/topology.json",
                    "v1",
                    "2026-09-05 00:00:00",
                    "test fixture",
                    "storm-run-1",
                    "b" * 64,
                    False,
                ],
            )
            con.execute(
                "INSERT INTO mn_model_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    "mn:model:storm-run-1",
                    "fixture-cascade",
                    "v1",
                    "mn-storm-run-1",
                    "a" * 64,
                    "validated",
                    "lost_load_mw",
                    1.0,
                    "MW",
                    None if model_mode == "topology" else "regional sum",
                    100.0 if model_mode == "topology" else None,
                    "pandapower" if model_mode == "topology" else None,
                    "fixture-converter" if model_mode == "topology" else None,
                ],
            )
        con.execute(
            "INSERT INTO cascade_runs VALUES ('mn-storm-run-1', 'mn_winter_2023_snow')"
        )
    finally:
        con.close()


def test_qualified_persisted_prediction_is_returned(tmp_path: Path) -> None:
    database = tmp_path / "qualified.duckdb"
    _prediction_database(database, qualifications=(True, False))

    response = _client(database).get(
        "/predictions", params={"scenario_id": "mn_winter_2023_snow"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert len(body["predictions"]) == 1
    assert body["predictions"][0] == {
        "scenario_id": "mn_winter_2023_snow",
        "county_fips": "27000",
        "ts": "2023-01-01T00:00:00Z",
        "p_out": 0.4,
        "customers_at_risk": 100,
        "driver": "ice",
        "model_kind": "lightgbm",
        "model_version": "model-v1",
        "artifact_sha256": "a" * 64,
        "split_id": "holdout-v1",
        "feature_set_version": "features-v1",
        "evaluation_sha256": "evaluation-0",
        "rule_id": None,
        "rule_version": None,
        "persisted_at": "2026-09-05T00:00:00Z",
        "evaluation_status": "ready",
        "qualified": True,
        "qualification_reason": None,
    }


def test_unqualified_prediction_is_not_returned_as_success(tmp_path: Path) -> None:
    database = tmp_path / "unqualified.duckdb"
    _prediction_database(database, qualifications=(False,))

    response = _client(database).get("/predictions")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["error"]["details"] == {
        "artifact": "outage_predictions",
        "reason": "no_qualified_prediction",
    }


def test_persisted_cascade_is_returned(tmp_path: Path) -> None:
    database = tmp_path / "cascade.duckdb"
    _cascade_database(database)

    response = _client(database).get(
        "/cascade", params={"scenario_id": "mn_winter_2023_snow"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "available",
        "run_id": "mn-storm-run-1",
        "scenario_id": "mn_winter_2023_snow",
        "artifact_id": "mn:model:storm-run-1",
        "model_mode": "topology",
        "provenance": [
            {
                "source_name": "fixture:topology",
                "source_ref": "fixtures/topology.json",
                "source_version": "v1",
                "retrieved_at": "2026-09-05T00:00:00Z",
                "license_or_terms": "test fixture",
                "source_record_id": "storm-run-1",
                "content_sha256": "b" * 64,
                "is_derived": False,
            }
        ],
        "limitations": ["Fixture topology evidence only."],
    }


def test_prediction_missing_artifact_is_unavailable(tmp_path: Path) -> None:
    response = _client(tmp_path / "missing.duckdb").get("/predictions")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_bare_cascade_row_is_not_a_qualified_topology_artifact(tmp_path: Path) -> None:
    database = tmp_path / "bare-cascade.duckdb"
    _cascade_database(database, model_mode=None)

    response = _client(database).get(
        "/cascade", params={"scenario_id": "mn_winter_2023_snow"}
    )

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_aggregate_model_cannot_be_relabelled_as_a_cascade(tmp_path: Path) -> None:
    database = tmp_path / "aggregate-cascade.duckdb"
    _cascade_database(database, model_mode="aggregate")

    response = _client(database).get(
        "/cascade", params={"scenario_id": "mn_winter_2023_snow"}
    )

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "cascade_runs",
        "reason": "topology_cascade_unsupported_or_absent",
    }


def test_prediction_invalid_limit_is_rejected(tmp_path: Path) -> None:
    response = _client(tmp_path / "missing.duckdb").get(
        "/predictions", params={"limit": 0}
    )

    assert response.status_code == 422


def test_prediction_invalid_model_kind_is_rejected(tmp_path: Path) -> None:
    response = _client(tmp_path / "missing.duckdb").get(
        "/predictions", params={"model_kind": "unsupported"}
    )

    assert response.status_code == 422

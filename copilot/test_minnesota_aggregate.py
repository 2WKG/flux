"""HTTP proof for the persisted Minnesota aggregate artifact route."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from copilot.api import install_error_handlers
from copilot.config import Settings
from copilot.routes.minnesota_aggregate import router
from pipelines.minnesota_schema import ensure_minnesota_schema

ARTIFACT_ID = "mn:model_result:665b5ac415912f3f"
SOURCE_IDENTITY = "minnesota_aggregate_manifest_v1"
METRIC = "miso_ba_peak_demand_mw"
SHA256 = "f287a1dfbafddff8bd9f0ec989d488ad6743609280b19338eca048c3d5858e05"


def _client(database: Path) -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(duckdb_path=database)
    install_error_handlers(app)
    app.include_router(router)
    return TestClient(app)


def _components() -> dict[str, object]:
    return {
        "artifact_version": "v1",
        "aggregate_manifest": {
            "format": "flux-minnesota-aggregate-v1",
            "model_mode": "aggregate",
            "allocation_status": "unavailable",
            "allocation_limit": "No reviewed BA-to-service-area allocation crosswalk is available.",
            "sources": [
                {"id": "tiger_counties_2024", "url": "https://example.invalid/tiger"},
                {
                    "id": "mngeo_service_areas_2026",
                    "url": "https://example.invalid/mngeo",
                },
                {"id": "eia860_2024", "url": "https://example.invalid/eia860"},
                {
                    "id": "eia930_balance_2024_h1",
                    "url": "https://example.invalid/eia930",
                    "file_sha256": {"miso_ba_context_2024_h1.csv": SHA256},
                },
            ],
        },
        "stress_context": {
            "source_label": "MISO balancing authority (not Minnesota demand)",
            "time_basis": "UTC end of hour",
            "window_start_utc": "2024-01-01T06:00:00Z",
            "window_end_utc": "2024-07-01T05:00:00Z",
            "window_peak_demand_mw": 109244.0,
            "window_peak_hour_utc": "2024-06-24T23:00:00Z",
            "scored_hours": 4368,
            "min_index": 0.1,
            "mean_index": 0.654879,
            "p95_index": 0.9,
        },
        "prohibited_claims": [
            "Minnesota demand allocation",
            "county or service-area load allocation",
            "facility dispatch",
        ],
    }


def _insert_artifact(
    database: Path,
    *,
    artifact_id: str = ARTIFACT_ID,
    source_identity: str = SOURCE_IDENTITY,
    include_model_and_score: bool = True,
) -> None:
    con = duckdb.connect(str(database))
    try:
        ensure_minnesota_schema(con)
        con.execute(
            "INSERT INTO mn_artifact_manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                artifact_id,
                "model_result",
                "2.0.0-mn",
                "mn",
                "available",
                "aggregate",
                json.dumps(
                    {
                        "artifact_kind": "model_result",
                        "geography_id": "mn",
                        "model_mode": "aggregate",
                        "source_identity": source_identity,
                        "source_version": "v1",
                        "content_sha256": SHA256,
                    }
                ),
                "2026-09-06 00:00:00",
                json.dumps(["The metric is aggregate only."]),
                json.dumps(["It is not a transmission-flow or outage simulation."]),
                json.dumps(["mn:source_manifest:0000000000000000"]),
            ],
        )
        for ordinal, source_name in enumerate(
            ("gate0-a", "gate0-b", "gate0-c", "gate0-d")
        ):
            con.execute(
                "INSERT INTO mn_artifact_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    artifact_id,
                    ordinal,
                    source_name,
                    f"fixture://{source_name}",
                    "v1",
                    "2026-09-06 00:00:00",
                    "fixture",
                    source_name,
                    SHA256,
                    ordinal == 3,
                ],
            )
        if include_model_and_score:
            con.execute(
                "INSERT INTO mn_model_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    artifact_id,
                    "minnesota_aggregate_peak_context",
                    "v1",
                    "aggregate-runtime-v1:f287a1dfbafddff",
                    SHA256,
                    "validated",
                    METRIC,
                    109244.0,
                    "MW",
                    "MAX(`Demand (MW)`) across the committed EIA-930 MISO balancing-authority context rows for 2024 H1; this is MISO BA context, not Minnesota demand.",
                    None,
                    None,
                    None,
                ],
            )
            con.execute(
                "INSERT INTO mn_score_results VALUES (?, ?, ?, ?, ?, ?)",
                [
                    artifact_id,
                    METRIC,
                    109244.0,
                    "MW",
                    json.dumps(_components()),
                    "source_screened",
                ],
            )
    finally:
        con.close()


def _details(response) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return response.json()["error"]["details"]


def test_aggregate_route_serves_the_persisted_aggregate_artifact(
    tmp_path: Path,
) -> None:
    database = tmp_path / "aggregate.duckdb"
    _insert_artifact(database)

    response = _client(database).get("/minnesota/aggregate")

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_id"] == ARTIFACT_ID
    assert body["artifact_contract_version"] == "2.0.0-mn"
    assert body["artifact_identity"] == {
        "artifact_id": ARTIFACT_ID,
        "artifact_kind": "model_result",
        "geography_id": "mn",
        "model_mode": "aggregate",
        "source_identity": SOURCE_IDENTITY,
        "source_version": "v1",
        "content_sha256": SHA256,
    }
    assert body["availability"] == "available"
    assert body["model_mode"] == "aggregate"
    assert body["aggregate_manifest"]["allocation_status"] == "unavailable"
    assert body["stress_metric"] == {
        "metric_name": METRIC,
        "metric_value": 109244.0,
        "unit": "MW",
        "formula": "MAX(`Demand (MW)`) across the committed EIA-930 MISO balancing-authority context rows for 2024 H1; this is MISO BA context, not Minnesota demand.",
        **_components()["stress_context"],
    }
    assert len(body["provenance"]) == 4
    assert body["limitations"] == [
        "It is not a transmission-flow or outage simulation."
    ]
    assert body["prohibited_claims"] == _components()["prohibited_claims"]
    assert body["base_mva"] is None
    assert body["solver_version"] is None
    assert body["converter_version"] is None


def test_aggregate_route_refuses_missing_or_ambiguous_identity(tmp_path: Path) -> None:
    missing_database = tmp_path / "missing.duckdb"
    _insert_artifact(missing_database, source_identity="other_aggregate")
    missing = _client(missing_database).get("/minnesota/aggregate")
    assert missing.status_code == 503
    assert _details(missing) == {
        "artifact": "mn_artifact_manifests",
        "reason": "missing_identity",
    }

    ambiguous_database = tmp_path / "ambiguous.duckdb"
    _insert_artifact(ambiguous_database)
    _insert_artifact(
        ambiguous_database,
        artifact_id="mn:model_result:1111111111111111",
        include_model_and_score=False,
    )
    ambiguous = _client(ambiguous_database).get("/minnesota/aggregate")
    assert ambiguous.status_code == 503
    assert _details(ambiguous) == {
        "artifact": "mn_artifact_manifests",
        "reason": "ambiguous_identity",
    }


def test_aggregate_route_refuses_incomplete_persisted_artifact(tmp_path: Path) -> None:
    database = tmp_path / "incomplete.duckdb"
    _insert_artifact(database, include_model_and_score=False)

    response = _client(database).get("/minnesota/aggregate")

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "mn_artifact_manifests",
        "reason": "invalid_persisted_artifact",
    }


def test_aggregate_route_refuses_a_tampered_metric_or_identity(tmp_path: Path) -> None:
    metric_database = tmp_path / "tampered-metric.duckdb"
    _insert_artifact(metric_database)
    con = duckdb.connect(str(metric_database))
    try:
        con.execute("UPDATE mn_score_results SET score_value=1.0")
    finally:
        con.close()
    metric_response = _client(metric_database).get("/minnesota/aggregate")
    assert metric_response.status_code == 503
    assert _details(metric_response) == {
        "artifact": "mn_artifact_manifests",
        "reason": "invalid_persisted_artifact",
    }

    identity_database = tmp_path / "tampered-identity.duckdb"
    _insert_artifact(identity_database)
    con = duckdb.connect(str(identity_database))
    try:
        con.execute("UPDATE mn_model_results SET input_manifest_sha256=?", ["b" * 64])
    finally:
        con.close()
    identity_response = _client(identity_database).get("/minnesota/aggregate")
    assert identity_response.status_code == 503
    assert _details(identity_response) == {
        "artifact": "mn_artifact_manifests",
        "reason": "invalid_persisted_artifact",
    }

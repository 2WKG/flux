"""Contract tests for the versioned envelope and failure semantics."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from copilot.api import (
    API_VERSION,
    ArtifactRef,
    InvalidInputError,
    NotFoundError,
    SuccessEnvelope,
    UnavailableError,
    install_error_handlers,
    safe_details,
    success,
)
from copilot.api.errors import INTERNAL_ERROR_MESSAGE, REQUEST_ID_HEADER

ARTIFACT = ArtifactRef(
    artifact_id="cascade_runs",
    artifact_version="uri_2021-s0-ab12cd34",
    source_kind="simulated",
)


class Scenario(BaseModel):
    scenario_id: str
    hours: int


@pytest.fixture
def client() -> TestClient:
    app = install_error_handlers(FastAPI())

    @app.get("/ok")
    def _ok() -> SuccessEnvelope[Scenario]:
        return success(
            Scenario(scenario_id="uri_2021", hours=168),
            request_id="req-ok",
            artifacts=(ARTIFACT,),
        )

    @app.get("/unavailable")
    def _unavailable() -> SuccessEnvelope[Scenario]:
        raise UnavailableError(
            "Cascade artifacts for scenario 'uri_2021' have not been built.",
            details={"scenario_id": "uri_2021"},
        )

    @app.get("/missing")
    def _missing() -> SuccessEnvelope[Scenario]:
        raise NotFoundError("Unknown scenario 'nope'.")

    @app.get("/invalid")
    def _invalid() -> SuccessEnvelope[Scenario]:
        raise InvalidInputError("hour must be between 0 and 167.")

    @app.get("/boom")
    def _boom() -> SuccessEnvelope[Scenario]:
        raise RuntimeError(
            "IO Error: could not open /secrets/grid.duckdb (token=abc123)"
        )

    return TestClient(app, raise_server_exceptions=False)


def test_success_payload_carries_version_request_id_and_provenance(client: TestClient) -> None:
    body = client.get("/ok").json()

    assert body["status"] == "ok"
    assert body["data"] == {"scenario_id": "uri_2021", "hours": 168}
    assert body["meta"]["api_version"] == API_VERSION
    assert body["meta"]["request_id"] == "req-ok"
    assert body["meta"]["artifacts"][0]["artifact_id"] == "cascade_runs"
    assert body["meta"]["partial"] is False
    assert body["meta"]["generated_at"].endswith("Z") or "+00:00" in body["meta"]["generated_at"]


@pytest.mark.parametrize(
    ("path", "http_status", "status", "code", "retryable"),
    [
        ("/unavailable", 503, "unavailable", "unavailable", True),
        ("/missing", 404, "error", "not_found", False),
        ("/invalid", 422, "error", "invalid_input", False),
        ("/boom", 500, "error", "internal_error", False),
    ],
)
def test_failure_classes_map_to_the_documented_shape(
    client: TestClient,
    path: str,
    http_status: int,
    status: str,
    code: str,
    retryable: bool,
) -> None:
    response = client.get(path)
    body = response.json()

    assert response.status_code == http_status
    assert body["status"] == status
    assert body["data"] is None
    assert body["error"]["code"] == code
    assert body["error"]["retryable"] is retryable
    assert body["error"]["message"]
    assert body["meta"]["api_version"] == API_VERSION
    assert body["meta"]["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_unavailable_is_never_an_empty_success(client: TestClient) -> None:
    body = client.get("/unavailable").json()

    assert body["status"] != "ok"
    assert "data" in body and body["data"] is None
    assert body["error"]["retry_after_s"] == 30
    assert client.get("/unavailable").headers["Retry-After"] == "30"
    assert body["error"]["details"] == {"scenario_id": "uri_2021"}


def test_unexpected_failure_leaks_no_duckdb_text_or_secret(client: TestClient) -> None:
    raw = client.get("/boom").text

    assert INTERNAL_ERROR_MESSAGE in raw
    for leak in ("IO Error", "grid.duckdb", "/secrets/", "abc123", "Traceback"):
        assert leak not in raw


def test_framework_validation_becomes_invalid_input(client: TestClient) -> None:
    app = install_error_handlers(FastAPI())

    @app.get("/layers")
    def _layers(hour: int) -> SuccessEnvelope[Scenario]:  # pragma: no cover - never reached
        raise AssertionError

    body = TestClient(app).get("/layers", params={"hour": "not-an-int"}).json()

    assert body["error"]["code"] == "invalid_input"
    assert body["error"]["details"] == {"field": "query.hour"}


def test_safe_details_drops_sensitive_keys_and_truncates() -> None:
    details = safe_details(
        {
            "field": "hour",
            "duckdb_path": "/secrets/grid.duckdb",
            "api_key": "abc123",
            "sql": "SELECT 1",
            "reason": "x" * 500,
        }
    )

    assert set(details) == {"field", "reason"}
    assert len(details["reason"]) == 201


def test_envelopes_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SuccessEnvelope[Scenario].model_validate(
            {
                "status": "ok",
                "data": {"scenario_id": "uri_2021", "hours": 1},
                "meta": {
                    "request_id": "r",
                    "generated_at": "2026-09-05T00:00:00Z",
                    "traceback": "boom",
                },
            }
        )

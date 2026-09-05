"""Contract tests for the versioned envelope and failure semantics."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from copilot.api import (
    API_VERSION,
    FailureEnvelope,
    InvalidInputError,
    NotFoundError,
    UnavailableError,
    install_error_handlers,
)
from copilot.api.errors import INTERNAL_ERROR_MESSAGE, REQUEST_ID_HEADER


class Scenario(BaseModel):
    scenario_id: str
    hours: int


@pytest.fixture
def client() -> TestClient:
    app = install_error_handlers(FastAPI())

    @app.get("/ok")
    def _ok() -> JSONResponse:
        return JSONResponse(
            content={"scenario_id": "uri_2021", "hours": 168},
        )

    @app.get("/unavailable")
    def _unavailable() -> JSONResponse:
        raise UnavailableError(
            "Cascade artifacts for scenario 'uri_2021' have not been built.",
            details={"scenario_id": "uri_2021"},
        )

    @app.get("/missing")
    def _missing() -> JSONResponse:
        raise NotFoundError("Unknown scenario 'nope'.")

    @app.get("/invalid")
    def _invalid() -> JSONResponse:
        raise InvalidInputError("hour must be between 0 and 167.")

    @app.get("/boom")
    def _boom() -> JSONResponse:
        raise RuntimeError(
            "IO Error: could not open /secrets/grid.duckdb (token=abc123)"
        )

    return TestClient(app, raise_server_exceptions=False)


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
    def _layers(hour: int) -> JSONResponse:  # pragma: no cover - never reached
        raise AssertionError

    body = TestClient(app).get("/layers", params={"hour": "not-an-int"}).json()

    assert body["error"]["code"] == "invalid_input"
    assert body["error"]["details"] == {"field": "query.hour"}


def test_failure_envelopes_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        FailureEnvelope.model_validate(
            {
                "status": "error",
                "data": None,
                "error": {
                    "code": "invalid_input",
                    "message": "test",
                    "retryable": False,
                },
                "meta": {
                    "request_id": "r",
                    "generated_at": "2026-09-05T00:00:00Z",
                    "traceback": "boom",
                },
            }
        )


def test_successful_response_carries_request_id_header(client: TestClient) -> None:
    response = client.get("/ok")

    assert response.status_code == 200
    assert REQUEST_ID_HEADER in response.headers
    assert response.headers[REQUEST_ID_HEADER]


def test_client_supplied_request_id_is_echoed_back(client: TestClient) -> None:
    custom_id = "client-req-12345"
    response = client.get("/ok", headers={REQUEST_ID_HEADER: custom_id})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == custom_id

"""HTTP behaviour of the explainer teaching-cascade read route."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.routes.explainer import TRACE_ARTIFACT
from twin.toy_cascade import trace_hash


def test_the_route_serves_the_persisted_server_solved_trace() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/explainer/toy-cascade")
    assert response.status_code == 200
    body = response.json()
    assert body == json.loads(TRACE_ARTIFACT.read_text(encoding="utf-8"))
    assert body["traceHash"] == trace_hash(body["stages"])
    assert body["networkProvenance"] == "synthetic_five_bus_teaching_network"


def test_a_missing_artifact_is_unavailable_not_an_empty_success(
    tmp_path: Path,
) -> None:
    app = create_app()
    app.state.explainer_trace_path = tmp_path / "absent.json"
    with TestClient(app) as client:
        response = client.get("/explainer/toy-cascade")
    assert response.status_code == 503
    assert "has not been exported" in json.dumps(response.json())


def test_an_unreadable_artifact_is_unavailable_not_a_partial_trace(
    tmp_path: Path,
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("[not json", encoding="utf-8")
    app = create_app()
    app.state.explainer_trace_path = broken
    with TestClient(app) as client:
        response = client.get("/explainer/toy-cascade")
    assert response.status_code == 503

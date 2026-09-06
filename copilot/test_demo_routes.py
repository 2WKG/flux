"""HTTP proof for the optional, injected demo planning routes."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.testclient import TestClient

from copilot.api import install_error_handlers
from copilot.demo.bridge import DemoCapability, DemoToolResult
from copilot.routes.demo import create_demo_router


class _Bridge:
    def __init__(self, result: DemoToolResult | None = None) -> None:
        self.result = result or DemoToolResult(
            status="available",
            label="Synthetic Texas cascade result",
            data={"lost_load_mw": 12.5, "topology": "synthetic (ACTIVSg2000)"},
            provenance=("tool:run_cascade", "artifact:tx:synthetic:fixture"),
            limitations=("Synthetic topology only.",),
        )
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    async def capabilities(self) -> tuple[DemoCapability, ...]:
        return (
            DemoCapability(
                name="Texas cascade",
                state="tx",
                status="synthetic",
                label="Synthetic topology only",
                source="ACTIVSg2000",
                limitations=("Not a physical asset map.",),
            ),
            DemoCapability(
                name="Minnesota inventory",
                state="mn",
                status="aggregate",
                label="Inventory and aggregate stress only",
                limitations=("No topology-backed cascade.",),
            ),
        )

    async def execute(
        self, tool: str, arguments: Mapping[str, object]
    ) -> DemoToolResult:
        self.calls.append((tool, arguments))
        return self.result


def _client(bridge: _Bridge) -> TestClient:
    app = install_error_handlers(FastAPI())
    app.include_router(create_demo_router(bridge))
    return TestClient(app)


def test_brief_exposes_visible_truth_labels_without_a_primary_route_dependency() -> None:
    response = _client(_Bridge()).get("/demo/brief")

    assert response.status_code == 200
    body = response.json()
    assert body["primary_copilot_path"] == "/ask"
    assert [(item["state"], item["status"]) for item in body["capabilities"]] == [
        ("tx", "synthetic"),
        ("mn", "aggregate"),
    ]


def test_texas_cascade_request_preserves_the_named_tool_result_without_math() -> None:
    bridge = _Bridge()
    response = _client(bridge).post(
        "/demo/ask",
        json={
            "question": "What cascade failures follow this outage?",
            "context": {"state": "tx", "scenario_id": "uri_2021", "hour": 4},
        },
    )

    assert response.status_code == 200
    body = response.json()
    card = body["cards"][0]
    assert body["mode"] == "planning_fallback"
    assert bridge.calls == [("cascade", {"state": "tx", "scenario_id": "uri_2021", "hour": 4})]
    assert card["kind"] == "cascade"
    assert card["result"]["data"]["lost_load_mw"] == 12.5
    assert card["result"]["provenance"] == [
        "tool:run_cascade",
        "artifact:tx:synthetic:fixture",
    ]
    assert "12.5" not in card["plain_english"]


def test_minnesota_cascade_prompt_selects_availability_boundary() -> None:
    bridge = _Bridge()
    response = _client(bridge).post(
        "/demo/ask",
        json={"question": "Run a cascade", "context": {"state": "mn"}},
    )

    assert response.status_code == 200
    card = response.json()["cards"][0]
    assert bridge.calls == [("availability", {"state": "mn"})]
    assert card["kind"] == "availability"
    assert "no topology-backed cascade" in card["plain_english"]


def test_forecast_prompt_keeps_experimental_result_labelled_and_unavailable_honest() -> None:
    bridge = _Bridge(
        DemoToolResult(
            status="unavailable",
            label="Experimental forecast",
            reason="No experimental forecast artifact is installed.",
            limitations=("No weather forecast is inferred.",),
        )
    )
    response = _client(bridge).post(
        "/demo/ask",
        json={"question": "Show the JEPA projection", "context": {"state": "mn"}},
    )

    assert response.status_code == 200
    card = response.json()["cards"][0]
    assert bridge.calls == [("forecast", {"state": "mn"})]
    assert card["kind"] == "forecast"
    assert card["result"]["status"] == "unavailable"
    assert "unavailable" in card["plain_english"]


def test_invalid_demo_context_uses_the_shared_http_validation_envelope() -> None:
    response = _client(_Bridge()).post(
        "/demo/ask", json={"question": "show inventory", "context": {"hour": -1}}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"

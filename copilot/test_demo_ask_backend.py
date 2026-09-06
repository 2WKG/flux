"""Real HTTP proof for the injected demo cascade backend and existing ``/ask`` SSE."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.demo.ask_backend import DemoAskBackend
from copilot.tools.schemas import ArtifactRef, CascadeData, TrippedElement

ATTEMPT = "demo_cascade_0123456789"


class _ActualRunner:
    """A strict core-shaped test adapter, never a route-level fake response."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def run(
        self, *, element_ids: list[str], scenario_id: str, hour: int
    ) -> CascadeData:
        self.calls.append(
            {"element_ids": element_ids, "scenario_id": scenario_id, "hour": hour}
        )
        return CascadeData(
            status="available",
            provenance=[
                ArtifactRef(
                    artifact_id="tx:synthetic:cascade:fixture",
                    artifact_version="v1",
                    source_kind="simulated",
                    source_ref="twin.tools.run_cascade",
                )
            ],
            run_id="cascade-fixture-1",
            scenario_id="uri_2021",
            hour=4,
            tripped_element_ids=[
                TrippedElement(
                    element_id="line-7", kind="line", stage=1, cause="forced"
                )
            ],
            lost_load_mw=12.5,
            counties_dark=[],
            critical_loads_lost=[],
            steps=1,
        )


def _events(response) -> list[tuple[str, dict[str, object]]]:
    assert response.headers["content-type"].startswith("text/event-stream")
    result = []
    for block in response.text.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if ": " in line
        )
        if "event" in fields:
            result.append((fields["event"], json.loads(fields["data"])))
    return result


def _client(runner: _ActualRunner) -> TestClient:
    backend = DemoAskBackend(runner)
    return TestClient(
        create_app(Settings(duckdb_path="data/duck/grid.duckdb"), ask_backend=backend)
    )


def test_existing_ask_http_path_runs_a_provenanced_cascade_tool_and_streams_plain_text() -> None:
    runner = _ActualRunner()
    response = _client(runner).post(
        "/ask",
        json={
            "attempt_id": ATTEMPT,
            "question": "Run the cascade for this line outage.",
            "context": {
                "scenario_id": "uri_2021",
                "hour": 4,
                "selected_element_id": "line-7",
            },
            "history": [],
        },
    )

    assert runner.calls == [
        {"element_ids": ["line-7"], "scenario_id": "uri_2021", "hour": 4}
    ]
    events = _events(response)
    assert [event for event, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "text",
        "done",
    ]
    tool_result = events[2][1]
    assert tool_result["tool"] == "run_cascade"
    assert tool_result["result"]["lost_load_mw"] == 12.5
    # The shared narrator carries provenance beside the tool evidence; its SSE
    # result payload intentionally contains only the evidence fields.
    assert "provenance" not in tool_result["result"]
    assert "12.5" not in events[3][1]["delta"]


def test_existing_ask_http_path_keeps_missing_selection_an_explicit_tool_unavailable() -> None:
    runner = _ActualRunner()
    response = _client(runner).post(
        "/ask",
        json={
            "attempt_id": ATTEMPT,
            "question": "Run a cascade.",
            "context": {"scenario_id": "uri_2021", "hour": 4},
            "history": [],
        },
    )

    assert runner.calls == []
    events = _events(response)
    assert [event for event, _ in events] == ["lifecycle", "tool_call", "tool_result", "error"]
    assert events[2][1]["ok"] is False
    assert events[3][1]["error"]["code"] == "unavailable"

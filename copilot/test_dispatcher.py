from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.dispatcher import (
    AssistantText,
    ToolCall,
    ToolDispatcher,
    interactive_tool_handlers,
)
from copilot.non_interactive_tool_handlers import (
    NonInteractiveToolServices,
    non_interactive_tool_handlers,
)
from copilot.providers.claude import ClaudeNarrationProvider
from copilot.tools.schemas import TOOL_REGISTRY, unavailable_output, validate_tool_input


def _handlers(calls: list[tuple[str, object]]):
    async def handler(payload, context):
        calls.append((payload.__class__.__name__, context["scenario_id"]))
        return unavailable_output(
            "unsupported_request", "test implementation unavailable"
        ).model_dump(mode="json")

    return {definition.name: handler for definition in TOOL_REGISTRY}


class _Provider:
    def __init__(self) -> None:
        self.actions = [
            ToolCall("call-1", "top_lines", {"region": "ERCOT", "tech": "any", "n": 1}),
            AssistantText("Grounded answer."),
        ]

    async def next_action(self, **kwargs):
        assert kwargs["context"]["scenario_id"] == "uri_2021"
        return self.actions.pop(0)


def test_dispatcher_validates_and_executes_a_provider_selected_real_handler() -> None:
    calls: list[tuple[str, object]] = []
    results, text = asyncio.run(
        ToolDispatcher(_handlers(calls)).run(
            _Provider(),
            question="lines",
            history=(),
            context={"scenario_id": "uri_2021"},
        )
    )
    assert text == "Grounded answer."
    assert results[0].name == "top_lines"
    assert calls == [("TopLinesInput", "uri_2021")]


def test_dispatcher_fails_closed_on_invalid_provider_arguments() -> None:
    class BadProvider:
        async def next_action(self, **kwargs):
            return ToolCall(
                "call-1", "top_lines", {"region": "ERCOT", "tech": "bad", "n": 1}
            )

    with pytest.raises(ValueError, match="invalid arguments"):
        asyncio.run(
            ToolDispatcher(_handlers([])).run(
                BadProvider(), question="x", history=(), context={}
            )
        )


def test_composed_handler_registry_uses_concrete_persisted_bindings(
    tmp_path: Path,
) -> None:
    """A production registry does not replace the nine historic tools with a stub."""

    handlers = interactive_tool_handlers(
        _InteractiveService(),
        historical_handlers=non_interactive_tool_handlers(
            NonInteractiveToolServices(database_path=tmp_path / "missing.duckdb")
        ),
    )
    result = asyncio.run(
        handlers["predict_outage"](
            validate_tool_input(
                "predict_outage", {"county_fips": "48453", "scenario_id": "uri_2021"}
            ),
            {},
        )
    )

    assert result["status"] == "unavailable"
    assert result["unavailable"]["code"] == "artifact_unavailable"
    assert "outage prediction database" in result["unavailable"]["reason"]


class _InteractiveService:
    async def scenario_edit(self, payload):
        assert payload.base_scenario_id == "interactive"
        return {
            "model_fidelity": "dc_screening",
            "network_provenance": "synthetic_activsg2000",
            "limitations": ["Synthetic topology only."],
            "data": {"edit_hash": "f" * 16},
        }

    async def cascade(self, payload):
        assert payload.scenario_id == "interactive"
        return {
            "model_fidelity": "dc_screening",
            "network_provenance": "synthetic_activsg2000",
            "limitations": ["Synthetic topology only."],
            "data": {"cascade_id": "cascade-0123456789abcdef"},
        }


class _AskProvider:
    def __init__(self) -> None:
        self.actions = [
            ToolCall(
                "scene-edit-1",
                "scenario_edit",
                {
                    "base_scenario_id": "interactive",
                    "ops": [{"op": "outage", "element_id": "line:7"}],
                    "hour": 0,
                    "seed": 0,
                },
            ),
            AssistantText("The requested synthetic edit is available."),
        ]

    async def next_action(self, **kwargs):
        assert len(kwargs["tools"]) == 13
        return self.actions.pop(0)


def _events(response) -> list[tuple[str, dict[str, object]]]:
    assert response.headers["content-type"].startswith("text/event-stream")
    events = []
    for block in response.text.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if ": " in line
        )
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def test_ask_uses_provider_selected_pydantic_handler_and_nests_scene_action() -> None:
    provider = _AskProvider()
    dispatcher = ToolDispatcher(interactive_tool_handlers(_InteractiveService()))
    client = TestClient(
        create_app(
            Settings(duckdb_path=Path("/tmp/grid.duckdb")),
            tool_provider=provider,
            tool_dispatcher=dispatcher,
        )
    )
    events = _events(
        client.post(
            "/ask",
            json={
                "attempt_id": "dispatcher_scene_action_1",
                "question": "Make this outage edit.",
                "history": [],
            },
        )
    )
    assert [name for name, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "text",
        "done",
    ]
    result = events[2][1]["result"]
    assert result["scene_action"] == {
        "action_id": "scenario_edit:scene-edit-1",
        "kind": "scenario_edit",
        "tool_call_id": "scene-edit-1",
        "edit_hash": "f" * 16,
        "reversible": True,
        "status": "available",
    }


def test_configured_app_provider_reaches_dispatcher_over_http_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured app uses the production Claude transport through ``/ask``."""

    class FakeMessages:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.responses = [
                SimpleNamespace(
                    content=[
                        SimpleNamespace(
                            type="tool_use",
                            id="configured-scene-edit",
                            name="scenario_edit",
                            input={
                                "base_scenario_id": "interactive",
                                "ops": [
                                    {"op": "outage", "element_id": "line:7"}
                                ],
                                "hour": 0,
                                "seed": 0,
                            },
                        )
                    ]
                ),
                SimpleNamespace(content=[SimpleNamespace(type="text", text="Done.")]),
            ]

        async def create(self, **kwargs: object) -> object:
            self.calls.append(dict(kwargs))
            return self.responses.pop(0)

    messages = FakeMessages()
    built = []

    def configured_factory(settings: Settings) -> ClaudeNarrationProvider:
        built.append(settings.provider_status())
        return ClaudeNarrationProvider(
            "injected-test-key",
            settings.model_for("claude"),
            client=SimpleNamespace(messages=messages),
        )

    monkeypatch.setattr("copilot.app.build_tool_provider", configured_factory)
    dispatcher = ToolDispatcher(interactive_tool_handlers(_InteractiveService()))
    client = TestClient(
        create_app(
            Settings(
                duckdb_path=Path("/tmp/grid.duckdb"),
                anthropic_api_key="unused-configured-key",
            ),
            tool_dispatcher=dispatcher,
        )
    )

    events = _events(
        client.post(
            "/ask",
            json={
                "attempt_id": "configured_dispatcher_1",
                "question": "Make this outage edit.",
                "history": [],
            },
        )
    )

    assert [(event, payload.get("tool")) for event, payload in events] == [
        ("lifecycle", None),
        ("tool_call", "scenario_edit"),
        ("tool_result", "scenario_edit"),
        ("text", None),
        ("done", None),
    ]
    assert len(built) == 1
    assert built[0].provider == "claude"
    assert built[0].ready is True
    assert events[2][1]["result"]["scene_action"] == {
        "action_id": "scenario_edit:configured-scene-edit",
        "kind": "scenario_edit",
        "tool_call_id": "configured-scene-edit",
        "edit_hash": "f" * 16,
        "reversible": True,
        "status": "available",
    }
    assert [tool["name"] for tool in messages.calls[0]["tools"]] == [
        definition.name for definition in TOOL_REGISTRY
    ]
    replay = messages.calls[1]["messages"][-2:]
    assert replay[1]["content"][0]["type"] == "tool_result"


def test_dispatcher_nests_distinct_cascade_request_identity_in_scene_action() -> None:
    class CascadeProvider:
        def __init__(self) -> None:
            self.actions = [
                ToolCall(
                    "cascade-call-1",
                    "cascade",
                    {
                        "element_ids": ["line:7"],
                        "scenario_id": "interactive",
                        "hour": 0,
                        "seed": 0,
                    },
                ),
                AssistantText("Cascade evidence is available."),
            ]

        async def next_action(self, **kwargs):
            return self.actions.pop(0)

    results, _ = asyncio.run(
        ToolDispatcher(
            interactive_tool_handlers(_InteractiveService()), max_turns=2
        ).run(CascadeProvider(), question="Cascade", history=(), context={})
    )

    assert results[0].result["data"]["cascade_id"] != "f" * 16
    assert results[0].result["scene_action"] == {
        "action_id": "cascade:cascade-call-1",
        "kind": "cascade",
        "tool_call_id": "cascade-call-1",
        "cascade_id": "cascade-0123456789abcdef",
        "reversible": True,
        "status": "available",
    }

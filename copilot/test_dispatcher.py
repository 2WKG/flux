from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from copilot.app import create_app
from copilot.config import Settings
from copilot.dispatcher import (
    MAX_TOOL_TURNS,
    AssistantText,
    ToolCall,
    ToolDispatcher,
    ToolLoopOverrun,
    interactive_tool_handlers,
)
from copilot.non_interactive_tool_handlers import (
    NonInteractiveToolServices,
    non_interactive_tool_handlers,
)
from copilot.tools.schemas import TOOL_REGISTRY, unavailable_output, validate_tool_input
from pipelines.labels import SYNTHETIC_TOPOLOGY_LABEL


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
            "network_provenance": SYNTHETIC_TOPOLOGY_LABEL,
            "limitations": ["Synthetic topology only."],
            "edit_hash": "f" * 16,
        }

    async def cascade(self, payload):
        assert payload.scenario_id == "interactive"
        return {
            "model_fidelity": "dc_screening",
            "network_provenance": SYNTHETIC_TOPOLOGY_LABEL,
            "limitations": ["Synthetic topology only."],
            "cascade_id": "cascade-0123456789abcdef",
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


def test_injected_app_provider_reaches_dispatcher_over_http_without_network() -> None:
    """An injected tool transport reaches the dispatcher through ``/ask``.

    The tool-calling transport is deployment-injected, exactly like
    ``ask_backend``: ``create_app`` constructs no default, so an unconfigured
    deployment keeps the documented unavailable terminal.  This test injects one
    and proves the wiring from ``/ask`` down to the interactive handler.
    """

    class RecordingProvider:
        name = "claude"
        model = "claude-test"

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.actions = [
                ToolCall(
                    "configured-scene-edit",
                    "scenario_edit",
                    {
                        "base_scenario_id": "interactive",
                        "ops": [{"op": "outage", "element_id": "line:7"}],
                        "hour": 0,
                        "seed": 0,
                    },
                ),
                AssistantText("Done."),
            ]

        async def next_action(self, **kwargs: object):
            self.calls.append(dict(kwargs))
            return self.actions.pop(0)

    provider = RecordingProvider()
    dispatcher = ToolDispatcher(interactive_tool_handlers(_InteractiveService()))
    client = TestClient(
        create_app(
            Settings(
                duckdb_path=Path("/tmp/grid.duckdb"),
                anthropic_api_key="unused-configured-key",
            ),
            narration_provider=None,
            tool_dispatcher=dispatcher,
            tool_provider=provider,
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
    assert events[2][1]["result"]["scene_action"] == {
        "action_id": "scenario_edit:configured-scene-edit",
        "kind": "scenario_edit",
        "tool_call_id": "configured-scene-edit",
        "edit_hash": "f" * 16,
        "reversible": True,
        "status": "available",
    }
    assert [tool["name"] for tool in provider.calls[0]["tools"]] == [
        definition.name for definition in TOOL_REGISTRY
    ]


def test_unconfigured_app_keeps_the_unavailable_terminal() -> None:
    """Without an injected transport ``/ask`` still refuses rather than guessing."""

    client = TestClient(
        create_app(
            Settings(duckdb_path=Path("/tmp/grid.duckdb")),
            narration_provider=None,
        )
    )
    events = _events(
        client.post(
            "/ask",
            json={
                "attempt_id": "unconfigured_dispatcher_1",
                "question": "Make this outage edit.",
                "history": [],
            },
        )
    )
    assert [event for event, _ in events] == ["lifecycle", "error"]
    assert events[-1][1]["error"]["code"] == "unavailable"


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


class _LoopingProvider:
    """A provider that never stops calling tools."""

    def __init__(self) -> None:
        self.turns = 0

    async def next_action(self, **kwargs):
        self.turns += 1
        return ToolCall(
            f"loop-{self.turns}",
            "scenario_edit",
            {
                "base_scenario_id": "interactive",
                "ops": [{"op": "outage", "element_id": "line:7"}],
                "hour": 0,
                "seed": 0,
            },
        )


def test_the_tool_loop_is_bounded_by_max_turns() -> None:
    """P7: a looping provider is stopped after exactly `max_turns` calls."""

    provider = _LoopingProvider()
    dispatcher = ToolDispatcher(
        interactive_tool_handlers(_InteractiveService()), max_turns=3
    )
    with pytest.raises(ToolLoopOverrun, match="3 turns"):
        asyncio.run(dispatcher.run(provider, question="Edit", history=(), context={}))
    assert provider.turns == 3


def test_the_default_tool_loop_bound_is_max_tool_turns() -> None:
    provider = _LoopingProvider()
    dispatcher = ToolDispatcher(interactive_tool_handlers(_InteractiveService()))
    with pytest.raises(ToolLoopOverrun):
        asyncio.run(dispatcher.run(provider, question="Edit", history=(), context={}))
    assert provider.turns == MAX_TOOL_TURNS


def test_a_loop_overrun_is_distinguishable_from_an_invalid_tool_action() -> None:
    """`/ask` must not collapse an unbounded provider into `tool_error`."""

    client = TestClient(
        create_app(
            Settings(duckdb_path=Path("/tmp/grid.duckdb")),
            narration_provider=None,
            tool_dispatcher=ToolDispatcher(
                interactive_tool_handlers(_InteractiveService()), max_turns=2
            ),
            tool_provider=_LoopingProvider(),
        )
    )
    events = _events(
        client.post(
            "/ask",
            json={
                "attempt_id": "loop_overrun_attempt_1",
                "question": "Edit",
                "history": [],
            },
        )
    )
    assert events[-1][0] == "error"
    assert events[-1][1]["error"]["code"] == "protocol_error"
    assert "bounded tool-call loop" in events[-1][1]["error"]["message"]


def test_a_minnesota_question_is_refused_not_answered_with_texas_data() -> None:
    """Ported from #254: never answer a Minnesota question with ERCOT numbers."""

    class MinnesotaProvider:
        def __init__(self) -> None:
            self.actions = [
                ToolCall(
                    "mn-1",
                    "cascade",
                    {
                        "element_ids": ["line:7"],
                        "scenario_id": "interactive",
                        "hour": 0,
                        "seed": 0,
                    },
                ),
                AssistantText("No Minnesota topology is available."),
            ]

        async def next_action(self, **kwargs):
            return self.actions.pop(0)

    results, _ = asyncio.run(
        ToolDispatcher(interactive_tool_handlers(_InteractiveService())).run(
            MinnesotaProvider(),
            question="Run a cascade in Minnesota",
            history=(),
            context={},
        )
    )
    assert results[0].result["status"] == "unavailable"
    assert results[0].result["unavailable"]["code"] == "unsupported_request"
    assert "Texas synthetic" in results[0].result["unavailable"]["reason"]
    assert "lost_load_mw" not in json.dumps(dict(results[0].result))
    assert "scene_action" not in results[0].result


def test_a_texas_question_still_runs_the_interactive_cascade() -> None:
    """The Minnesota guard must not refuse the questions it does serve."""

    class TexasProvider:
        def __init__(self) -> None:
            self.actions = [
                ToolCall(
                    "tx-1",
                    "cascade",
                    {
                        "element_ids": ["line:7"],
                        "scenario_id": "interactive",
                        "hour": 0,
                        "seed": 0,
                    },
                ),
                AssistantText("Done."),
            ]

        async def next_action(self, **kwargs):
            return self.actions.pop(0)

    results, _ = asyncio.run(
        ToolDispatcher(interactive_tool_handlers(_InteractiveService())).run(
            TexasProvider(),
            question="Run an ERCOT cascade near Houston",
            history=(),
            context={},
        )
    )
    assert results[0].result["status"] == "available"
    assert results[0].result["data"]["cascade_id"] == "cascade-0123456789abcdef"


def test_a_missing_simulation_core_names_itself_in_the_tool_result() -> None:
    """Not "the answer provider is unavailable" -- the core is what is missing."""

    from copilot.api import UnavailableError

    class _BrokenService:
        async def cascade(self, payload):
            raise UnavailableError(
                "Synthetic interactive simulation is unavailable.",
                details={"reason": "synthetic_core_unavailable"},
            )

        async def scenario_edit(self, payload):  # pragma: no cover - unused here
            raise AssertionError("not called")

    class _Provider:
        def __init__(self) -> None:
            self.actions = [
                ToolCall(
                    "broken-1",
                    "cascade",
                    {
                        "element_ids": ["line:7"],
                        "scenario_id": "interactive",
                        "hour": 0,
                        "seed": 0,
                    },
                ),
                AssistantText("The simulation core is unavailable."),
            ]

        async def next_action(self, **kwargs):
            return self.actions.pop(0)

    results, answer = asyncio.run(
        ToolDispatcher(interactive_tool_handlers(_BrokenService())).run(
            _Provider(), question="Cascade", history=(), context={}
        )
    )
    assert results[0].result["status"] == "unavailable"
    reason = results[0].result["unavailable"]["reason"]
    assert "simulation core" in reason
    assert "synthetic_core_unavailable" in reason
    assert "provider" not in reason.lower()
    assert answer


def test_the_frozen_tool_schemas_bound_their_list_inputs() -> None:
    """P4: the bound lives in the FROZEN contract, not only at the HTTP layer.

    Widening `max_length` in `copilot/tools/schemas.py` must turn this red;
    the HTTP-layer bound in `copilot/interactive_routes.py` is a separate
    assertion in `copilot/test_interactive_routes.py`.
    """

    at_the_bound = validate_tool_input(
        "scenario_edit",
        {
            "base_scenario_id": "interactive",
            "ops": [
                {"op": "outage", "element_id": f"line:{index}"} for index in range(64)
            ],
            "hour": 0,
            "seed": 0,
        },
    )
    assert len(at_the_bound.ops) == 64

    with pytest.raises(ValidationError):
        validate_tool_input(
            "scenario_edit",
            {
                "base_scenario_id": "interactive",
                "ops": [
                    {"op": "outage", "element_id": f"line:{index}"}
                    for index in range(65)
                ],
                "hour": 0,
                "seed": 0,
            },
        )

    with pytest.raises(ValidationError):
        validate_tool_input(
            "cascade",
            {
                "element_ids": [f"line:{index}" for index in range(65)],
                "scenario_id": "interactive",
                "hour": 0,
                "seed": 0,
            },
        )

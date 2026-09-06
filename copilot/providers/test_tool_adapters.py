"""No-network provider transport tests for the frozen dispatcher contract."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from copilot.dispatcher import AssistantText, ToolCall, ToolResult
from copilot.providers.claude import ClaudeNarrationProvider
from copilot.providers.gemini import GeminiNarrationProvider
from copilot.tools.schemas import TOOL_SCHEMAS

EXPECTED_NAMES = [
    "predict_outage",
    "run_cascade",
    "score_site",
    "top_lines",
    "sql",
    "cite",
    "compare_interventions",
    "top_critical_elements",
    "causal_query",
    "scenario_edit",
    "cascade",
    "balance",
    "redundancy",
]


class _ClaudeMessages:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return self.response


class _GeminiModels:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate_content(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return self.response


class _TypeFactory:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class _GeminiTypes:
    GenerateContentConfig = _TypeFactory
    Tool = _TypeFactory
    AutomaticFunctionCallingConfig = _TypeFactory


class _GeminiModule:
    types = _GeminiTypes


def _tool_result() -> ToolResult:
    return ToolResult(
        call_id="call-1",
        name="scenario_edit",
        arguments={"base_scenario_id": "interactive", "ops": []},
        result={"status": "available", "data": {"edit_hash": "abc"}},
    )


def _kwargs() -> dict[str, Any]:
    return {
        "question": "What changes if this line is out?",
        "history": ({"role": "user", "content": "Earlier question"},),
        "context": {"scenario_id": "interactive", "hour": 0},
        "tools": tuple(TOOL_SCHEMAS),
        "results": (_tool_result(),),
    }


def test_claude_sends_all_frozen_tools_and_replays_tool_result() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id="claude-call",
                name="scenario_edit",
                input={"base_scenario_id": "interactive", "ops": []},
            )
        ]
    )
    messages = _ClaudeMessages(response)
    provider = ClaudeNarrationProvider(
        "unused", "claude-test", client=SimpleNamespace(messages=messages)
    )

    action = asyncio.run(provider.next_action(**_kwargs()))

    assert action == ToolCall(
        "claude-call", "scenario_edit", {"base_scenario_id": "interactive", "ops": []}
    )
    request = messages.calls[0]
    assert [tool["name"] for tool in request["tools"]] == EXPECTED_NAMES
    assert [tool["name"] for tool in request["tools"]] == [
        schema["name"] for schema in TOOL_SCHEMAS
    ]
    assert all(tool["strict"] is True for tool in request["tools"])
    replay = request["messages"][-2:]
    assert replay[0]["content"][0]["type"] == "tool_use"
    assert replay[1]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "call-1",
        "content": '{"data":{"edit_hash":"abc"},"status":"available"}',
    }


def test_claude_returns_terminal_text_without_network() -> None:
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text="Done.")])
    provider = ClaudeNarrationProvider(
        "unused",
        "claude-test",
        client=SimpleNamespace(messages=_ClaudeMessages(response)),
    )

    assert asyncio.run(provider.next_action(**_kwargs())) == AssistantText("Done.")


def test_gemini_sends_all_frozen_declarations_and_function_response() -> None:
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(
                            function_call=SimpleNamespace(
                                id="gemini-call",
                                name="scenario_edit",
                                args={"base_scenario_id": "interactive", "ops": []},
                            )
                        )
                    ]
                )
            )
        ]
    )
    models = _GeminiModels(response)
    provider = GeminiNarrationProvider(
        "unused",
        "gemini-test",
        client=SimpleNamespace(aio=SimpleNamespace(models=models)),
        genai_module=_GeminiModule(),
    )

    action = asyncio.run(provider.next_action(**_kwargs()))

    assert action == ToolCall(
        "gemini-call", "scenario_edit", {"base_scenario_id": "interactive", "ops": []}
    )
    request = models.calls[0]
    config = request["config"]
    declaration_tool = config.kwargs["tools"][0]
    assert [
        item["name"] for item in declaration_tool.kwargs["function_declarations"]
    ] == EXPECTED_NAMES
    assert [
        item["parameters_json_schema"]
        for item in declaration_tool.kwargs["function_declarations"]
    ] == [schema["input_schema"] for schema in TOOL_SCHEMAS]
    response_part = request["contents"][-1]["parts"][0]["function_response"]
    assert response_part == {
        "id": "call-1",
        "name": "scenario_edit",
        "response": {"status": "available", "data": {"edit_hash": "abc"}},
    }
    assert config.kwargs["automatic_function_calling"].kwargs == {"disable": True}


def test_gemini_returns_terminal_text_without_network() -> None:
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(parts=[SimpleNamespace(text="Done.")])
            )
        ]
    )
    provider = GeminiNarrationProvider(
        "unused",
        "gemini-test",
        client=SimpleNamespace(aio=SimpleNamespace(models=_GeminiModels(response))),
        genai_module=_GeminiModule(),
    )

    assert asyncio.run(provider.next_action(**_kwargs())) == AssistantText("Done.")

from __future__ import annotations

import asyncio

import pytest

from copilot.dispatcher import AssistantText, ToolCall, ToolDispatcher
from copilot.tools.schemas import TOOL_REGISTRY


def _handlers(calls: list[tuple[str, object]]):
    async def handler(payload, context):
        calls.append((payload.__class__.__name__, context["scenario_id"]))
        return {"status": "available", "value": 1}

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
    results, text = asyncio.run(ToolDispatcher(_handlers(calls)).run(_Provider(), question="lines", history=(), context={"scenario_id": "uri_2021"}))
    assert text == "Grounded answer."
    assert results[0].name == "top_lines"
    assert calls == [("TopLinesInput", "uri_2021")]


def test_dispatcher_fails_closed_on_invalid_provider_arguments() -> None:
    class BadProvider:
        async def next_action(self, **kwargs):
            return ToolCall("call-1", "top_lines", {"region": "ERCOT", "tech": "bad", "n": 1})

    with pytest.raises(ValueError, match="invalid arguments"):
        asyncio.run(ToolDispatcher(_handlers([])).run(BadProvider(), question="x", history=(), context={}))

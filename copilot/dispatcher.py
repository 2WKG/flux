"""Provider-agnostic, bounded execution of the Copilot tool contract.

Providers choose a declared function; this module never infers a tool from a
question.  It validates every provider argument before invoking a registered
handler and gives the provider only immutable context plus prior tool results.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from pydantic import BaseModel, ValidationError

from copilot.tools.schemas import TOOL_REGISTRY, validate_tool_input

MAX_TOOL_TURNS = 4


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    arguments: Mapping[str, object]
    result: Mapping[str, object]


@dataclass(frozen=True)
class AssistantText:
    text: str


class ToolCallingProvider(Protocol):
    """Common projection of Claude/Gemini function-call responses."""

    async def next_action(
        self,
        *,
        question: str,
        history: Sequence[Mapping[str, str]],
        context: Mapping[str, object],
        tools: Sequence[Mapping[str, object]],
        results: Sequence[ToolResult],
    ) -> ToolCall | AssistantText: ...


ToolHandler = Callable[[BaseModel, Mapping[str, object]], Awaitable[Mapping[str, object]]]


class ToolDispatcher:
    """Closed registry with a bounded provider-controlled execution loop."""

    def __init__(self, handlers: Mapping[str, ToolHandler], *, max_turns: int = MAX_TOOL_TURNS) -> None:
        expected = {item.name for item in TOOL_REGISTRY}
        supplied = set(handlers)
        if supplied != expected:
            raise ValueError(
                "tool handler registry must cover exactly the frozen tool contract; "
                f"missing={sorted(expected - supplied)!r}, extra={sorted(supplied - expected)!r}"
            )
        if not 1 <= max_turns <= MAX_TOOL_TURNS:
            raise ValueError(f"max_turns must be from 1 to {MAX_TOOL_TURNS}")
        self._handlers = dict(handlers)
        self._max_turns = max_turns

    @property
    def tools(self) -> tuple[Mapping[str, object], ...]:
        from copilot.tools.schemas import TOOL_SCHEMAS

        return tuple(MappingProxyType(dict(item)) for item in TOOL_SCHEMAS)

    async def run(
        self,
        provider: ToolCallingProvider,
        *,
        question: str,
        history: Sequence[Mapping[str, str]],
        context: Mapping[str, object],
    ) -> tuple[tuple[ToolResult, ...], str]:
        frozen_context = MappingProxyType(dict(context))
        results: list[ToolResult] = []
        for _ in range(self._max_turns):
            action = await provider.next_action(
                question=question,
                history=tuple(MappingProxyType(dict(item)) for item in history),
                context=frozen_context,
                tools=self.tools,
                results=tuple(results),
            )
            if isinstance(action, AssistantText):
                if not action.text:
                    raise ValueError("provider returned empty assistant text")
                return tuple(results), action.text
            result = await self._execute(action, frozen_context)
            results.append(result)
        raise ValueError("provider exceeded the bounded tool-call loop")

    async def _execute(self, call: ToolCall, context: Mapping[str, object]) -> ToolResult:
        try:
            payload = validate_tool_input(call.name, dict(call.arguments))
        except (ValidationError, ValueError) as exc:
            raise ValueError(f"invalid arguments for tool {call.name!r}") from exc
        result = await self._handlers[call.name](payload, context)
        if not isinstance(result, Mapping):
            raise TypeError(f"tool {call.name!r} returned a non-mapping result")
        return ToolResult(call.call_id, call.name, MappingProxyType(dict(call.arguments)), MappingProxyType(dict(result)))

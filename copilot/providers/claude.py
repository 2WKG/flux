"""Claude transport for the bounded Copilot tool dispatcher.

This module deliberately has no policy for choosing tools.  It renders the
dispatcher-owned frozen contract for Anthropic and translates one model turn
back into the small provider-neutral dispatcher result types.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from copilot.dispatcher import AssistantText, ToolCall, ToolResult
from copilot.narration import GroundedNarration
from copilot.providers.grounding import SYSTEM_PROMPT, narration_prompt

MAX_OUTPUT_TOKENS = 1024


class ClaudeNarrationProvider:
    """Anthropic transport for narration and dispatcher-selected tool calls.

    ``client`` is injection-only support for deterministic tests and local
    transports.  Supplying it avoids importing or constructing the SDK.
    """

    name = "claude"

    def __init__(self, api_key: str, model: str, *, client: Any | None = None) -> None:
        if client is None:
            # Keep SDK import/construction out of module import and test paths.
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=api_key)
        self._client = client
        self.model = model

    def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        async def deltas() -> AsyncIterator[str]:
            async with self._client.messages.stream(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": narration_prompt(narration)}],
            ) as stream:
                async for chunk in stream.text_stream:
                    if chunk:
                        yield chunk

        return deltas()

    async def next_action(
        self,
        *,
        question: str,
        history: Sequence[Mapping[str, str]],
        context: Mapping[str, object],
        tools: Sequence[Mapping[str, object]],
        results: Sequence[ToolResult],
    ) -> ToolCall | AssistantText:
        """Ask Claude for exactly one dispatcher turn without streaming.

        The dispatcher retains typed results, rather than SDK response objects.
        Rebuilding the preceding ``tool_use``/``tool_result`` pair from those
        immutable values gives Anthropic the continuation shape it requires.
        """
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            tools=[dict(tool) for tool in tools],
            messages=_messages(question, history, context, results),
        )
        text: list[str] = []
        for block in _field(response, "content", ()):
            kind = _field(block, "type")
            if kind == "tool_use":
                name = _field(block, "name")
                arguments = _field(block, "input", {})
                call_id = _field(block, "id")
                if not isinstance(name, str) or not isinstance(call_id, str):
                    raise ValueError("Claude returned an invalid tool-use block")
                if not isinstance(arguments, Mapping):
                    raise ValueError("Claude tool arguments must be an object")
                return ToolCall(call_id, name, dict(arguments))
            if kind == "text":
                value = _field(block, "text")
                if isinstance(value, str) and value:
                    text.append(value)
        terminal = "".join(text).strip()
        if not terminal:
            raise ValueError("Claude returned neither text nor a tool call")
        return AssistantText(terminal)


def _messages(
    question: str,
    history: Sequence[Mapping[str, str]],
    context: Mapping[str, object],
    results: Sequence[ToolResult],
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = [
        {"role": item["role"], "content": item["content"]} for item in history
    ]
    messages.append(
        {
            "role": "user",
            "content": "Question:\n"
            + question
            + "\n\nSelected context (JSON):\n"
            + _json(context),
        }
    )
    if results:
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": result.call_id,
                        "name": result.name,
                        "input": dict(result.arguments),
                    }
                    for result in results
                ],
            }
        )
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": result.call_id,
                        "content": _json(result.result),
                    }
                    for result in results
                ],
            }
        )
    return messages


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)

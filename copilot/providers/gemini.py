"""Gemini transport for the bounded Copilot tool dispatcher."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from copilot.dispatcher import AssistantText, ToolCall, ToolResult
from copilot.narration import GroundedNarration
from copilot.providers.grounding import SYSTEM_PROMPT, narration_prompt
from copilot.providers.tool_schemas import gemini_tools

MAX_OUTPUT_TOKENS = 1024


class GeminiNarrationProvider:
    """Google GenAI transport for narration and dispatcher-selected tools.

    ``client`` and ``genai_module`` permit fakes to exercise the complete
    request/response seam without importing an SDK or making a network call.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        client: Any | None = None,
        genai_module: Any | None = None,
    ) -> None:
        if client is None or genai_module is None:
            from google import genai

            genai_module = genai if genai_module is None else genai_module
            client = genai_module.Client(api_key=api_key) if client is None else client
        self._genai = genai_module
        self._client = client
        self.model = model

    def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        config = self._genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            automatic_function_calling=(
                self._genai.types.AutomaticFunctionCallingConfig(disable=True)
            ),
        )

        async def deltas() -> AsyncIterator[str]:
            stream = await self._client.aio.models.generate_content_stream(
                model=self.model,
                contents=narration_prompt(narration),
                config=config,
            )
            async for chunk in stream:
                if chunk.text:
                    yield chunk.text

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
        """Ask Gemini for one model turn with automatic execution disabled."""
        _require_frozen_tools(tools)
        config = self._genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            tools=[self._genai.types.Tool(function_declarations=gemini_tools())],
            automatic_function_calling=(
                self._genai.types.AutomaticFunctionCallingConfig(disable=True)
            ),
        )
        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=_contents(question, history, context, results),
            config=config,
        )
        text: list[str] = []
        for index, part in enumerate(_parts(response)):
            function_call = _field(part, "function_call")
            if function_call is not None:
                name = _field(function_call, "name")
                arguments = _field(function_call, "args", {})
                call_id = _field(function_call, "id", f"gemini-{index}")
                if not isinstance(name, str) or not isinstance(call_id, str):
                    raise ValueError("Gemini returned an invalid function call")
                if not isinstance(arguments, Mapping):
                    raise ValueError("Gemini function arguments must be an object")
                return ToolCall(call_id, name, dict(arguments))
            value = _field(part, "text")
            if isinstance(value, str) and value:
                text.append(value)
        response_text = _field(response, "text")
        if not text and isinstance(response_text, str) and response_text:
            text.append(response_text)
        terminal = "".join(text).strip()
        if not terminal:
            raise ValueError("Gemini returned neither text nor a function call")
        return AssistantText(terminal)


def _require_frozen_tools(tools: Sequence[Mapping[str, object]]) -> None:
    expected = [item["name"] for item in gemini_tools()]
    received = [item.get("name") for item in tools]
    if received != expected:
        raise ValueError(
            "dispatcher supplied a tool contract other than the frozen schema"
        )


def _contents(
    question: str,
    history: Sequence[Mapping[str, str]],
    context: Mapping[str, object],
    results: Sequence[ToolResult],
) -> list[dict[str, object]]:
    contents: list[dict[str, object]] = [
        {"role": item["role"], "parts": [{"text": item["content"]}]} for item in history
    ]
    contents.append(
        {
            "role": "user",
            "parts": [
                {
                    "text": "Question:\n"
                    + question
                    + "\n\nSelected context (JSON):\n"
                    + _json(context)
                }
            ],
        }
    )
    if results:
        contents.append(
            {
                "role": "model",
                "parts": [
                    {
                        "function_call": {
                            "id": result.call_id,
                            "name": result.name,
                            "args": dict(result.arguments),
                        }
                    }
                    for result in results
                ],
            }
        )
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "function_response": {
                            "id": result.call_id,
                            "name": result.name,
                            "response": dict(result.result),
                        }
                    }
                    for result in results
                ],
            }
        )
    return contents


def _parts(response: object) -> Sequence[object]:
    candidates = _field(response, "candidates", ())
    if not candidates:
        return ()
    content = _field(candidates[0], "content")
    parts = _field(content, "parts", ())
    return parts if isinstance(parts, Sequence) else ()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)

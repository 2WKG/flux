"""Gemini adapter: `google.genai` streaming translated into text deltas.

Same shape as the Claude adapter on purpose.  The two differ only in the SDK
call and in how a streaming chunk exposes its text; everything the browser
sees is built by `copilot.runtime` from the values below.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from copilot.narration import GroundedNarration
from copilot.providers.grounding import (
    MAX_OUTPUT_TOKENS,
    REQUEST_TIMEOUT_SECONDS,
    SYSTEM_PROMPT,
    narration_prompt,
)
from copilot.providers.selection import (
    SELECTION_SYSTEM_PROMPT,
    ToolSelection,
    selection_prompt,
)


class GeminiNarrationProvider:
    """An `AsyncNarrationProvider` backed by `google.genai`'s async client."""

    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        # Imported here so that importing this module (and the provider
        # registry) never requires the SDK or a credential.
        from google import genai

        self._genai = genai
        # `HttpOptions.timeout` is milliseconds in `google.genai` (introspected
        # against 2.22.0: `types.HttpOptions.model_fields["timeout"]` documents
        # "Timeout for the request in milliseconds").  Without it the SDK has no
        # deadline and a hung exchange never returns.
        self._client = genai.Client(
            api_key=api_key,
            http_options=genai.types.HttpOptions(
                timeout=int(REQUEST_TIMEOUT_SECONDS * 1000)
            ),
        )
        self.model = model

    def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        config = self._genai.types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            # Narration is a terminal turn: tools already ran, and the SDK's
            # automatic function calling has no place in this streaming path.
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
                # A chunk carrying only usage or safety metadata has no text.
                if chunk.text:
                    yield chunk.text

        return deltas()

    async def select_tool(
        self,
        question: str,
        *,
        tools: Sequence[Mapping[str, Any]],
        context: Mapping[str, Any] | None = None,
        history: Sequence[Mapping[str, str]] = (),
    ) -> ToolSelection | None:
        """Plan one turn against the same frozen contract the Claude adapter sends.

        Automatic function calling stays disabled here for the same reason it is
        disabled for narration: the SDK must not execute anything.  A response
        that carries no `function_call` part is the documented refusal.
        """

        types = self._genai.types
        config = types.GenerateContentConfig(
            system_instruction=SELECTION_SYSTEM_PROMPT,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            tools=[types.Tool(function_declarations=list(tools))],
            automatic_function_calling=(
                types.AutomaticFunctionCallingConfig(disable=True)
            ),
        )
        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=selection_prompt(question, context, history),
            config=config,
        )
        for candidate in response.candidates or ():
            content = candidate.content
            for part in (content.parts or ()) if content is not None else ():
                call = part.function_call
                if call is not None and call.name:
                    return ToolSelection(call.name, dict(call.args or {}))
        return None

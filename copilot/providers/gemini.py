"""Gemini adapter: `google.genai` streaming translated into text deltas.

Same shape as the Claude adapter on purpose.  The two differ only in the SDK
call and in how a streaming chunk exposes its text; everything the browser
sees is built by `copilot.runtime` from the values below.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from copilot.narration import GroundedNarration
from copilot.providers.grounding import SYSTEM_PROMPT, narration_prompt

MAX_OUTPUT_TOKENS = 1024


class GeminiNarrationProvider:
    """An `AsyncNarrationProvider` backed by `google.genai`'s async client."""

    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        # Imported here so that importing this module (and the provider
        # registry) never requires the SDK or a credential.
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
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

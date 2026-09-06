"""Claude adapter: Anthropic streaming translated into text deltas.

The adapter owns nothing but transport.  Ordering, tool events, citations,
verification, and every terminal event stay in `copilot.runtime`, so the
browser cannot tell from the stream which provider produced the answer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from copilot.narration import GroundedNarration
from copilot.providers.grounding import SYSTEM_PROMPT, narration_prompt

MAX_OUTPUT_TOKENS = 1024


class ClaudeNarrationProvider:
    """An `AsyncNarrationProvider` backed by `anthropic.AsyncAnthropic`."""

    name = "claude"

    def __init__(self, api_key: str, model: str) -> None:
        # Imported here so that importing this module (and the provider
        # registry) never requires the SDK or a credential.
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
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

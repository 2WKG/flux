"""Claude adapter: Anthropic streaming translated into text deltas.

The adapter owns nothing but transport.  Ordering, tool events, citations,
verification, and every terminal event stay in `copilot.runtime`, so the
browser cannot tell from the stream which provider produced the answer.
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


class ClaudeNarrationProvider:
    """An `AsyncNarrationProvider` backed by `anthropic.AsyncAnthropic`."""

    name = "claude"

    def __init__(self, api_key: str, model: str) -> None:
        # Imported here so that importing this module (and the provider
        # registry) never requires the SDK or a credential.
        from anthropic import AsyncAnthropic

        # `AsyncAnthropic(timeout=...)` is seconds.  Without it the SDK applies
        # its own default and a hung exchange is not bounded by this service.
        self._client = AsyncAnthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
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

    async def select_tool(
        self,
        question: str,
        *,
        tools: Sequence[Mapping[str, Any]],
        context: Mapping[str, Any] | None = None,
        history: Sequence[Mapping[str, str]] = (),
    ) -> ToolSelection | None:
        """Plan one turn: which frozen tool answers this, with which arguments.

        `tool_choice` stays `auto` rather than `any`: forcing a call would make
        "no tool fits" unrepresentable, and the model would have to invent an
        argument to satisfy the force.  A turn that returns no `tool_use` block
        is the documented refusal, and the caller reports it as such.
        """

        message = await self._client.messages.create(
            model=self.model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SELECTION_SYSTEM_PROMPT,
            tools=list(tools),
            tool_choice={"type": "auto"},
            messages=[
                {
                    "role": "user",
                    "content": selection_prompt(question, context, history),
                }
            ],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use":
                return ToolSelection(block.name, dict(block.input or {}))
        return None

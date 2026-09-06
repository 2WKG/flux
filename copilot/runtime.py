"""Route-free, injected runtime for the ordered Copilot SSE contract."""

from __future__ import annotations

from asyncio import CancelledError
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from copilot.narration import GroundedNarration
from copilot.sse import CopilotEventStream, SseEvent


class NarrationProvider(Protocol):
    """An injected provider; tests use deterministic local implementations."""

    def text(self, narration: GroundedNarration) -> Iterable[str]: ...


@dataclass(frozen=True)
class ToolTurn:
    call_id: str
    tool: str
    input: dict[str, object]
    narration: GroundedNarration
    elapsed_ms: int = 0


def run_turn(
    provider: NarrationProvider | None, turn: ToolTurn
) -> tuple[SseEvent, ...]:
    """Build an ordered stream without calling a network provider itself."""
    stream = CopilotEventStream()
    events = [stream.start(), stream.tool_call(turn.call_id, turn.tool, turn.input)]
    if turn.narration.status == "unavailable":
        events.append(
            stream.error(
                "unavailable",
                turn.narration.text,
                retryable=turn.narration.unavailable.retryable,
            )
        )
        return tuple(events)
    events.append(
        stream.tool_result(
            turn.call_id,
            turn.tool,
            dict(turn.narration.evidence),
            elapsed_ms=turn.elapsed_ms,
        )
    )
    for index, hit in enumerate(turn.narration.citations, 1):
        events.append(
            stream.citation(f"{turn.call_id}:cite:{index}", hit.model_dump(mode="json"))
        )
    if provider is None:
        events.append(
            stream.error(
                "unavailable", "No model provider is configured.", retryable=False
            )
        )
        return tuple(events)
    try:
        for delta in provider.text(turn.narration):
            events.append(stream.text(delta))
    except CancelledError:
        events.append(
            stream.error("cancelled", "The answer was cancelled.", retryable=True)
        )
        return tuple(events)
    events.append(stream.done(verified=True))
    return tuple(events)

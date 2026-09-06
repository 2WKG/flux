"""Route-free, injected runtime for the ordered Copilot SSE contract."""

from __future__ import annotations

from asyncio import CancelledError
from collections.abc import Iterable, Mapping
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
            _json_ready(turn.narration.evidence),
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
    except Exception:  # noqa: BLE001 - provider exceptions must become safe SSE terminals.
        events.append(
            stream.error(
                "upstream_error", "The model provider failed.", retryable=False
            )
        )
        return tuple(events)
    events.append(stream.done(verified=True))
    return tuple(events)


def _json_ready(value: object) -> dict[str, object]:
    """Copy immutable narration evidence into a JSON-native event payload.

    Narration freezes its accepted evidence so provider code cannot mutate it.
    ``json.dumps`` deliberately does not serialize ``MappingProxyType``, so the
    runtime copies mappings and tuples only at the SSE boundary.  Values that
    are not containers remain subject to the stream's eager JSON validation.
    """

    if not isinstance(value, Mapping):
        raise TypeError("narration evidence must be a mapping")
    return {str(key): _json_value(item) for key, item in value.items()}


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value

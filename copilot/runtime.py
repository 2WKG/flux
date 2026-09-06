"""Route-free, injected runtime for the ordered Copilot SSE contract."""

from __future__ import annotations

import asyncio
from asyncio import CancelledError
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from copilot.narration import GroundedNarration
from copilot.sse import CopilotEventStream, SseEvent


class NarrationProvider(Protocol):
    """An injected provider; tests use deterministic local implementations."""

    def text(self, narration: GroundedNarration) -> Iterable[str]: ...


class AsyncNarrationProvider(Protocol):
    """Cooperative provider used by the HTTP stream path."""

    def text(self, narration: GroundedNarration) -> AsyncIterator[str]: ...


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


async def stream_turn(
    provider: AsyncNarrationProvider | None,
    turn: ToolTurn,
    *,
    stream: CopilotEventStream | None = None,
    include_lifecycle: bool = True,
) -> AsyncIterator[SseEvent]:
    """Yield a turn as it runs, leaving transport heartbeats unblocked.

    ``run_turn`` remains the synchronous deterministic test adapter. HTTP
    transports use this cooperative iterator: a deployment provider must yield
    asynchronously, so the event loop can send heartbeats and propagate a
    disconnect without pretending that an arbitrary worker thread was stopped.
    """

    active = stream or CopilotEventStream()
    if include_lifecycle:
        yield active.start()
    yield active.tool_call(turn.call_id, turn.tool, turn.input)
    if turn.narration.status == "unavailable":
        yield active.error(
            "unavailable",
            turn.narration.text,
            retryable=turn.narration.unavailable.retryable,
        )
        return
    yield active.tool_result(
        turn.call_id,
        turn.tool,
        _json_ready(turn.narration.evidence),
        elapsed_ms=turn.elapsed_ms,
    )
    for index, hit in enumerate(turn.narration.citations, 1):
        yield active.citation(
            f"{turn.call_id}:cite:{index}", hit.model_dump(mode="json")
        )
    if provider is None:
        yield active.error(
            "unavailable", "No model provider is configured.", retryable=False
        )
        return

    iterator: AsyncIterator[str] | None = None
    try:
        iterator = provider.text(turn.narration)
        async for delta in iterator:
            yield active.text(delta)
    except CancelledError:
        if asyncio.current_task() is not None and asyncio.current_task().cancelling():
            await _close_iterator(iterator)
            raise
        yield active.error("cancelled", "The answer was cancelled.", retryable=True)
        return
    except Exception:  # noqa: BLE001 - provider setup must become a safe terminal.
        yield active.error(
            "upstream_error", "The model provider failed.", retryable=False
        )
        return
    yield active.done(verified=True)


async def _close_iterator(iterator: AsyncIterator[str] | None) -> None:
    closer = getattr(iterator, "aclose", None)
    if closer is not None:
        try:
            await closer()
        except Exception:  # noqa: BLE001 - disconnect cleanup must not replace cancellation.
            return


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

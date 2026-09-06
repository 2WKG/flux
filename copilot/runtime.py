"""Route-free, injected runtime for the ordered Copilot SSE contract.

``run_turn`` is synchronous and returns the whole event tuple: it is a
fixture-grade driver for the emitter contract, not the streaming ``/ask``
loop.  A route that must deliver ``text`` incrementally (and propagate task
cancellation) needs a generator built on the same emitter.
"""

from __future__ import annotations

import asyncio
from asyncio import CancelledError
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from copilot.narration import GroundedNarration
from copilot.sse import CopilotEventStream, SseEvent
from copilot.tools.schemas import RetrievalHit, UnavailableCode
from copilot.verify import verify


class NarrationProvider(Protocol):
    """An injected provider; tests use deterministic local implementations."""

    def text(self, narration: GroundedNarration) -> Iterable[str]: ...


class AsyncNarrationProvider(Protocol):
    """Cooperative provider used by the HTTP streaming transport."""

    def text(self, narration: GroundedNarration) -> AsyncIterator[str]: ...


@dataclass(frozen=True)
class ToolTurn:
    call_id: str
    tool: str
    input: Mapping[str, object]
    narration: GroundedNarration
    elapsed_ms: int = 0


# A tool's ``unavailable.reason`` is tool-authored text that may name files or
# internals.  It stays server-side; the wire carries a fixed code and message.
_TOOL_FAILURES: dict[UnavailableCode, tuple[str, str]] = {
    "artifact_unavailable": (
        "unavailable",
        "A required data artifact is not available.",
    ),
    "invalid_prerequisite": (
        "tool_error",
        "The tool could not validate its inputs or prerequisites.",
    ),
    "unsupported_request": (
        "invalid_input",
        "The tool does not support this request.",
    ),
    "insufficient_evidence": (
        "tool_error",
        "The tool found no evidence for this request.",
    ),
}
_TOOL_UNAVAILABLE_MESSAGE = (
    "A required tool result is unavailable, so no answer was produced."
)
_NO_PROVIDER_MESSAGE = "No model provider is configured."
_EMPTY_ANSWER_MESSAGE = "The model produced no answer."


def run_turn(
    provider: NarrationProvider | None, turn: ToolTurn
) -> tuple[SseEvent, ...]:
    """Build an ordered stream without calling a network provider itself."""
    stream = CopilotEventStream()
    events = [stream.start(), stream.tool_call(turn.call_id, turn.tool, turn.input)]
    narration = turn.narration
    if narration.status == "unavailable":
        unavailable = narration.unavailable
        if unavailable is None:  # pragma: no cover - GroundedNarration forbids it
            raise ValueError("unavailable narration carries no unavailable reason")
        code, message = _TOOL_FAILURES[unavailable.code]
        events.append(
            stream.failed_tool_result(
                turn.call_id, turn.tool, code, message, elapsed_ms=turn.elapsed_ms
            )
        )
        events.append(
            stream.error(
                "unavailable",
                _TOOL_UNAVAILABLE_MESSAGE,
                retryable=unavailable.retryable,
            )
        )
        return tuple(events)

    evidence = _thaw_mapping(narration.evidence)
    events.append(
        stream.tool_result(
            turn.call_id, turn.tool, evidence, elapsed_ms=turn.elapsed_ms
        )
    )
    for index, hit in enumerate(narration.citations, 1):
        events.append(
            stream.citation(f"{turn.call_id}:cite:{index}", _citation_payload(hit))
        )
    if provider is None:
        events.append(
            stream.error("unavailable", _NO_PROVIDER_MESSAGE, retryable=False)
        )
        return tuple(events)

    # Only the provider call is guarded: the emitter's own contract errors below
    # are programming errors and must not be relabelled as provider failures.
    try:
        deltas = [delta for delta in provider.text(narration) if delta]
    except CancelledError as exc:
        events.append(stream.disconnected(exc))
        return tuple(events)
    except Exception as exc:  # noqa: BLE001 - provider exceptions become fixed terminals.
        events.append(stream.provider_failed(exc))
        return tuple(events)
    if not deltas:
        events.append(
            stream.error("upstream_error", _EMPTY_ANSWER_MESSAGE, retryable=True)
        )
        return tuple(events)

    for delta in deltas:
        events.append(stream.text(delta))
    report = verify("".join(deltas), [evidence], narration.citations)
    events.append(
        stream.done(
            verified=report.verified,
            unverified_numbers=report.unverified_numbers,
            unverified_citations=report.unverified_citations,
            reason=report.reason,
        )
    )
    return tuple(events)


async def stream_turn(
    provider: AsyncNarrationProvider | None,
    turn: ToolTurn,
    *,
    stream: CopilotEventStream | None = None,
    include_lifecycle: bool = True,
) -> AsyncIterator[SseEvent]:
    """Yield one turn through the same safe emitter contract as ``run_turn``.

    The HTTP route uses cooperative injected boundaries: provider deltas are
    yielded as they arrive, permitting heartbeat and disconnect tasks to run.
    A real response-task cancellation is re-raised after iterator cleanup; a
    provider-raised cancellation remains the documented terminal event.
    """

    active = stream or CopilotEventStream()
    if include_lifecycle:
        yield active.start()
    yield active.tool_call(turn.call_id, turn.tool, turn.input)
    narration = turn.narration
    if narration.status == "unavailable":
        unavailable = narration.unavailable
        if unavailable is None:  # pragma: no cover - GroundedNarration forbids it
            raise ValueError("unavailable narration carries no unavailable reason")
        code, message = _TOOL_FAILURES[unavailable.code]
        yield active.failed_tool_result(
            turn.call_id, turn.tool, code, message, elapsed_ms=turn.elapsed_ms
        )
        yield active.error(
            "unavailable",
            _TOOL_UNAVAILABLE_MESSAGE,
            retryable=unavailable.retryable,
        )
        return

    evidence = _thaw_mapping(narration.evidence)
    yield active.tool_result(
        turn.call_id, turn.tool, evidence, elapsed_ms=turn.elapsed_ms
    )
    for index, hit in enumerate(narration.citations, 1):
        yield active.citation(f"{turn.call_id}:cite:{index}", _citation_payload(hit))
    if provider is None:
        yield active.error("unavailable", _NO_PROVIDER_MESSAGE, retryable=False)
        return

    iterator: AsyncIterator[str] | None = None
    deltas: list[str] = []
    try:
        iterator = provider.text(narration)
        async for delta in iterator:
            if delta:
                deltas.append(delta)
                yield active.text(delta)
    except CancelledError as exc:
        if asyncio.current_task() is not None and asyncio.current_task().cancelling():
            await _close_iterator(iterator)
            raise
        yield active.disconnected(exc)
        return
    except Exception as exc:  # noqa: BLE001 - provider exceptions become fixed terminals.
        yield active.provider_failed(exc)
        return
    if not deltas:
        yield active.error("upstream_error", _EMPTY_ANSWER_MESSAGE, retryable=True)
        return

    report = verify("".join(deltas), [evidence], narration.citations)
    yield active.done(
        verified=report.verified,
        unverified_numbers=report.unverified_numbers,
        unverified_citations=report.unverified_citations,
        reason=report.reason,
    )


async def _close_iterator(iterator: AsyncIterator[str] | None) -> None:
    closer = getattr(iterator, "aclose", None)
    if closer is not None:
        try:
            await closer()
        except Exception:  # noqa: BLE001 - disconnect cleanup must not replace cancellation.
            return


def _citation_payload(hit: RetrievalHit) -> dict[str, Any]:
    """Map a ``cite`` hit onto the documented citation wire fields only."""
    return {
        "doc": hit.doc,
        "title": hit.title,
        "page": hit.page,
        "chunk_id": hit.chunk_id,
        "locator": hit.locator,
        "excerpt": hit.text,
        "url": hit.source,
    }


def _thaw_mapping(value: Mapping[str, object]) -> dict[str, Any]:
    thawed = _thaw(value)
    if not isinstance(thawed, dict):  # pragma: no cover - Mapping input by type
        raise TypeError("evidence must be a mapping")
    return thawed


def _thaw(value: object) -> object:
    """Recursively turn frozen evidence (proxies, tuples) into JSON-ready values."""
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value

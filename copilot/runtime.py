"""Route-free, injected runtime for the ordered Copilot SSE contract.

``run_turn`` is synchronous and returns the whole event tuple: it is a
fixture-grade driver for the emitter contract, not the streaming ``/ask``
loop.  A route that must deliver ``text`` incrementally (and propagate task
cancellation) needs a generator built on the same emitter.
"""

from __future__ import annotations

from asyncio import CancelledError
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from copilot.narration import GroundedNarration
from copilot.sse import CopilotEventStream, SseEvent
from copilot.tools.schemas import RetrievalHit, UnavailableCode
from copilot.verify import verify


class NarrationProvider(Protocol):
    """An injected provider; tests use deterministic local implementations."""

    def text(self, narration: GroundedNarration) -> Iterable[str]: ...


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

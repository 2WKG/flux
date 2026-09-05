"""Ordered SSE event primitives for one Copilot answer attempt.

This module deliberately owns only event construction and serialization.  It
does not call a provider, execute a tool, or expose an HTTP route.  Those
layers supply the data and use :class:`CopilotEventStream` to preserve the
wire-level ordering contract.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

SCHEMA_VERSION = 1

_TERMINAL_FAILURES = {
    "disconnect": (
        "cancelled",
        "The answer attempt was cancelled before it completed.",
        True,
    ),
    "timeout": (
        "deadline",
        "The answer could not finish within the request deadline.",
        True,
    ),
    "provider": (
        "upstream_error",
        "The answer provider is unavailable.",
        True,
    ),
    "refusal": (
        "refusal",
        "The answer provider declined this request.",
        False,
    ),
    "iteration_limit": (
        "deadline",
        "The answer reached its iteration limit.",
        False,
    ),
}

_TOOL_ERROR_CODES = frozenset({"timeout", "invalid_input", "unavailable", "tool_error"})
_MAX_TOOL_ERROR_MESSAGE_CHARS = 1024


class StreamStateError(RuntimeError):
    """An event would violate an answer attempt's lifecycle."""


@dataclass(frozen=True, slots=True)
class SseEvent:
    """One already-ordered application event in the documented SSE shape."""

    event: str
    seq: int
    data: Mapping[str, Any]

    def encode(self) -> str:
        """Render one complete SSE record with a single JSON ``data`` line."""
        encoded = json.dumps(
            dict(self.data), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        return f"id: {self.seq}\nevent: {self.event}\ndata: {encoded}\n\n"


class CopilotEventStream:
    """Build the lifecycle and tool events for one answer attempt.

    ``start`` must be the first application event.  Tool results bind to an
    earlier call id and use the same tool name; failed tool results are
    non-terminal and allow the stream to continue.  ``done`` is the only
    success terminal event and closes the stream permanently.  Named failure
    methods emit only fixed, user-safe terminal errors; callers must not
    expose their caught provider exception text in stream data.
    """

    def __init__(self) -> None:
        self._next_seq = 1
        self._started = False
        self._terminal = False
        self._pending_calls: dict[str, str] = {}

    def start(self) -> SseEvent:
        """Emit the first lifecycle event for this answer attempt."""
        if self._started:
            raise StreamStateError("a stream can emit lifecycle start only once")
        event = self._event("lifecycle", {"status": "started"})
        self._started = True
        return event

    def tool_call(self, call_id: str, tool: str, input: Mapping[str, Any]) -> SseEvent:
        """Emit an observable, validated tool invocation start."""
        self._require_active()
        if not call_id:
            raise ValueError("call_id must not be empty")
        if not tool:
            raise ValueError("tool must not be empty")
        if call_id in self._pending_calls:
            raise StreamStateError(f"tool call {call_id!r} was already emitted")
        event = self._event(
            "tool_call", {"call_id": call_id, "tool": tool, "input": dict(input)}
        )
        self._pending_calls[call_id] = tool
        return event

    def tool_result(
        self,
        call_id: str,
        tool: str,
        result: Mapping[str, Any],
        *,
        elapsed_ms: int,
    ) -> SseEvent:
        """Emit the successful outcome for one previously emitted tool call."""
        self._validate_tool_call(call_id, tool)
        if elapsed_ms < 0:
            raise ValueError("elapsed_ms must be non-negative")
        event = self._event(
            "tool_result",
            {
                "call_id": call_id,
                "tool": tool,
                "ok": True,
                "result": dict(result),
                "elapsed_ms": elapsed_ms,
            },
        )
        del self._pending_calls[call_id]
        return event

    def failed_tool_result(
        self,
        call_id: str,
        tool: str,
        code: str,
        message: str,
        *,
        elapsed_ms: int,
    ) -> SseEvent:
        """Emit a failed outcome for one previously emitted tool call.

        The stream remains active and can accept further tool calls or done().
        Codes are a small fixed vocabulary and messages are bounded so callers
        cannot turn a tool error into an unbounded exception transport.
        """
        # Bound the caller-supplied fields before consuming the pending call so a
        # rejected payload leaves the call settleable with a valid one.
        if code not in _TOOL_ERROR_CODES:
            raise ValueError(f"unsupported tool error code: {code!r}")
        if not message or len(message) > _MAX_TOOL_ERROR_MESSAGE_CHARS:
            raise ValueError(
                f"tool error message must be 1..{_MAX_TOOL_ERROR_MESSAGE_CHARS} characters"
            )
        if elapsed_ms < 0:
            raise ValueError("elapsed_ms must be non-negative")
        event = self._event(
            "tool_result",
            {
                "call_id": call_id,
                "tool": tool,
                "ok": False,
                "error": {"code": code, "message": message},
                "elapsed_ms": elapsed_ms,
            },
        )
        del self._pending_calls[call_id]
        return event

    def done(
        self,
        *,
        verified: bool,
        unverified_numbers: Sequence[str] = (),
        usage: Mapping[str, int] | None = None,
    ) -> SseEvent:
        """Emit the one successful terminal event and permanently close it."""
        self._require_active()
        if self._pending_calls:
            raise StreamStateError(
                "a stream cannot finish while tool calls are pending"
            )
        if any(not number for number in unverified_numbers):
            raise ValueError("unverified_numbers must not contain empty strings")
        data: dict[str, Any] = {
            "status": "completed",
            "verified": verified,
            "unverified_numbers": list(unverified_numbers),
        }
        if usage is not None:
            data["usage"] = dict(usage)
        event = self._event("done", data)
        self._terminal = True
        return event

    def disconnected(self, cause: BaseException | None = None) -> SseEvent:
        """End an active stream after a client disconnect without leaking ``cause``."""
        return self._failure("disconnect", cause)

    def timed_out(self, cause: BaseException | None = None) -> SseEvent:
        """End an active stream after its deadline without leaking ``cause``."""
        return self._failure("timeout", cause)

    def provider_failed(self, cause: BaseException | None = None) -> SseEvent:
        """End an active stream after an upstream failure without leaking ``cause``."""
        return self._failure("provider", cause)

    def refused(self, cause: BaseException | None = None) -> SseEvent:
        """End an active stream after a provider refusal without leaking ``cause``."""
        return self._failure("refusal", cause)

    def iteration_limit_reached(self, cause: BaseException | None = None) -> SseEvent:
        """End an active stream after exhausting the fixed model-turn budget."""
        return self._failure("iteration_limit", cause)

    def _validate_tool_call(self, call_id: str, tool: str) -> None:
        """Validate a pending tool call without leaking details."""
        self._require_active()
        expected_tool = self._pending_calls.get(call_id)
        if expected_tool is None:
            raise StreamStateError(f"tool result {call_id!r} has no pending tool call")
        if tool != expected_tool:
            raise StreamStateError(
                f"tool result {call_id!r} names {tool!r}, expected {expected_tool!r}"
            )

    def _require_active(self) -> None:
        if not self._started:
            raise StreamStateError(
                "lifecycle start must be emitted before other events"
            )
        if self._terminal:
            raise StreamStateError("no application event may follow a terminal event")

    def _failure(self, kind: str, cause: BaseException | None) -> SseEvent:
        """Emit a fixed terminal error and intentionally discard raw failure detail."""
        self._require_active()
        del cause
        code, message, retryable = _TERMINAL_FAILURES[kind]
        event = self._event(
            "error",
            {
                "status": "failed",
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                },
            },
        )
        self._terminal = True
        return event

    def _event(self, event: str, data: Mapping[str, Any]) -> SseEvent:
        seq = self._next_seq
        envelope = {"v": SCHEMA_VERSION, "seq": seq, **data}
        # Serialize eagerly so malformed/non-finite values cannot enter a stream.
        json.dumps(envelope, ensure_ascii=False, allow_nan=False)
        self._next_seq += 1
        return SseEvent(event=event, seq=seq, data=MappingProxyType(envelope))

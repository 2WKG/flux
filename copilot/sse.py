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

# The closed v1 ``error.code`` set from docs/research/sse-event-schema.md.
_ERROR_CODES = frozenset(
    {
        "invalid_request",
        "unavailable",
        "deadline",
        "upstream_error",
        "tool_error",
        "refusal",
        "cancelled",
        "protocol_error",
    }
)
_MAX_ERROR_MESSAGE_CHARS = 1024

_CITATION_IDENTITY_FIELDS = ("doc", "title", "chunk_id")
_CITATION_OPTIONAL_FIELDS = ("locator", "excerpt", "url")
_CITATION_FIELDS = frozenset(
    ("page", *_CITATION_IDENTITY_FIELDS, *_CITATION_OPTIONAL_FIELDS)
)
_MAX_CITATION_EXCERPT_CHARS = 1200


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
    methods emit only fixed, user-safe terminal errors, and ``error`` accepts
    only the documented closed code set with a bounded message; callers must
    not expose their caught provider exception text in stream data.
    """

    def __init__(self) -> None:
        self._next_seq = 1
        self._started = False
        self._terminal = False
        self._pending_calls: dict[str, str] = {}
        self._citation_ids: set[str] = set()

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

    def text(self, delta: str) -> SseEvent:
        """Emit one non-empty, already-grounded display fragment."""
        self._require_active()
        if not delta:
            raise ValueError("text delta must not be empty")
        return self._event("text", {"delta": delta})

    def citation(self, citation_id: str, hit: Mapping[str, Any]) -> SseEvent:
        """Emit one documented citation for a hit the caller accepted from ``cite``.

        ``hit`` carries only the wire fields (``doc``, ``title``, ``page``,
        ``chunk_id`` and optional ``locator``/``excerpt``/``url``); a raw
        retrieval record must be mapped first so backend-only fields never
        reach the browser and no hit field can overwrite the envelope.
        """
        self._require_active()
        if not isinstance(citation_id, str) or not citation_id:
            raise ValueError("citation_id must be a non-empty string")
        if citation_id in self._citation_ids:
            raise StreamStateError(f"citation {citation_id!r} was already emitted")
        unknown = sorted(set(hit) - _CITATION_FIELDS)
        if unknown:
            raise ValueError(f"citation carries undocumented fields: {unknown}")
        for key in _CITATION_IDENTITY_FIELDS:
            value = hit.get(key)
            if not isinstance(value, str) or not value:
                raise ValueError(f"citation requires a non-empty string {key!r}")
        page = hit.get("page")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError("citation requires a positive integer page")
        payload: dict[str, Any] = {
            "citation_id": citation_id,
            "doc": hit["doc"],
            "title": hit["title"],
            "page": page,
            "chunk_id": hit["chunk_id"],
        }
        for key in _CITATION_OPTIONAL_FIELDS:
            value = hit.get(key)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"citation {key!r} must be a string or null")
            payload[key] = value
        excerpt = payload["excerpt"]
        if excerpt is not None and len(excerpt) > _MAX_CITATION_EXCERPT_CHARS:
            payload["excerpt"] = excerpt[:_MAX_CITATION_EXCERPT_CHARS]
            payload["excerpt_truncated"] = True
        event = self._event("citation", payload)
        self._citation_ids.add(citation_id)
        return event

    def error(self, code: str, message: str, *, retryable: bool) -> SseEvent:
        """Emit the failure terminal for a documented code with a fixed message.

        ``code`` must be one of the closed v1 codes and ``message`` must be a
        bounded, caller-fixed user-facing string -- never formatted exception
        text.  Pending tool calls are abandoned (disconnect-wins semantics).
        """
        if code not in _ERROR_CODES:
            raise ValueError(f"unsupported error code: {code!r}")
        if not message or len(message) > _MAX_ERROR_MESSAGE_CHARS:
            raise ValueError(
                f"error message must be 1..{_MAX_ERROR_MESSAGE_CHARS} characters"
            )
        return self._terminal_error(code, message, retryable)

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
        self._validate_tool_call(call_id, tool)
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
        unverified_citations: Sequence[str] = (),
        reason: str | None = None,
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
        if any(not marker for marker in unverified_citations):
            raise ValueError("unverified_citations must not contain empty strings")
        if verified and (unverified_numbers or unverified_citations or reason):
            raise ValueError("a verified answer cannot carry unverified findings")
        data: dict[str, Any] = {
            "status": "completed",
            "verified": verified,
            "unverified_numbers": list(unverified_numbers),
        }
        if unverified_citations:
            data["unverified_citations"] = list(unverified_citations)
        if reason is not None:
            data["reason"] = reason
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
        """End an active stream after exhausting its budget; both limits use deadline."""
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
        del cause
        code, message, retryable = _TERMINAL_FAILURES[kind]
        return self._terminal_error(code, message, retryable)

    def _terminal_error(self, code: str, message: str, retryable: bool) -> SseEvent:
        """The one failure terminal: closes the stream like ``done`` does."""
        self._require_active()
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
        if "v" in data or "seq" in data:
            raise ValueError("event data cannot override the envelope fields")
        seq = self._next_seq
        envelope = {"v": SCHEMA_VERSION, "seq": seq, **data}
        # Serialize eagerly so malformed/non-finite values cannot enter a stream.
        json.dumps(envelope, ensure_ascii=False, allow_nan=False)
        self._next_seq += 1
        return SseEvent(event=event, seq=seq, data=MappingProxyType(envelope))

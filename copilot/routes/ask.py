"""Injected, local-only HTTP transport for the Copilot v1 SSE attempt contract."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Iterable
from typing import Annotated, Protocol

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from copilot.runtime import AsyncNarrationProvider, ToolTurn, stream_turn
from copilot.sse import CopilotEventStream, SseEvent

router = APIRouter(tags=["ask"])

_ATTEMPT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
HEARTBEAT_SECONDS = 15


class AskContext(BaseModel):
    """Optional selected-state inputs, passed to an injected local backend."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str | None = Field(default=None, min_length=1, max_length=128)
    hour: int | None = Field(default=None, ge=0, le=167)
    selected_site_id: str | None = Field(default=None, min_length=1, max_length=128)
    compare_site_id: str | None = Field(default=None, min_length=1, max_length=128)
    selected_element_id: str | None = Field(default=None, min_length=1, max_length=128)
    unit_mw: int | None = Field(default=None)

    @model_validator(mode="after")
    def _valid_unit(self) -> AskContext:
        if self.unit_mw is not None and self.unit_mw not in {300, 1000}:
            raise ValueError("unit_mw must be 300 or 1000")
        return self


class AskHistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Annotated[str, Field(pattern=r"^(user|assistant)$")]
    content: Annotated[str, Field(min_length=1, max_length=4_000)]


class AskRequest(BaseModel):
    """The exact POST-resume identity and bounded conversational input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: Annotated[str, Field(min_length=16, max_length=128)]
    question: Annotated[str, Field(min_length=1, max_length=2_000)]
    context: AskContext | None = None
    history: Annotated[list[AskHistoryMessage], Field(max_length=6)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def _valid_attempt(self) -> AskRequest:
        if not _ATTEMPT_ID_RE.fullmatch(self.attempt_id):
            raise ValueError("attempt_id must be URL-safe ASCII")
        return self


class AskBackend(Protocol):
    """A deployment-injected local tool plan; this transport calls no provider."""

    provider: AsyncNarrationProvider | None

    async def turn(self, payload: AskRequest) -> ToolTurn: ...


def _unavailable_events(message: str) -> tuple[SseEvent, ...]:
    stream = CopilotEventStream()
    return (
        stream.start(),
        stream.error("unavailable", message, retryable=False),
    )


def _encoded_events(events: Iterable[SseEvent]) -> AsyncIterator[ServerSentEvent]:
    async def iterator() -> AsyncIterator[ServerSentEvent]:
        for event in events:
            # EventSourceResponse writes the single JSON data line; the stream
            # object already established contiguous id/seq and eager JSON safety.
            yield ServerSentEvent(
                event=event.event,
                id=str(event.seq),
                data=json.dumps(
                    dict(event.data), ensure_ascii=False, separators=(",", ":")
                ),
            )

    return iterator()


def _encoded_event(event: SseEvent) -> ServerSentEvent:
    return ServerSentEvent(
        event=event.event,
        id=str(event.seq),
        data=json.dumps(dict(event.data), ensure_ascii=False, separators=(",", ":")),
    )


async def _stream_backend(
    backend: AskBackend, payload: AskRequest
) -> AsyncIterator[ServerSentEvent]:
    """Start the SSE lifecycle before local work so ping/disconnect stay live."""

    stream = CopilotEventStream()
    yield _encoded_event(stream.start())
    try:
        turn = await backend.turn(payload)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - do not disclose local backend failures.
        yield _encoded_event(
            stream.error(
                "tool_error", "The local Copilot backend failed.", retryable=False
            )
        )
        return
    async for event in stream_turn(
        backend.provider, turn, stream=stream, include_lifecycle=False
    ):
        yield _encoded_event(event)


def _heartbeat() -> ServerSentEvent:
    """A transport-only comment: it deliberately has no application id."""

    return ServerSentEvent(comment="keepalive")


@router.post("/ask")
def ask(
    payload: AskRequest,
    request: Request,
    last_event_id: Annotated[str | None, Header()] = None,
) -> EventSourceResponse:
    """Stream one injected local tool turn, or an explicit unavailable terminal.

    Replay storage is intentionally not present in this weekend backend. A
    syntactically valid resume request is therefore rejected before streaming;
    it must never repeat work under the same attempt id.
    """

    if last_event_id is not None:
        # A replay store is optional v1 infrastructure.  Treat malformed ids
        # and all otherwise valid resumes distinctly so callers never mistake a
        # new stream for a replay of a non-idempotent attempt.
        if not last_event_id.isdecimal() or int(last_event_id) < 1:
            from copilot.api import InvalidInputError

            raise InvalidInputError("Last-Event-ID must be a positive decimal id.")
        from copilot.api import UnavailableError

        raise UnavailableError("SSE replay is not available for this attempt.")

    backend = getattr(request.app.state, "ask_backend", None)
    if backend is None:
        events = _unavailable_events("The local Copilot backend is not configured.")
        content = _encoded_events(events)
    else:
        content = _stream_backend(backend, payload)
    # Run metadata, not stream data: the SSE event vocabulary stays identical
    # across providers, and these headers are deliberately absent from the CORS
    # expose list, so the browser cannot branch on which model answered while an
    # operator reading the response still can.
    headers = {"X-Flux-Attempt-Id": payload.attempt_id}
    settings = getattr(request.app.state, "settings", None)
    if settings is not None:
        status = settings.provider_status()
        headers["X-Flux-Copilot-Provider"] = status.provider
        headers["X-Flux-Copilot-Model"] = status.model
    return EventSourceResponse(
        content,
        headers=headers,
        ping=HEARTBEAT_SECONDS,
        ping_message_factory=_heartbeat,
    )

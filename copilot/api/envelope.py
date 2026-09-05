"""Versioned response envelopes for the read-only Copilot HTTP surface.

Only the failure envelope is returned from routes. An absent, stale, or unbuilt
artifact is a failure envelope — never an empty successful result. Route
payloads are unwrapped: bare arrays, equality-tested tool-dict pass-throughs,
Arrow IPC bytes.

This module owns contracts only; DuckDB access, retrieval, and route handlers
belong to their own units. Envelopes are closed to unknown fields so a raw
DuckDB error, exception text, or credential cannot ride along in a response.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

API_VERSION = "v1"
"""Envelope version. Bump on any breaking change to the shapes below."""

type ResponseStatus = Literal["unavailable", "error"]
type FailureCode = Literal[
    "unavailable",
    "invalid_input",
    "not_found",
    "internal_error",
]


class EnvelopeModel(BaseModel):
    """Base model that rejects fields outside the declared contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ResponseMeta(EnvelopeModel):
    """Envelope metadata carried by failure responses."""

    api_version: Annotated[str, Field(min_length=1, max_length=16)] = API_VERSION
    request_id: Annotated[str, Field(min_length=1, max_length=64)]
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware UTC")
        return value.astimezone(UTC)


class Failure(EnvelopeModel):
    """Typed failure body: stable code, safe message, retry guidance."""

    code: FailureCode
    message: Annotated[str, Field(min_length=1, max_length=1_024)]
    retryable: bool
    retry_after_s: Annotated[int | None, Field(ge=1, le=3_600)] = None
    details: Annotated[dict[str, str], Field(default_factory=dict, max_length=10)]


class FailureEnvelope(EnvelopeModel):
    status: Literal["unavailable", "error"]
    data: None = None
    error: Failure
    meta: ResponseMeta

"""Versioned response envelopes for the read-only Copilot HTTP surface.

Every route returns one of two shapes at the top level: a success envelope with
``status="ok"`` and a typed ``data`` payload, or a failure envelope with
``status="unavailable"`` or ``status="error"``, ``data=None`` and a typed
``error``. An absent, stale, or unbuilt artifact is a failure envelope — never
an empty successful result.

This module owns contracts only; DuckDB access, retrieval, and route handlers
belong to their own units. Envelopes are closed to unknown fields so a raw
DuckDB error, exception text, or credential cannot ride along in a response.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

API_VERSION = "v1"
"""Envelope version. Bump on any breaking change to the shapes below."""

type ResponseStatus = Literal["ok", "unavailable", "error"]
type FailureCode = Literal[
    "unavailable",
    "invalid_input",
    "not_found",
    "internal_error",
]

_MAX_DETAIL_KEYS = 10
_MAX_DETAIL_VALUE_CHARS = 200
_DENIED_DETAIL_KEY_PARTS = (
    "credential",
    "dsn",
    "duckdb",
    "env",
    "key",
    "password",
    "path",
    "query",
    "secret",
    "sql",
    "token",
    "traceback",
    "url",
)

T = TypeVar("T")


def safe_details(details: dict[str, Any] | None) -> dict[str, str]:
    """Reduce caller-supplied details to short, non-sensitive strings.

    Keys whose name suggests a secret, connection string, filesystem path, or
    raw SQL are dropped rather than redacted, values are stringified and
    truncated, and the map is capped. Detail maps are for stable hints such as
    ``{"field": "scenario_id"}`` — never for exception or driver text.
    """
    if not details:
        return {}
    safe: dict[str, str] = {}
    for key, value in details.items():
        lowered = key.lower()
        if any(part in lowered for part in _DENIED_DETAIL_KEY_PARTS):
            continue
        text = value if isinstance(value, str) else str(value)
        if len(text) > _MAX_DETAIL_VALUE_CHARS:
            text = text[:_MAX_DETAIL_VALUE_CHARS] + "…"
        safe[key] = text
        if len(safe) == _MAX_DETAIL_KEYS:
            break
    return safe


class EnvelopeModel(BaseModel):
    """Base model that rejects fields outside the declared contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactRef(EnvelopeModel):
    """Provenance for one artifact that backed the response."""

    artifact_id: Annotated[str, Field(min_length=1, max_length=256)]
    artifact_version: Annotated[str, Field(min_length=1, max_length=256)]
    source_kind: Literal["fixture", "observed", "simulated", "heuristic", "retrieval"]


class ResponseMeta(EnvelopeModel):
    """Envelope metadata carried by success and failure responses alike."""

    api_version: Annotated[str, Field(min_length=1, max_length=16)] = API_VERSION
    request_id: Annotated[str, Field(min_length=1, max_length=64)]
    generated_at: datetime
    artifacts: tuple[ArtifactRef, ...] = ()
    partial: bool = False

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
    details: dict[str, str] = Field(default_factory=dict)


class SuccessEnvelope(EnvelopeModel, Generic[T]):
    status: Literal["ok"] = "ok"
    data: T
    meta: ResponseMeta


class FailureEnvelope(EnvelopeModel):
    status: Literal["unavailable", "error"]
    data: None = None
    error: Failure
    meta: ResponseMeta


def response_meta(
    request_id: str,
    *,
    artifacts: tuple[ArtifactRef, ...] = (),
    partial: bool = False,
    generated_at: datetime | None = None,
) -> ResponseMeta:
    return ResponseMeta(
        request_id=request_id,
        generated_at=generated_at or datetime.now(UTC),
        artifacts=artifacts,
        partial=partial,
    )


def success(
    data: T,
    *,
    request_id: str,
    artifacts: tuple[ArtifactRef, ...] = (),
    partial: bool = False,
    generated_at: datetime | None = None,
) -> SuccessEnvelope[T]:
    """Wrap a payload that is genuinely present in the success envelope."""
    return SuccessEnvelope[T](
        data=data,
        meta=response_meta(
            request_id,
            artifacts=artifacts,
            partial=partial,
            generated_at=generated_at,
        ),
    )

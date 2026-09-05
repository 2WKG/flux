"""Small, provider-neutral boundary for Copilot model configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os


PROVIDER = "anthropic"
MODEL_ID = "claude-opus-5"
API_VERSION: str | None = None
REQUEST_TIMEOUT_S = 30
MAX_RETRIES = 0


class ProviderState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class ProviderStatus:
    state: ProviderState
    code: str


def configured_model(environ: dict[str, str] | None = None) -> str:
    """Return the only configured model; overrides are intentionally unsupported."""
    values = os.environ if environ is None else environ
    requested = values.get("COPILOT_MODEL", MODEL_ID)
    return requested


def availability(environ: dict[str, str] | None = None, provider_error: str | None = None) -> ProviderStatus:
    """Map configuration and provider failures to safe, displayable states."""
    values = os.environ if environ is None else environ
    if not values.get("ANTHROPIC_API_KEY"):
        return ProviderStatus(ProviderState.UNAVAILABLE, "missing_credentials")
    if configured_model(values) != MODEL_ID:
        return ProviderStatus(ProviderState.UNAVAILABLE, "unsupported_model")
    if provider_error in {"quota", "rate_limit"}:
        return ProviderStatus(ProviderState.UNAVAILABLE, "quota_exhausted")
    if provider_error:
        return ProviderStatus(ProviderState.ERROR, "provider_error")
    return ProviderStatus(ProviderState.AVAILABLE, "ready")

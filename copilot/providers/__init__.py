"""Provider selection for the Copilot narration boundary.

Two adapters implement the one `AsyncNarrationProvider` protocol.  Which one
runs is configuration (`COPILOT_PROVIDER`), resolved once at construction.
There is no automatic cross-provider fallback: if the selected provider is not
configured, `build_narration_provider` returns `None` and the existing
`/ask` path emits the documented unavailable terminal.  Falling back silently
would make it impossible to say which model produced an answer.
"""

from __future__ import annotations

from copilot.config import DEFAULT_PROVIDER_MODELS, ProviderStatus, Settings
from copilot.providers.grounding import SYSTEM_PROMPT, narration_prompt
from copilot.providers.tool_schemas import anthropic_tools, gemini_tools
from copilot.runtime import AsyncNarrationProvider

__all__ = [
    "DEFAULT_PROVIDER_MODELS",
    "SYSTEM_PROMPT",
    "ProviderStatus",
    "anthropic_tools",
    "build_narration_provider",
    "gemini_tools",
    "narration_prompt",
    "provider_statuses",
    "tools_for",
]


def provider_statuses(settings: Settings) -> tuple[ProviderStatus, ...]:
    """Report every supported provider's readiness, independently."""
    return tuple(
        settings.provider_status(name) for name in sorted(DEFAULT_PROVIDER_MODELS)
    )


def tools_for(provider: str) -> list[dict[str, object]]:
    """The frozen tool contract rendered in ``provider``'s schema shape."""
    if provider == "claude":
        return list(anthropic_tools())
    if provider == "gemini":
        return list(gemini_tools())
    raise ValueError(f"unknown copilot provider: {provider!r}")


def build_narration_provider(settings: Settings) -> AsyncNarrationProvider | None:
    """Construct the active provider adapter, or ``None`` when unconfigured.

    Construction opens no network connection, so this stays safe to call at
    startup; a credential is still not evidence that the model answers.
    """
    status = settings.provider_status()
    if not status.ready:
        return None
    api_key = settings.credential_for(status.provider)
    if api_key is None:  # pragma: no cover - `ready` already proved otherwise
        return None
    if status.provider == "claude":
        from copilot.providers.claude import ClaudeNarrationProvider

        return ClaudeNarrationProvider(api_key, status.model)
    from copilot.providers.gemini import GeminiNarrationProvider

    return GeminiNarrationProvider(api_key, status.model)

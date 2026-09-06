"""Configuration and adapter tests that never make a paid provider call.

Everything here proves *ready or unavailable* behaviour and schema/prompt
sharing.  No test constructs a real SDK client or issues a completion.
"""

from __future__ import annotations

import pytest

from copilot.config import DEFAULT_PROVIDER_MODELS, Settings
from copilot.narration import GroundedNarration
from copilot.providers import (
    build_narration_provider,
    provider_statuses,
    tools_for,
)
from copilot.providers.grounding import SYSTEM_PROMPT, narration_prompt
from copilot.tools.schemas import TOOL_SCHEMAS, ArtifactRef

_PROVIDER_ENV = (
    "COPILOT_PROVIDER",
    "COPILOT_MODEL",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "gemini-api-key",
)


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's own credentials must not decide these outcomes."""
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_gemini_is_the_default_provider_with_its_documented_model() -> None:
    settings = _settings()

    assert settings.copilot_provider == "gemini"
    assert settings.provider_status().model == "gemini-3.8-flash"


def test_an_unconfigured_active_provider_is_reported_unavailable() -> None:
    settings = _settings(gemini_api_key=None)

    status = settings.provider_status()

    assert status.ready is False
    assert status.reason == "GEMINI_API_KEY is not set"
    assert settings.model_is_configured is False
    assert build_narration_provider(settings) is None


def test_a_configured_claude_key_does_not_make_the_gemini_default_ready() -> None:
    """No cross-provider fallback: the selected provider is the only one asked."""
    settings = _settings(anthropic_api_key="configured-but-inactive")

    assert settings.provider_status().ready is False
    assert settings.provider_status("claude").ready is True
    assert build_narration_provider(settings) is None


def test_each_provider_reports_readiness_independently() -> None:
    settings = _settings(
        copilot_provider="claude", anthropic_api_key="configured-claude"
    )

    statuses = {status.provider: status for status in provider_statuses(settings)}

    assert set(statuses) == set(DEFAULT_PROVIDER_MODELS)
    assert statuses["claude"].ready is True
    assert statuses["gemini"].ready is False


def test_copilot_model_overrides_only_the_active_provider() -> None:
    settings = _settings(copilot_provider="claude", copilot_model="claude-opus-5")

    assert settings.model_for("claude") == "claude-opus-5"
    assert settings.model_for("gemini") == DEFAULT_PROVIDER_MODELS["gemini"]


def test_the_hyphenated_gemini_key_spelling_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("gemini-api-key", "from-a-local-dotenv")

    assert _settings().provider_status().ready is True


def test_a_provider_status_never_carries_the_credential_value() -> None:
    secret = "never-echoed-secret"
    settings = _settings(copilot_provider="claude", anthropic_api_key=secret)

    assert secret not in repr(settings)
    assert secret not in repr(settings.provider_status())


def test_an_unknown_provider_is_rejected_rather_than_defaulted() -> None:
    with pytest.raises(ValueError):
        tools_for("some-other-vendor")


def test_both_providers_declare_the_same_frozen_tool_contract() -> None:
    claude = tools_for("claude")
    gemini = tools_for("gemini")

    assert [tool["name"] for tool in claude] == [tool["name"] for tool in gemini]
    assert [tool["description"] for tool in claude] == [
        tool["description"] for tool in gemini
    ]
    for contract, rendered in zip(TOOL_SCHEMAS, gemini, strict=True):
        # Only the wrapper differs; the parameter schema is the same object.
        assert rendered["parameters_json_schema"] == contract["input_schema"]


def test_the_gemini_declarations_are_accepted_by_the_sdk_without_a_call() -> None:
    """Schema translation is validated locally; no request is issued."""
    from google.genai import types

    tool = types.Tool(function_declarations=tools_for("gemini"))

    assert [declaration.name for declaration in tool.function_declarations] == [
        schema["name"] for schema in TOOL_SCHEMAS
    ]


def test_the_grounding_prompt_is_shared_and_carries_the_exact_evidence() -> None:
    narration = GroundedNarration(
        status="available",
        text="One persisted line ranking row.",
        evidence={"lines": [{"line_id": "L1", "mw_per_musd": 12.5}]},
        provenance=(
            ArtifactRef(
                artifact_id="line_upgrade_scores",
                artifact_version="1",
                source_kind="fixture",
                source_ref="fixture://lines",
            ),
        ),
        citations=(),
        limitations=("synthetic topology",),
    )

    prompt = narration_prompt(narration)

    assert "12.5" in prompt
    assert "synthetic topology" in prompt
    assert "You never compute" in SYSTEM_PROMPT

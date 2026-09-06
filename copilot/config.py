"""Configuration for the read-only Copilot HTTP service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CopilotProvider = Literal["claude", "gemini"]

# Defaults per provider.  `claude-sonnet-5` is the id in 00-overview §"LLM";
# `gemini-3.8-flash` is the current stable Flash id published at
# https://ai.google.dev/gemini-api/docs/models (fetched 2026-09-06) and returned
# by `google.genai` `client.models.list()` against a developer key.  Neither id
# is invented here, and `COPILOT_MODEL` overrides the active provider default.
DEFAULT_PROVIDER_MODELS: dict[str, str] = {
    "claude": "claude-sonnet-5",
    "gemini": "gemini-3.8-flash",
}


@dataclass(frozen=True)
class ProviderStatus:
    """Whether one provider is locally configured, and which model it would use.

    ``ready`` never means reachable: a configured credential is not evidence
    that a model answers.  ``reason`` names the missing field, never its value.
    """

    provider: str
    model: str
    ready: bool
    reason: str | None = None


class ConfigError(RuntimeError):
    """Raised when local configuration is unusable, naming the offending fields.

    Carries field names only.  Values are never included: ``Settings`` sets
    ``hide_input_in_errors=True`` so that a rejected ``DUCKDB_PATH`` (which can
    carry a token) is not echoed into a traceback, a log, or a terminal.
    """

    def __init__(self, fields: tuple[str, ...], reasons: tuple[str, ...]) -> None:
        self.fields = fields
        self.reasons = reasons
        joined = "; ".join(
            f"{field}: {reason}" for field, reason in zip(fields, reasons)
        )
        super().__init__(f"Invalid Flux configuration -> {joined}")


class Settings(BaseSettings):
    """Runtime settings kept separate from route and provider implementations."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    duckdb_path: Path = Field(default=Path("data/duck/grid.duckdb"))
    # Provider selection is configuration, not code.  There is deliberately no
    # cross-provider fallback: an unconfigured active provider is reported
    # unavailable rather than silently answered by the other one, so a reader
    # can always tell which model produced an answer.
    copilot_provider: CopilotProvider = Field(default="gemini")
    copilot_model: str | None = Field(default=None)
    anthropic_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        # `GEMINI_API_KEY` is the name Google's own quickstart uses; the
        # hyphenated spelling exists in local developer `.env` files here and is
        # not a valid Python identifier, so it is accepted as an alias.
        validation_alias=AliasChoices("GEMINI_API_KEY", "gemini-api-key"),
    )
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)

    @field_validator("duckdb_path", mode="before")
    @classmethod
    def validate_duckdb_path(cls, value: str | Path) -> Path:
        """Reject path forms that cannot be a local read-only DuckDB artifact.

        Existence is deliberately not required here: a missing but otherwise
        valid artifact is reported as the documented unavailable health state.
        """
        value_text = str(value).strip()
        if not value_text:
            raise ValueError("DUCKDB_PATH must be a non-empty local file path")

        # DuckDB reads remote and virtual databases from targets whose first path
        # segment carries a colon: MotherDuck's `md:<db>`, `ducklake:<catalog>`,
        # the in-memory `:memory:`, and any `scheme://host/...` URL.  A `Path`
        # normalises `motherduck://x` to `motherduck:/x`, so the check is on the
        # segment rather than on the `://` spelling.  Opening any of them would
        # take this read-only local service off the filesystem and onto a network.
        if ":" in value_text.split("/", 1)[0]:
            raise ValueError(
                "DUCKDB_PATH must be a local file path, not a DuckDB connection "
                "target (md:, ducklake:, :memory:, or scheme://)"
            )

        path = Path(value_text)
        if path.is_dir():
            raise ValueError("DUCKDB_PATH must name a file, not a directory")
        return path

    def credential_for(self, provider: str) -> str | None:
        """Return the non-empty credential for ``provider``, or ``None``."""
        secret = {
            "claude": self.anthropic_api_key,
            "gemini": self.gemini_api_key,
        }.get(provider)
        value = secret.get_secret_value() if secret is not None else ""
        return value or None

    def model_for(self, provider: str) -> str:
        """Resolve the model id for ``provider``.

        ``COPILOT_MODEL`` overrides only the *active* provider, so pointing it
        at a Claude id cannot silently rename the Gemini model, or vice versa.
        """
        if provider == self.copilot_provider and self.copilot_model:
            return self.copilot_model
        return DEFAULT_PROVIDER_MODELS[provider]

    def provider_status(self, provider: str | None = None) -> ProviderStatus:
        """Report one provider's local readiness independently of the other."""
        name = provider or self.copilot_provider
        if name not in DEFAULT_PROVIDER_MODELS:
            raise ValueError(f"unknown copilot provider: {name!r}")
        model = self.model_for(name)
        if self.credential_for(name) is None:
            field = "ANTHROPIC_API_KEY" if name == "claude" else "GEMINI_API_KEY"
            return ProviderStatus(
                provider=name,
                model=model,
                ready=False,
                reason=f"{field} is not set",
            )
        return ProviderStatus(provider=name, model=model, ready=True)

    @property
    def model_is_configured(self) -> bool:
        """Whether the *active* provider's model and credential are configured."""
        return self.provider_status().ready


def load_settings(**overrides: object) -> Settings:
    """Build ``Settings``, turning a validation failure into a named ``ConfigError``.

    The pydantic ``ValidationError`` is the right thing to raise from a field
    validator, but at the application boundary it reaches an operator as a raw
    traceback out of module import.  This converts it to one loud, named line
    that says which fields are wrong and why, and never what they were set to.
    """
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except ValidationError as error:
        fields: list[str] = []
        reasons: list[str] = []
        for detail in error.errors():
            location = detail.get("loc") or ("<settings>",)
            fields.append(".".join(str(part) for part in location))
            reasons.append(str(detail.get("msg", "invalid value")))
        raise ConfigError(tuple(fields), tuple(reasons)) from None

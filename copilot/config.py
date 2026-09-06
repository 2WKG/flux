"""Configuration for the read-only Copilot HTTP service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CopilotProvider = Literal["claude", "gemini"]
DEFAULT_PROVIDER_MODELS = {"claude": "claude-sonnet-5", "gemini": "gemini-3.8-flash"}


@dataclass(frozen=True)
class ProviderStatus:
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
    physical_inventory_root: Path = Field(
        default=Path("data/artifacts/physical_inventory")
    )
    copilot_provider: CopilotProvider = Field(default="claude")
    copilot_model: str | None = Field(default=None)
    anthropic_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
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
        #
        # A Windows absolute path (`C:\flux\grid.duckdb`) has the same leading
        # colon, so it is admitted only where it really is one: on Windows,
        # where the drive letter makes the value absolute.  `PureWindowsPath`
        # is asked that question directly instead of the ambient `Path`, so the
        # branch is testable off Windows and identical on it.  On POSIX
        # `Z:/x.duckdb` is relative, and admitting it would have the service
        # open a directory literally named `Z:`.  The connection-target
        # spellings above carry no drive letter, so they stay relative — and
        # therefore refused — on Windows too.
        #
        # A UNC / network share (`\\server\share\grid.duckdb`, or its `//` form)
        # has no colon at all, so it slips past the segment check while being
        # exactly the off-the-filesystem target this guard exists to refuse.
        # It is named separately so the operator sees why it was rejected.
        if PureWindowsPath(value_text).drive.startswith("\\\\"):
            raise ValueError(
                "duckdb_path_network_target: DUCKDB_PATH must be a local file "
                "path, not a UNC network share"
            )

        looks_like_connection_target = ":" in value_text.split("/", 1)[0]
        is_windows_absolute_path = (
            os.name == "nt" and PureWindowsPath(value_text).is_absolute()
        )
        if looks_like_connection_target and not is_windows_absolute_path:
            raise ValueError(
                "DUCKDB_PATH must be a local file path, not a DuckDB connection "
                "target (md:, ducklake:, :memory:, or scheme://)"
            )

        path = Path(value_text)
        if path.is_dir():
            raise ValueError("DUCKDB_PATH must name a file, not a directory")
        return path

    def credential_for(self, provider: str) -> str | None:
        secret = {"claude": self.anthropic_api_key, "gemini": self.gemini_api_key}.get(
            provider
        )
        return secret.get_secret_value() if secret is not None else None

    def model_for(self, provider: str) -> str:
        return (
            self.copilot_model
            if provider == self.copilot_provider and self.copilot_model
            else DEFAULT_PROVIDER_MODELS[provider]
        )

    def provider_status(self, provider: str | None = None) -> ProviderStatus:
        name = provider or self.copilot_provider
        if name not in DEFAULT_PROVIDER_MODELS:
            raise ValueError(f"unknown copilot provider: {name!r}")
        model = self.model_for(name)
        if not self.credential_for(name):
            return ProviderStatus(
                name, model, False, f"{name.upper()}_API_KEY is not set"
            )
        return ProviderStatus(name, model, True)

    @property
    def model_is_configured(self) -> bool:
        """Whether the model and its provider credential are configured locally."""
        return bool(self.copilot_model and self.provider_status().ready)


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

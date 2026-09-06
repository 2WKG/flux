"""Configuration for the read-only Copilot HTTP service."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings kept separate from route and provider implementations."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    duckdb_path: Path = Field(default=Path("data/duck/grid.duckdb"))
    copilot_model: str | None = Field(default=None)
    anthropic_api_key: SecretStr | None = Field(default=None, repr=False)
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)

    @field_validator("duckdb_path", mode="before")
    @classmethod
    def validate_duckdb_path(cls, value: str | Path) -> Path:
        """Reject path forms that cannot be a local read-only DuckDB artifact.

        Existence is deliberately not required here: a missing but otherwise
        valid artifact is reported as the documented unavailable health state.
        """
        value_text = str(value).strip()
        if not value_text or "://" in value_text or value_text.lower() == ":memory:":
            raise ValueError("DUCKDB_PATH must be a non-empty local file path")

        path = Path(value_text)
        if path == Path(".") or path.is_dir():
            raise ValueError("DUCKDB_PATH must name a file, not a directory")
        return path

    @property
    def model_is_configured(self) -> bool:
        """Whether the model and its provider credential are configured locally."""
        return bool(
            self.copilot_model
            and self.anthropic_api_key
            and self.anthropic_api_key.get_secret_value()
        )

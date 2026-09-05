"""Configuration for the read-only Copilot HTTP service."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings kept separate from route and provider implementations."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    duckdb_path: Path = Field(default=Path("data/duck/grid.duckdb"))
    copilot_model: str | None = Field(default=None)
    anthropic_api_key: SecretStr | None = Field(default=None, repr=False)
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)

    @property
    def model_is_configured(self) -> bool:
        """Whether the model and its provider credential are configured locally."""
        return bool(
            self.copilot_model
            and self.anthropic_api_key
            and self.anthropic_api_key.get_secret_value()
        )

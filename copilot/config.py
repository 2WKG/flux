"""Configuration for the read-only Copilot HTTP service."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    duckdb_path: Path = Field(default=Path("data/duck/grid.duckdb"))
    physical_inventory_root: Path = Field(
        default=Path("data/artifacts/physical_inventory")
    )
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
        if not value_text:
            raise ValueError("DUCKDB_PATH must be a non-empty local file path")

        # DuckDB reads remote and virtual databases from targets whose first path
        # segment carries a colon: MotherDuck's `md:<db>`, `ducklake:<catalog>`,
        # the in-memory `:memory:`, and any `scheme://host/...` URL.  A `Path`
        # normalises `motherduck://x` to `motherduck:/x`, so the check is on the
        # segment rather than on the `://` spelling.  Opening any of them would
        # take this read-only local service off the filesystem and onto a network.
        path = Path(value_text)
        # A drive-qualified path is local on Windows, but not on POSIX. Consult
        # the running platform's Path implementation so a local Windows artifact
        # is accepted without admitting a virtual DuckDB target.
        if ":" in value_text.split("/", 1)[0] and not path.is_absolute():
            raise ValueError(
                "DUCKDB_PATH must be a local file path, not a DuckDB connection "
                "target (md:, ducklake:, :memory:, or scheme://)"
            )

        if path.is_dir():
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

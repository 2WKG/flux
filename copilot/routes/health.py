"""Fixture-safe service health endpoint."""

from __future__ import annotations

from typing import Literal

import duckdb
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from copilot.api import SuccessEnvelope, UnavailableError, success
from copilot.api.errors import request_id_of
from copilot.config import Settings

router = APIRouter(tags=["health"])


class ComponentStatus(BaseModel):
    """A deliberately narrow availability statement for a health component."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["available", "not_configured", "not_verified"]
    message: str


class HealthData(BaseModel):
    """Health facts established locally, without invoking an external provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    database: ComponentStatus
    model: ComponentStatus


def _open_database(path: str) -> None:
    """Prove the configured database can be opened without exposing its location."""
    connection = duckdb.connect(path, read_only=True)
    connection.close()


def _model_status(settings: Settings) -> ComponentStatus:
    if not settings.model_is_configured:
        return ComponentStatus(
            status="not_configured",
            message="No model provider credential is configured.",
        )
    return ComponentStatus(
        status="not_verified",
        message="Model availability is not verified by this local health check.",
    )


@router.get("/health", response_model=SuccessEnvelope[HealthData])
def health(request: Request) -> SuccessEnvelope[HealthData]:
    """Return local readiness facts or the shared unavailable envelope.

    Opening the configured DuckDB file read-only prevents a missing or corrupt
    fixture from being represented as an available source. Provider APIs are
    intentionally not called: a configured credential is not evidence that a
    model is reachable.
    """
    settings: Settings = request.app.state.settings
    try:
        _open_database(str(settings.duckdb_path))
    except duckdb.Error as exc:
        raise UnavailableError(
            "The configured database artifact is unavailable.",
            details={
                "artifact": "database",
                "model": "not_configured"
                if not settings.model_is_configured
                else "not_verified",
            },
        ) from exc

    return success(
        HealthData(
            database=ComponentStatus(
                status="available",
                message="The configured database artifact opened read-only.",
            ),
            model=_model_status(settings),
        ),
        request_id=request_id_of(request),
    )

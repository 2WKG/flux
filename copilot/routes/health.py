"""Fixture-safe service health endpoint."""

from __future__ import annotations

from typing import Literal

import duckdb
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from copilot.api import UnavailableError
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

    ok: Literal[True]
    duckdb_path: str
    tables: tuple[str, ...]
    corpus_chunks: int
    dense: bool
    model: ComponentStatus


def _database_health(path: str) -> tuple[tuple[str, ...], int, bool]:
    """Read the database readiness facts without creating or changing it."""
    connection = duckdb.connect(path, read_only=True)
    try:
        tables = tuple(
            sorted(row[0] for row in connection.execute("SHOW TABLES").fetchall())
        )
        if "corpus_chunks" not in tables:
            return tables, 0, False

        corpus_chunks = connection.execute(
            "SELECT COUNT(*) FROM corpus_chunks"
        ).fetchone()[0]
        dense = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM corpus_chunks WHERE embedding IS NOT NULL)"
        ).fetchone()[0]
        return tables, corpus_chunks, dense
    finally:
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


@router.get("/health", response_model=HealthData)
def health(request: Request) -> HealthData:
    """Return local readiness facts or raise the shared unavailable error.

    The DuckDB probe is read-only, so a missing or corrupt fixture is never
    represented as available and the endpoint cannot create an empty database.
    Provider APIs are intentionally not called: a configured credential is not
    evidence that a model is reachable.
    """
    settings: Settings = request.app.state.settings
    try:
        tables, corpus_chunks, dense = _database_health(str(settings.duckdb_path))
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

    return HealthData(
        ok=True,
        duckdb_path=str(settings.duckdb_path),
        tables=tables,
        corpus_chunks=corpus_chunks,
        dense=dense,
        model=_model_status(settings),
    )

"""Read-only scenario catalog and detail routes backed by DuckDB."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import duckdb
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from copilot.api import (
    ArtifactRef,
    NotFoundError,
    SuccessEnvelope,
    UnavailableError,
    success,
)
from copilot.api.errors import request_id_of
from copilot.config import Settings

router = APIRouter(tags=["scenarios"])

type ArtifactSourceKind = Literal[
    "fixture", "observed", "simulated", "heuristic", "retrieval"
]


class ScenarioAssumptions(BaseModel):
    """Scenario parameters persisted by the artifact, not inferred by the API."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["historical", "forecast", "synthetic"]
    ts_start: datetime
    ts_end: datetime
    duration_hours: int


class ScenarioProvenance(BaseModel):
    """The complete row-level provenance supplied by the DuckDB contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str
    source_ref: str
    source_version: str | None
    source_retrieved_at: datetime | None
    fixture_batch_id: str


class ScenarioData(BaseModel):
    """Identity, persisted assumptions, and provenance for one scenario."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    name: str
    assumptions: ScenarioAssumptions
    provenance: ScenarioProvenance


class ScenarioCatalog(BaseModel):
    """Deterministically ordered collection of scenarios in the configured artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenarios: tuple[ScenarioData, ...]


_SCENARIO_COLUMNS = """
    scenario_id, name, kind, ts_start, ts_end,
    source_name, source_ref, source_version, source_retrieved_at, fixture_batch_id
"""


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _source_kind(source_name: str, scenario_kind: str) -> ArtifactSourceKind:
    """Classify a provenance artifact without inventing a new source label."""
    if source_name.startswith("fixture:"):
        return "fixture"
    if scenario_kind == "historical":
        return "observed"
    if scenario_kind == "synthetic":
        return "simulated"
    return "heuristic"


def _scenario_from_row(row: tuple[object, ...]) -> tuple[ScenarioData, ArtifactRef]:
    (
        scenario_id,
        name,
        kind,
        ts_start,
        ts_end,
        source_name,
        source_ref,
        source_version,
        source_retrieved_at,
        fixture_batch_id,
    ) = row
    start = _as_utc(ts_start if isinstance(ts_start, datetime) else None)
    end = _as_utc(ts_end if isinstance(ts_end, datetime) else None)
    if start is None or end is None:
        raise ValueError("scenario timestamps must be present")

    scenario_kind = str(kind)
    provenance = ScenarioProvenance(
        source_name=str(source_name),
        source_ref=str(source_ref),
        source_version=str(source_version) if source_version is not None else None,
        source_retrieved_at=_as_utc(
            source_retrieved_at if isinstance(source_retrieved_at, datetime) else None
        ),
        fixture_batch_id=str(fixture_batch_id),
    )
    data = ScenarioData(
        scenario_id=str(scenario_id),
        name=str(name),
        assumptions=ScenarioAssumptions(
            kind=scenario_kind,
            ts_start=start,
            ts_end=end,
            duration_hours=int((end - start).total_seconds() // 3_600),
        ),
        provenance=provenance,
    )
    artifact = ArtifactRef(
        artifact_id=f"scenario:{data.scenario_id}",
        artifact_version=provenance.source_version
        or provenance.fixture_batch_id
        or provenance.source_ref,
        source_kind=_source_kind(provenance.source_name, scenario_kind),
    )
    return data, artifact


def _query_scenarios(
    settings: Settings, scenario_id: str | None = None
) -> list[tuple[object, ...]]:
    """Read only the declared scenario contract from the configured artifact."""
    try:
        connection = duckdb.connect(str(settings.duckdb_path), read_only=True)
        try:
            if scenario_id is None:
                return connection.execute(
                    f"SELECT {_SCENARIO_COLUMNS} FROM scenarios ORDER BY scenario_id"
                ).fetchall()
            return connection.execute(
                f"SELECT {_SCENARIO_COLUMNS} FROM scenarios WHERE scenario_id = ?",
                [scenario_id],
            ).fetchall()
        finally:
            connection.close()
    except duckdb.Error as exc:
        raise UnavailableError(
            "The configured scenario artifact is unavailable.",
            details={"artifact": "scenarios"},
        ) from exc


@router.get("/scenarios", response_model=SuccessEnvelope[ScenarioCatalog])
def scenario_catalog(request: Request) -> SuccessEnvelope[ScenarioCatalog]:
    """Return every persisted scenario in deterministic identifier order."""
    settings: Settings = request.app.state.settings
    resolved = [_scenario_from_row(row) for row in _query_scenarios(settings)]
    return success(
        ScenarioCatalog(scenarios=tuple(data for data, _ in resolved)),
        request_id=request_id_of(request),
        artifacts=tuple(artifact for _, artifact in resolved),
    )


@router.get("/scenarios/{scenario_id}", response_model=SuccessEnvelope[ScenarioData])
def scenario_detail(
    request: Request, scenario_id: str
) -> SuccessEnvelope[ScenarioData]:
    """Return one persisted scenario without client-side database access."""
    settings: Settings = request.app.state.settings
    rows = _query_scenarios(settings, scenario_id)
    if not rows:
        raise NotFoundError(
            "The requested scenario does not exist.",
            details={"scenario_id": scenario_id},
        )
    data, artifact = _scenario_from_row(rows[0])
    return success(data, request_id=request_id_of(request), artifacts=(artifact,))

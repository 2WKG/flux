"""Read-only scenario catalog and detail routes backed by DuckDB.

``GET /scenarios`` returns the bare array pinned by ``docs/specs/00-overview.md``
§4.2 and ``docs/specs/05-copilot.md`` §Routes::

    [{scenario_id, name, kind, ts_start, ts_end, hours, has_cascade, has_predictions}]

``GET /scenarios/{scenario_id}`` returns one such row, unwrapped.  Each row
additionally carries a ``provenance`` object copied from the persisted
provenance columns; documented consumer fields stay top-level.

Failures use the shared failure envelope (``copilot.api``) with a named
``reason`` in ``details`` — an absent, empty, drifted, or malformed artifact
is never an empty success and never a 500.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, Literal

import duckdb
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from copilot.api import NotFoundError, UnavailableError
from copilot.config import Settings
from copilot.routes.contract import ScenarioId

router = APIRouter(tags=["scenarios"])

SCENARIO_KINDS: Final = ("historical", "forecast", "synthetic")
SYNTHETIC_TOPOLOGY_LABEL: Final = "synthetic (ACTIVSg2000)"
_FIXTURE_PREFIX: Final = "fixture:"
_ACTIVSG_MARKER: Final = "activsg"
# Tables the row shape depends on: has_cascade / has_predictions are read
# from persisted artifacts, never defaulted to false when a table is absent.
_REQUIRED_TABLES: Final = ("scenarios", "cascade_runs", "outage_predictions")

_SCENARIO_SQL: Final = """
    SELECT
        s.scenario_id, s.name, s.kind, s.ts_start, s.ts_end,
        s.source_name, s.source_ref, s.source_version, s.source_retrieved_at,
        s.fixture_batch_id,
        EXISTS (SELECT 1 FROM cascade_runs c WHERE c.scenario_id = s.scenario_id),
        EXISTS (SELECT 1 FROM outage_predictions p WHERE p.scenario_id = s.scenario_id)
    FROM scenarios AS s
"""


class ScenarioProvenance(BaseModel):
    """The persisted provenance columns of a scenario row, surfaced verbatim.

    ``source_kind`` and ``topology`` are derived only by explicit rules on the
    persisted ``source_name``/``source_ref``: a ``fixture:`` prefix is a
    fixture; an ACTIVSg reference is simulated on synthetic topology.  Any
    other source is reported as ``None`` — not inferred from ``kind``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str
    source_ref: str
    source_version: str | None
    source_retrieved_at: datetime | None
    fixture_batch_id: str
    source_kind: Literal["fixture", "simulated"] | None
    topology: Literal["synthetic (ACTIVSg2000)"] | None


class ScenarioRow(BaseModel):
    """One ``GET /scenarios`` element; documented consumer fields are top-level."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    name: str
    kind: Literal["historical", "forecast", "synthetic"]
    ts_start: datetime
    ts_end: datetime
    hours: int
    has_cascade: bool
    has_predictions: bool
    provenance: ScenarioProvenance


class _RowInvalid(ValueError):
    """A persisted row violates the scenarios contract (a schema mismatch)."""


def _unavailable(
    reason: str, *, artifact: str = "scenarios", **extra: str
) -> UnavailableError:
    messages = {
        "missing": f"The {artifact} artifact is unavailable.",
        "no_rows": "The scenarios artifact has no rows.",
        "schema_mismatch": "The scenarios artifact does not match the documented contract.",
        "query_failed": "The scenarios artifact could not be read.",
    }
    return UnavailableError(
        messages[reason], details={"artifact": artifact, "reason": reason, **extra}
    )


def _as_utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _derive_labels(
    source_name: str, source_ref: str
) -> tuple[
    Literal["fixture", "simulated"] | None, Literal["synthetic (ACTIVSg2000)"] | None
]:
    if source_name.startswith(_FIXTURE_PREFIX):
        return "fixture", None
    haystack = f"{source_name} {source_ref}".casefold()
    if _ACTIVSG_MARKER in haystack:
        return "simulated", SYNTHETIC_TOPOLOGY_LABEL
    return None, None


def _scenario_from_row(row: tuple[object, ...]) -> ScenarioRow:
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
        has_cascade,
        has_predictions,
    ) = row
    for label, value in (
        ("scenario_id", scenario_id),
        ("name", name),
        ("source_name", source_name),
        ("source_ref", source_ref),
        ("fixture_batch_id", fixture_batch_id),
    ):
        if not isinstance(value, str) or not value:
            raise _RowInvalid(f"{label} must be a non-empty string")
    if kind not in SCENARIO_KINDS:
        raise _RowInvalid("kind is outside the documented enumeration")
    start = _as_utc(ts_start)
    end = _as_utc(ts_end)
    if start is None or end is None:
        raise _RowInvalid("scenario timestamps must be present")
    if end < start:
        raise _RowInvalid("ts_end precedes ts_start")
    if not isinstance(has_cascade, bool) or not isinstance(has_predictions, bool):
        raise _RowInvalid("artifact existence flags must be boolean")

    source_kind, topology = _derive_labels(source_name, source_ref)
    return ScenarioRow(
        scenario_id=scenario_id,
        name=name,
        kind=kind,
        ts_start=start,
        ts_end=end,
        hours=int((end - start).total_seconds() // 3_600),
        has_cascade=has_cascade,
        has_predictions=has_predictions,
        provenance=ScenarioProvenance(
            source_name=source_name,
            source_ref=source_ref,
            source_version=str(source_version) if source_version is not None else None,
            source_retrieved_at=_as_utc(source_retrieved_at),
            fixture_batch_id=fixture_batch_id,
            source_kind=source_kind,
            topology=topology,
        ),
    )


def _missing_tables(connection: duckdb.DuckDBPyConnection) -> list[str]:
    present = {
        name
        for (name,) in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    return [table for table in _REQUIRED_TABLES if table not in present]


def _query_scenarios(
    settings: Settings, scenario_id: str | None = None
) -> list[tuple[object, ...]]:
    """Read the declared scenario contract; every failure is a named unavailable."""

    try:
        connection = duckdb.connect(str(settings.duckdb_path), read_only=True)
    except duckdb.Error as exc:
        raise _unavailable("missing", artifact="database") from exc
    try:
        missing = _missing_tables(connection)
        if missing:
            raise _unavailable("missing", artifact=missing[0])
        try:
            if scenario_id is None:
                return connection.execute(
                    f"{_SCENARIO_SQL} ORDER BY s.scenario_id"
                ).fetchall()
            return connection.execute(
                f"{_SCENARIO_SQL} WHERE s.scenario_id = ?", [scenario_id]
            ).fetchall()
        except duckdb.BinderException as exc:
            raise _unavailable("schema_mismatch") from exc
        except duckdb.Error as exc:
            raise _unavailable("query_failed") from exc
    finally:
        connection.close()


def _rows_to_scenarios(rows: list[tuple[object, ...]]) -> list[ScenarioRow]:
    scenarios: list[ScenarioRow] = []
    for row in rows:
        try:
            scenarios.append(_scenario_from_row(row))
        except _RowInvalid as exc:
            scenario_id = row[0] if row and isinstance(row[0], str) else "unknown"
            raise _unavailable("schema_mismatch", scenario_id=scenario_id) from exc
    return scenarios


@router.get("/scenarios", response_model=list[ScenarioRow])
def scenario_catalog(request: Request) -> list[ScenarioRow]:
    """Return every persisted scenario as a bare array in identifier order."""

    settings: Settings = request.app.state.settings
    rows = _query_scenarios(settings)
    if not rows:
        raise _unavailable("no_rows")
    return _rows_to_scenarios(rows)


@router.get("/scenarios/{scenario_id}", response_model=ScenarioRow)
def scenario_detail(request: Request, scenario_id: ScenarioId) -> ScenarioRow:
    """Return one persisted scenario row, unwrapped."""

    settings: Settings = request.app.state.settings
    rows = _query_scenarios(settings, scenario_id)
    if not rows:
        raise NotFoundError(
            "The requested scenario does not exist.",
            details={"scenario_id": scenario_id},
        )
    [scenario] = _rows_to_scenarios(rows)
    return scenario

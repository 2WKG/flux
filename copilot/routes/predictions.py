"""Read-only qualified-prediction and persisted-cascade reads.

``GET /predictions`` returns the bare array pinned by ``docs/specs/05-copilot.md``
§Routes: one element per ``outage_predictions`` row whose provenance cites an
evaluation persisted with ``qualified = TRUE``.  Qualification is read from
``evaluation_artifacts`` through :func:`models.outage.persistence.query_predictions`
(``qualified_only=True``) — the predicate runs in SQL before ``LIMIT``, so a
qualified row is never hidden behind unqualified ones.  Heuristic rows cite no
evaluation and are therefore never "qualified"; an artifact holding only such
rows is ``no_qualified_prediction``, by design.

``GET /cascade`` returns one persisted ``cascade_runs`` run, unwrapped, in the
spec-05 cascade layer shape ``{run_id, scenario_id, hours:[...], provenance,
attributes}``.  ``lost_load_mw`` and the topology label come from the row's own
columns and provenance (``pipelines.db`` ``PROVENANCE_COLUMNS``), never from a
constant.  With no ``run_id`` the "latest" run is the one with the greatest
``source_retrieved_at`` (the only timestamp the table carries); runs without it
sort last and ties fall back to lexical ``run_id`` order — there is no run
timestamp column, so this is documented rather than pretended.

Failures use the shared failure envelope (``copilot.api``) with a named
``reason`` in ``details``; malformed parameters are the shared 422
``invalid_input`` envelope and are rejected before the database is opened.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Final, Literal

import duckdb
from fastapi import APIRouter, Query, Request

from copilot.api import InvalidInputError, NotFoundError, UnavailableError
from copilot.config import Settings
from copilot.routes.scenarios import _as_utc, _derive_labels
from models.outage.persistence import PersistenceError, query_predictions

router = APIRouter(tags=["predictions"])

PREDICTION_TABLES: Final = (
    "outage_predictions",
    "prediction_provenance",
    "evaluation_artifacts",
)
CASCADE_TABLES: Final = ("cascade_runs",)
MAX_PREDICTIONS: Final = 1000

# Persisted identifiers are lowercase, bounded route values (the #54/#95
# pattern); ``cascade_runs.run_id`` is ``{scenario_id}-s{seed}-{sha8}``.
_ID_PATTERN: Final = r"^[a-z0-9][a-z0-9_-]*$"
ScenarioIdQuery = Annotated[
    str, Query(min_length=1, max_length=64, pattern=_ID_PATTERN)
]
OptionalScenarioIdQuery = Annotated[
    str | None, Query(min_length=1, max_length=64, pattern=_ID_PATTERN)
]
RunIdQuery = Annotated[
    str | None, Query(min_length=1, max_length=128, pattern=_ID_PATTERN)
]
CountyFipsQuery = Annotated[str | None, Query(pattern=r"^\d{5}$")]
ModelKind = Literal["lightgbm", "heuristic"]

CASCADE_ATTRIBUTES: Final[dict[str, dict[str, str | None]]] = {
    "hour": {
        "unit": "h",
        "kind": "offset from the scenario ts_start",
        "source": "cascade_runs.hour",
    },
    "tripped_element_ids": {
        "unit": None,
        "kind": "ordered element list",
        "source": "cascade_runs.tripped_element_ids_json",
    },
    "lost_load_mw": {
        "unit": "MW",
        "kind": "measure",
        "source": "cascade_runs.lost_load_mw",
    },
    "counties_dark": {
        "unit": None,
        "kind": "FIPS code list",
        "source": "cascade_runs.counties_dark_json",
    },
    "critical_loads_lost": {
        "unit": None,
        "kind": "critical load id list",
        "source": "cascade_runs.critical_loads_lost_json",
    },
}

_RUN_COLUMNS: Final = """run_id, scenario_id, hour, tripped_element_ids_json,
           lost_load_mw, counties_dark_json, critical_loads_lost_json,
           source_name, source_ref, source_version, source_retrieved_at,
           fixture_batch_id"""
_LATEST_RUN_SQL: Final = """
    SELECT run_id FROM cascade_runs WHERE scenario_id = ?
    GROUP BY run_id
    ORDER BY max(source_retrieved_at) DESC NULLS LAST, run_id DESC
    LIMIT 1
"""
_RUN_SQL: Final = f"""
    SELECT {_RUN_COLUMNS} FROM cascade_runs
    WHERE scenario_id = ? AND run_id = ?
    ORDER BY hour
"""

_MESSAGES: Final = {
    "database_missing": "The {artifact} database is unavailable.",
    "missing": "The {artifact} artifact is unavailable.",
    "no_qualified_prediction": (
        "No persisted prediction cites a qualified evaluation artifact."
    ),
    "topology_cascade_unsupported_or_absent": (
        "No persisted topology cascade run exists for the scenario."
    ),
    "schema_mismatch": "The {artifact} artifact does not match the documented contract.",
    "query_failed": "The {artifact} artifact could not be read.",
}


class _RowInvalid(ValueError):
    """A persisted cascade row violates the documented shape."""


def _unavailable(reason: str, *, artifact: str, **extra: str) -> UnavailableError:
    return UnavailableError(
        _MESSAGES[reason].format(artifact=artifact),
        details={"artifact": artifact, "reason": reason, **extra},
    )


def _connect(settings: Settings, *, artifact: str) -> duckdb.DuckDBPyConnection:
    try:
        return duckdb.connect(str(settings.duckdb_path), read_only=True)
    except duckdb.Error as exc:
        raise _unavailable("database_missing", artifact=artifact) from exc


def _missing_tables(
    connection: duckdb.DuckDBPyConnection, required: tuple[str, ...]
) -> list[str]:
    present = {
        name
        for (name,) in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    return [table for table in required if table not in present]


@router.get("/predictions")
def predictions(
    request: Request,
    scenario_id: OptionalScenarioIdQuery = None,
    county_fips: CountyFipsQuery = None,
    model_kind: ModelKind | None = None,
    limit: int = Query(MAX_PREDICTIONS, ge=1, le=MAX_PREDICTIONS),
) -> list[dict[str, Any]]:
    """Return qualified prediction rows as a bare array, or a named failure."""

    artifact = "outage_predictions"
    settings: Settings = request.app.state.settings
    con = _connect(settings, artifact=artifact)
    try:
        missing = _missing_tables(con, PREDICTION_TABLES)
        if missing:
            raise _unavailable("missing", artifact=missing[0])
        try:
            rows = query_predictions(
                con,
                scenario_id=scenario_id,
                county_fips=county_fips,
                model_kind=model_kind,
                limit=limit,
                qualified_only=True,
            )
        except PersistenceError as exc:
            raise InvalidInputError(
                "Request parameters do not match the documented contract.",
                details={"reason": "invalid_request"},
            ) from exc
        except duckdb.BinderException as exc:
            raise _unavailable("schema_mismatch", artifact=artifact) from exc
        except duckdb.Error as exc:
            raise _unavailable("query_failed", artifact=artifact) from exc
        if not rows:
            raise _unavailable("no_qualified_prediction", artifact=artifact)
        return rows
    finally:
        con.close()


def _json_list(value: object, label: str) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise _RowInvalid(f"{label} is not JSON") from exc
    if not isinstance(value, list):
        raise _RowInvalid(f"{label} must be a JSON array")
    return value


def _cascade_from_rows(rows: list[tuple[object, ...]]) -> dict[str, Any]:
    hours: list[dict[str, Any]] = []
    for row in rows:
        (
            run_id,
            scenario_id,
            hour,
            tripped,
            lost_load_mw,
            counties_dark,
            critical_loads_lost,
            *_provenance,
        ) = row
        if not isinstance(hour, int) or isinstance(hour, bool) or hour < 0:
            raise _RowInvalid("hour must be a non-negative integer")
        if not isinstance(lost_load_mw, int | float) or isinstance(lost_load_mw, bool):
            raise _RowInvalid("lost_load_mw must be a number")
        hours.append(
            {
                "hour": hour,
                "tripped_element_ids": _json_list(tripped, "tripped_element_ids_json"),
                "lost_load_mw": float(lost_load_mw),
                "counties_dark": _json_list(counties_dark, "counties_dark_json"),
                "critical_loads_lost": _json_list(
                    critical_loads_lost, "critical_loads_lost_json"
                ),
            }
        )
    (
        run_id,
        scenario_id,
        *_hour_fields,
        source_name,
        source_ref,
        source_version,
        source_retrieved_at,
        fixture_batch_id,
    ) = rows[0]
    for label, value in (
        ("run_id", run_id),
        ("scenario_id", scenario_id),
        ("source_name", source_name),
        ("source_ref", source_ref),
        ("fixture_batch_id", fixture_batch_id),
    ):
        if not isinstance(value, str) or not value:
            raise _RowInvalid(f"{label} must be a non-empty string")
    source_kind, topology = _derive_labels(source_name, source_ref)
    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "hours": hours,
        "provenance": {
            "source_name": source_name,
            "source_ref": source_ref,
            "source_version": source_version,
            "source_retrieved_at": _as_utc(source_retrieved_at),
            "fixture_batch_id": fixture_batch_id,
            "source_kind": source_kind,
            "topology": topology,
        },
        "attributes": CASCADE_ATTRIBUTES,
    }


@router.get("/cascade")
def cascade(
    request: Request, scenario_id: ScenarioIdQuery, run_id: RunIdQuery = None
) -> dict[str, Any]:
    """Read one persisted topology cascade run; aggregate evidence cannot supply one."""

    artifact = "cascade_runs"
    settings: Settings = request.app.state.settings
    con = _connect(settings, artifact=artifact)
    try:
        missing = _missing_tables(con, CASCADE_TABLES)
        if missing:
            raise _unavailable("missing", artifact=missing[0])
        try:
            if run_id is None:
                latest = con.execute(_LATEST_RUN_SQL, [scenario_id]).fetchone()
                if latest is None:
                    raise _unavailable(
                        "topology_cascade_unsupported_or_absent", artifact=artifact
                    )
                run_id = str(latest[0])
            rows = con.execute(_RUN_SQL, [scenario_id, run_id]).fetchall()
        except duckdb.BinderException as exc:
            raise _unavailable("schema_mismatch", artifact=artifact) from exc
        except duckdb.Error as exc:
            raise _unavailable("query_failed", artifact=artifact) from exc
        if not rows:
            raise NotFoundError(
                "The requested cascade run does not exist for the scenario.",
                details={"scenario_id": scenario_id, "run_id": run_id},
            )
        try:
            return _cascade_from_rows(rows)
        except _RowInvalid as exc:
            raise _unavailable(
                "schema_mismatch", artifact=artifact, run_id=run_id
            ) from exc
    finally:
        con.close()

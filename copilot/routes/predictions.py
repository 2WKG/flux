"""Read-only qualified-prediction and persisted-cascade reads (2WKG-104).

``GET /predictions`` returns the bare array pinned by ``docs/specs/05-copilot.md``
§Routes: one element per ``outage_predictions`` row whose provenance cites an
evaluation persisted with ``qualified = TRUE``.  Qualification is read from
``evaluation_artifacts`` through :func:`models.outage.persistence.query_predictions`
(``qualified_only=True``) — the predicate runs in SQL before ``LIMIT``, so a
qualified row is never hidden behind unqualified ones.  Heuristic rows cite no
evaluation and are therefore never "qualified"; an artifact holding only such
rows is ``no_qualified_prediction``, by design.

``GET /cascade`` returns one persisted ``cascade_runs`` run, unwrapped.  A run is
eligible only when the Minnesota artifact metadata qualifies it: its
``mn_model_results`` row is ``validated``, its ``mn_artifact_manifests`` row is
``available`` with ``model_mode = 'topology'``, and the manifest has provenance
rows.  The payload is the spec-05 cascade layer shape plus the artifact's own
metadata: ``{run_id, scenario_id, artifact_id, model_mode, geography_id,
hours:[{hour, tripped_element_ids, lost_load_mw, counties_dark,
critical_loads_lost}], provenance:[...], limitations:[...], source_kind,
topology, attributes}``.  ``lost_load_mw`` is read from the row (MW, see
``CASCADE_ATTRIBUTES``); ``source_kind``/``topology`` are derived from the
artifact's and the row's persisted provenance, never from a constant — a run
whose provenance supports neither label is ``topology_label_unavailable``.
With no ``run_id`` the "latest" run is the qualified run whose manifest has the
greatest ``created_at`` (the only run-level timestamp persisted); ties fall back
to lexical ``run_id`` then ``artifact_id`` order — a total order over the
selected columns, so the served run is deterministic by construction rather than
whatever ``LIMIT 1`` happens to reach first.  That is documented, not pretended
to be temporal.

When no run qualifies, ``cascade_not_computed`` means there is no persisted
``cascade_runs`` row for the scenario; ``topology_cascade_unsupported`` means a
persisted model is aggregate or otherwise non-topology; and
``cascade_artifact_unavailable`` means a persisted row lacks available,
validated Minnesota topology metadata.  When a scenario holds both, the most
recoverable reason wins: any topology artifact present makes the answer
``cascade_artifact_unavailable``, never ``topology_cascade_unsupported``.  Each is a read-only unavailable response, never a
fabricated zero or a request to compute a run.

Failures use the shared failure envelope (``copilot.api``) with a named
``reason`` in ``details``; malformed parameters are the shared 422
``invalid_input`` envelope and are rejected before the database is opened.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Final, Literal

import duckdb
from fastapi import APIRouter, Query, Request, Response

from copilot.api import InvalidInputError, NotFoundError, UnavailableError
from copilot.api.errors import ARTIFACT_HEADER
from copilot.config import Settings
from copilot.routes.scenarios import _as_utc, _derive_labels
from models.outage.persistence import PersistenceError, query_predictions

router = APIRouter(tags=["predictions"])

PREDICTION_TABLES: Final = (
    "outage_predictions",
    "prediction_provenance",
    "evaluation_artifacts",
)
CASCADE_TABLES: Final = (
    "cascade_runs",
    "mn_artifact_manifests",
    "mn_artifact_provenance",
    "mn_model_results",
)
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

# The qualified-run selection: a persisted cascade run counts only when its
# Minnesota model result is validated and its manifest is an available topology
# artifact with provenance.  ``run_id`` narrows it; otherwise the manifest with
# the greatest ``created_at`` wins.  The tie-break is a TOTAL order over the
# selected columns — ``run_id`` desc, then ``artifact_id`` desc — because two
# available topology manifests can cite the same ``model_run_id`` with the same
# ``created_at``, and ``LIMIT 1`` over a partial order would serve an arbitrary
# one of them.  Documented, not pretended to be temporal.
_QUALIFIED_RUN_SQL: Final = """
    SELECT DISTINCT c.run_id, m.artifact_id, m.model_mode, m.geography_id,
           m.limitations_json, m.created_at
    FROM cascade_runs AS c
    JOIN mn_model_results AS r ON r.model_run_id = c.run_id
    JOIN mn_artifact_manifests AS m ON m.artifact_id = r.artifact_id
    WHERE c.scenario_id = ?
      AND {run_filter}
      AND m.availability = 'available'
      AND m.model_mode = 'topology'
      AND r.validation_status = 'validated'
      AND EXISTS (
          SELECT 1 FROM mn_artifact_provenance AS p
          WHERE p.artifact_id = m.artifact_id
      )
    ORDER BY m.created_at DESC, c.run_id DESC, m.artifact_id DESC
    LIMIT 1
"""
_RUN_EXISTS_SQL: Final = (
    "SELECT 1 FROM cascade_runs WHERE scenario_id = ? AND run_id = ? LIMIT 1"
)
# Aggregated to exactly ONE row on purpose: ``cascade_runs`` holds one row per
# HOUR (a 72-hour run is 72 rows, multiplied again by matching manifests), and
# this query exists only to pick a 3-value enum for an already-failing request.
# The aggregates are computed in DuckDB so the route reads a single row.
_RUN_ARTIFACT_STATUS_SQL: Final = """
    SELECT count(*) > 0 AS any_row,
           bool_or(m.model_mode = 'topology') AS any_topology,
           bool_or(m.model_mode IN ('aggregate', 'not_applicable')) AS any_unsupported
    FROM cascade_runs AS c
    LEFT JOIN mn_model_results AS r ON r.model_run_id = c.run_id
    LEFT JOIN mn_artifact_manifests AS m ON m.artifact_id = r.artifact_id
    WHERE c.scenario_id = ?
      AND {run_filter}
"""
_HOURS_SQL: Final = """
    SELECT hour, tripped_element_ids_json, lost_load_mw, counties_dark_json,
           critical_loads_lost_json, source_name, source_ref
    FROM cascade_runs
    WHERE scenario_id = ? AND run_id = ?
    ORDER BY hour
"""
_PROVENANCE_SQL: Final = """
    SELECT source_name, source_ref, source_version, retrieved_at,
           license_or_terms, source_record_id, content_sha256, is_derived
    FROM mn_artifact_provenance
    WHERE artifact_id = ?
    ORDER BY provenance_ordinal
"""

_MESSAGES: Final = {
    "database_missing": "The {artifact} database is unavailable.",
    "missing": "The {artifact} artifact is unavailable.",
    "no_qualified_prediction": (
        "No persisted prediction cites a qualified evaluation artifact."
    ),
    "cascade_not_computed": (
        "No persisted cascade run has been computed for the scenario."
    ),
    "topology_cascade_unsupported": (
        "The persisted model does not support topology cascade results."
    ),
    "cascade_artifact_unavailable": (
        "The persisted cascade artifact is unavailable for the scenario."
    ),
    "invalid_topology_artifact": (
        "The topology cascade artifact metadata does not match the documented contract."
    ),
    "topology_label_unavailable": (
        "The persisted provenance does not identify the cascade topology."
    ),
    "schema_mismatch": "The {artifact} artifact does not match the documented contract.",
    "query_failed": "The {artifact} artifact could not be read.",
}


class _RowInvalid(ValueError):
    """A persisted cascade row violates the documented shape."""


class _ArtifactInvalid(ValueError):
    """The qualifying Minnesota artifact metadata violates its contract."""


def _header_safe_artifact_id(value: object) -> str:
    """Return an immutable artifact ID that can safely enter an HTTP header."""

    if not isinstance(value, str) or not value:
        raise _ArtifactInvalid("artifact_id must be a non-empty string")
    if not value.isascii() or any(
        not 33 <= ord(character) <= 126 for character in value
    ):
        raise _ArtifactInvalid("artifact_id is not safe for an HTTP header")
    return value


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


def _json_list(value: object, label: str, error: type[ValueError]) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise error(f"{label} is not JSON") from exc
    if not isinstance(value, list):
        raise error(f"{label} must be a JSON array")
    return value


def _require_str(value: object, label: str, error: type[ValueError]) -> str:
    if not isinstance(value, str) or not value:
        raise error(f"{label} must be a non-empty string")
    return value


def _hours_from_rows(
    rows: list[tuple[object, ...]],
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    hours: list[dict[str, Any]] = []
    row_sources: list[tuple[str, str]] = []
    for row in rows:
        (
            hour,
            tripped,
            lost_load_mw,
            counties_dark,
            critical_loads_lost,
            source_name,
            source_ref,
        ) = row
        if not isinstance(hour, int) or isinstance(hour, bool) or hour < 0:
            raise _RowInvalid("hour must be a non-negative integer")
        if not isinstance(lost_load_mw, int | float) or isinstance(lost_load_mw, bool):
            raise _RowInvalid("lost_load_mw must be a number")
        hours.append(
            {
                "hour": hour,
                "tripped_element_ids": _json_list(
                    tripped, "tripped_element_ids_json", _RowInvalid
                ),
                "lost_load_mw": float(lost_load_mw),
                "counties_dark": _json_list(
                    counties_dark, "counties_dark_json", _RowInvalid
                ),
                "critical_loads_lost": _json_list(
                    critical_loads_lost, "critical_loads_lost_json", _RowInvalid
                ),
            }
        )
        row_sources.append(
            (
                _require_str(source_name, "source_name", _RowInvalid),
                _require_str(source_ref, "source_ref", _RowInvalid),
            )
        )
    return hours, row_sources


def _provenance_from_rows(rows: list[tuple[object, ...]]) -> list[dict[str, Any]]:
    provenance: list[dict[str, Any]] = []
    for row in rows:
        (
            source_name,
            source_ref,
            source_version,
            retrieved_at,
            license_or_terms,
            source_record_id,
            content_sha256,
            is_derived,
        ) = row
        if source_record_id is not None and not isinstance(source_record_id, str):
            raise _ArtifactInvalid("source_record_id is not a string")
        if not isinstance(is_derived, bool):
            raise _ArtifactInvalid("is_derived is not a boolean")
        if not isinstance(retrieved_at, datetime):
            raise _ArtifactInvalid("retrieved_at is not a timestamp")
        provenance.append(
            {
                "source_name": _require_str(
                    source_name, "source_name", _ArtifactInvalid
                ),
                "source_ref": _require_str(source_ref, "source_ref", _ArtifactInvalid),
                "source_version": _require_str(
                    source_version, "source_version", _ArtifactInvalid
                ),
                "retrieved_at": _as_utc(retrieved_at),
                "license_or_terms": _require_str(
                    license_or_terms, "license_or_terms", _ArtifactInvalid
                ),
                "source_record_id": source_record_id,
                "content_sha256": _require_str(
                    content_sha256, "content_sha256", _ArtifactInvalid
                ),
                "is_derived": is_derived,
            }
        )
    if not provenance:
        raise _ArtifactInvalid("the topology artifact has no provenance")
    return provenance


def _limitations(value: object) -> list[str]:
    limitations = _json_list(value, "limitations_json", _ArtifactInvalid)
    if not limitations or not all(
        isinstance(item, str) and item for item in limitations
    ):
        raise _ArtifactInvalid("limitations_json must be a non-empty list of strings")
    return limitations


def _topology_labels(
    sources: list[tuple[str, str]],
) -> tuple[str, str | None]:
    """Derive the reality label from persisted provenance, never a constant.

    Any ACTIVSg reference marks the run as simulated synthetic topology; a run
    whose every source is a fixture is a fixture.  Anything else is unlabelled
    and the caller fails closed.
    """
    labels = [_derive_labels(name, ref) for name, ref in sources]
    for source_kind, topology in labels:
        if topology is not None:
            return str(source_kind), topology
    if labels and all(source_kind == "fixture" for source_kind, _ in labels):
        return "fixture", None
    raise _ArtifactInvalid("no provenance row identifies the topology")


def _unqualified_cascade_reason(
    status: tuple[object, ...] | None,
) -> str:
    """Classify a persisted but unservable cascade without inferring a result.

    ``status`` is the single aggregated row of :data:`_RUN_ARTIFACT_STATUS_SQL`.
    Precedence is *most recoverable wins*, pinned in ``docs/specs/05-copilot.md``
    §Routes: a scenario that holds any topology artifact is
    ``cascade_artifact_unavailable`` even when it also holds an aggregate run,
    because telling an operator "this model does not support topology cascade"
    when a topology model demonstrably exists is a false statement about the
    model rather than about the artifact.
    """

    if status is None or not status[0]:
        return "cascade_not_computed"
    _any_row, any_topology, any_unsupported = status
    if any_topology:
        return "cascade_artifact_unavailable"
    if any_unsupported:
        return "topology_cascade_unsupported"
    return "cascade_artifact_unavailable"


@router.get("/cascade")
def cascade(
    request: Request,
    response: Response,
    scenario_id: ScenarioIdQuery,
    run_id: RunIdQuery = None,
) -> dict[str, Any]:
    """Read one qualified persisted topology cascade run; never compute one."""

    artifact = "cascade_runs"
    settings: Settings = request.app.state.settings
    con = _connect(settings, artifact=artifact)
    try:
        missing = _missing_tables(con, CASCADE_TABLES)
        if missing:
            raise _unavailable("missing", artifact=missing[0])
        try:
            params = [scenario_id] if run_id is None else [scenario_id, run_id]
            chosen = con.execute(
                _QUALIFIED_RUN_SQL.format(
                    run_filter="TRUE" if run_id is None else "c.run_id = ?"
                ),
                params,
            ).fetchone()
            if chosen is None:
                if (
                    run_id is not None
                    and con.execute(_RUN_EXISTS_SQL, [scenario_id, run_id]).fetchone()
                    is None
                ):
                    raise NotFoundError(
                        "The requested cascade run does not exist for the scenario.",
                        details={"scenario_id": scenario_id, "run_id": run_id},
                    )
                status_params = (
                    [scenario_id] if run_id is None else [scenario_id, run_id]
                )
                status_row = con.execute(
                    _RUN_ARTIFACT_STATUS_SQL.format(
                        run_filter="TRUE" if run_id is None else "c.run_id = ?"
                    ),
                    status_params,
                ).fetchone()
                raise _unavailable(
                    _unqualified_cascade_reason(status_row),
                    artifact=artifact,
                    **({} if run_id is None else {"run_id": run_id}),
                )
            run_id = str(chosen[0])
            hour_rows = con.execute(_HOURS_SQL, [scenario_id, run_id]).fetchall()
            provenance_rows = con.execute(_PROVENANCE_SQL, [chosen[1]]).fetchall()
        except duckdb.BinderException as exc:
            raise _unavailable("schema_mismatch", artifact=artifact) from exc
        except duckdb.Error as exc:
            raise _unavailable("query_failed", artifact=artifact) from exc
    finally:
        con.close()

    try:
        hours, row_sources = _hours_from_rows(hour_rows)
    except _RowInvalid as exc:
        raise _unavailable("schema_mismatch", artifact=artifact, run_id=run_id) from exc
    try:
        artifact_id = _header_safe_artifact_id(chosen[1])
        geography_id = _require_str(chosen[3], "geography_id", _ArtifactInvalid)
        limitations = _limitations(chosen[4])
        provenance = _provenance_from_rows(provenance_rows)
    except _ArtifactInvalid as exc:
        raise _unavailable(
            "invalid_topology_artifact", artifact=artifact, run_id=run_id
        ) from exc
    try:
        source_kind, topology = _topology_labels(
            [(p["source_name"], p["source_ref"]) for p in provenance] + row_sources
        )
    except _ArtifactInvalid as exc:
        raise _unavailable(
            "topology_label_unavailable", artifact=artifact, run_id=run_id
        ) from exc
    response.headers[ARTIFACT_HEADER] = artifact_id
    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "artifact_id": artifact_id,
        "model_mode": chosen[2],
        "geography_id": geography_id,
        "hours": hours,
        "provenance": provenance,
        "limitations": limitations,
        "source_kind": source_kind,
        "topology": topology,
        "attributes": CASCADE_ATTRIBUTES,
    }

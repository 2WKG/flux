"""Qualified reads of persisted Minnesota comparison and critical-element scores.

These routes do not run a model or derive deltas/rankings from legacy cascade
rows.  They expose only score artifacts whose persisted component payload names
the requested scenario/intervention or critical element.  Aggregate and other
non-topology artifacts are deliberately unavailable on this topology-read
surface.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Annotated, Any, Final

import duckdb
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from copilot.api import UnavailableError
from copilot.api.pagination import DeterministicOrder, PageRequest, SortTerm

router = APIRouter(tags=["comparisons"])

_REQUIRED_TABLES: Final = (
    "mn_artifact_manifests",
    "mn_artifact_provenance",
    "mn_score_results",
)
_CRITICAL_ORDER: Final = DeterministicOrder(
    primary=(SortTerm("score_value", "DESC"),),
    tie_breaker=SortTerm("artifact_id", "ASC"),
)


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=1, max_length=128)
    intervention_ids: list[
        Annotated[str, Field(pattern=r"^(site:[^@:\s]+(?:@(300|1000))?|line:[^:\s]+)$")]
    ] = Field(min_length=1, max_length=5)


class _PersistedInvalid(ValueError):
    """A supposedly qualified score cannot be represented honestly."""


class _DeclaredUnavailable(ValueError):
    """A persisted manifest explicitly says that its result is unavailable."""


def _unavailable(reason: str, *, artifact: str, **details: str) -> UnavailableError:
    messages = {
        "database_missing": "The comparison database is unavailable.",
        "missing": f"The {artifact} artifact is unavailable.",
        "schema_mismatch": f"The {artifact} artifact does not match the documented contract.",
        "query_failed": f"The {artifact} artifact could not be read.",
        "no_qualified_result": "No qualified persisted result exists for this request.",
        "unsupported_model_mode": (
            "The persisted result is not a supported topology-mode artifact."
        ),
        "invalid_persisted_result": (
            "The persisted result does not contain the required identity or evidence."
        ),
        "artifact_unavailable": "The requested persisted result is unavailable.",
    }
    return UnavailableError(
        messages[reason], details={"artifact": artifact, "reason": reason, **details}
    )


def _connect(request: Request) -> duckdb.DuckDBPyConnection:
    try:
        return duckdb.connect(
            str(request.app.state.settings.duckdb_path), read_only=True
        )
    except duckdb.Error as exc:
        raise _unavailable("database_missing", artifact="database") from exc


def _missing_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    present = {
        name
        for (name,) in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    return [table for table in _REQUIRED_TABLES if table not in present]


def _as_object(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise _PersistedInvalid(f"{label} is not JSON") from exc
    if not isinstance(value, dict):
        raise _PersistedInvalid(f"{label} must be a JSON object")
    return value


def _as_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise _PersistedInvalid(f"{label} must be a non-empty string")
    return value


def _as_string_list(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise _PersistedInvalid(f"{label} must be a non-empty-string list")
    return value


def _as_limitations(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise _PersistedInvalid("limitations_json is not JSON") from exc
    return _as_string_list(value, label="limitations_json")


def _as_timestamp(value: object, *, label: str) -> str:
    if not isinstance(value, datetime):
        raise _PersistedInvalid(f"{label} must be a timestamp")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def _provenance(
    con: duckdb.DuckDBPyConnection, artifact_id: str
) -> list[dict[str, Any]]:
    rows = con.execute(
        """SELECT source_name, source_ref, source_version, retrieved_at,
                  license_or_terms, source_record_id, content_sha256, is_derived
             FROM mn_artifact_provenance WHERE artifact_id=?
             ORDER BY provenance_ordinal""",
        [artifact_id],
    ).fetchall()
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
            raise _PersistedInvalid("source_record_id must be a string or null")
        if not isinstance(is_derived, bool):
            raise _PersistedInvalid("is_derived must be boolean")
        provenance.append(
            {
                "source_name": _as_string(source_name, label="source_name"),
                "source_ref": _as_string(source_ref, label="source_ref"),
                "source_version": _as_string(source_version, label="source_version"),
                "retrieved_at": _as_timestamp(retrieved_at, label="retrieved_at"),
                "license_or_terms": _as_string(
                    license_or_terms, label="license_or_terms"
                ),
                "source_record_id": source_record_id,
                "content_sha256": _as_string(content_sha256, label="content_sha256"),
                "is_derived": is_derived,
            }
        )
    if not provenance:
        raise _PersistedInvalid("available score has no provenance")
    return provenance


def _score_rows(
    con: duckdb.DuckDBPyConnection, *, geography_id: str
) -> list[tuple[object, ...]]:
    return con.execute(
        """SELECT m.artifact_id, m.availability, m.model_mode, m.limitations_json,
                  s.metric, s.score_value, s.score_unit, s.score_components_json,
                  s.regulatory_label
             FROM mn_artifact_manifests AS m
             JOIN mn_score_results AS s USING (artifact_id)
             WHERE m.artifact_kind='score' AND m.geography_id=?
             ORDER BY m.artifact_id ASC""",
        [geography_id],
    ).fetchall()


def _score_payload(
    con: duckdb.DuckDBPyConnection, row: tuple[object, ...]
) -> tuple[dict[str, Any], dict[str, Any]]:
    (
        artifact_id,
        availability,
        model_mode,
        limitations_json,
        metric,
        score_value,
        score_unit,
        components_json,
        regulatory_label,
    ) = row
    artifact_id = _as_string(artifact_id, label="artifact_id")
    if availability == "unavailable":
        raise _DeclaredUnavailable("score manifest is unavailable")
    if availability != "available":
        raise _PersistedInvalid("unavailable score has a domain row")
    if model_mode not in {"topology", "aggregate", "not_applicable"}:
        raise _PersistedInvalid("model_mode is invalid")
    if (
        not isinstance(score_value, int | float)
        or isinstance(score_value, bool)
        or not math.isfinite(score_value)
    ):
        raise _PersistedInvalid("score_value must be finite")
    payload = {
        "artifact_id": artifact_id,
        "model_mode": model_mode,
        "metric": _as_string(metric, label="metric"),
        "score_value": float(score_value),
        "score_unit": _as_string(score_unit, label="score_unit"),
        "score_components": _as_object(components_json, label="score_components_json"),
        "regulatory_label": _as_string(regulatory_label, label="regulatory_label"),
        "provenance": _provenance(con, artifact_id),
        "limitations": _as_limitations(limitations_json),
    }
    return payload, payload["score_components"]


@router.post("/compare")
def compare(payload: CompareRequest, request: Request) -> dict[str, Any]:
    """Read named topology comparison scores; never derive an intervention delta."""

    con = _connect(request)
    try:
        missing = _missing_tables(con)
        if missing:
            raise _unavailable("missing", artifact=missing[0])
        rows = _score_rows(con, geography_id="mn")
        selected: dict[str, dict[str, Any]] = {}
        unsupported = False
        for row in rows:
            try:
                score, components = _score_payload(con, row)
            except _DeclaredUnavailable as exc:
                raise _unavailable(
                    "artifact_unavailable", artifact="comparison"
                ) from exc
            except _PersistedInvalid as exc:
                raise _unavailable(
                    "invalid_persisted_result", artifact="mn_score_results"
                ) from exc
            if components.get("scenario_id") != payload.scenario_id:
                continue
            intervention_id = components.get("intervention_id")
            if intervention_id not in payload.intervention_ids:
                continue
            if score["model_mode"] != "topology":
                unsupported = True
                continue
            selected[str(intervention_id)] = {
                **score,
                "scenario_id": payload.scenario_id,
                "intervention_id": str(intervention_id),
            }
        if unsupported:
            raise _unavailable("unsupported_model_mode", artifact="comparison")
        if set(selected) != set(payload.intervention_ids):
            raise _unavailable("no_qualified_result", artifact="comparison")
        return {
            "scenario_id": payload.scenario_id,
            "interventions": [selected[item] for item in payload.intervention_ids],
            "comparison_status": "persisted_scores_not_derived_deltas",
        }
    except duckdb.BinderException as exc:
        raise _unavailable("schema_mismatch", artifact="mn_score_results") from exc
    except duckdb.Error as exc:
        raise _unavailable("query_failed", artifact="mn_score_results") from exc
    finally:
        con.close()


@router.get("/elements/critical")
def critical_elements(
    request: Request,
    region: Annotated[str, Query(min_length=1, max_length=128)],
    n: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> dict[str, Any]:
    """Page persisted critical-element score artifacts in a stable stored order."""

    page = PageRequest(limit=n, offset=offset)
    con = _connect(request)
    try:
        missing = _missing_tables(con)
        if missing:
            raise _unavailable("missing", artifact=missing[0])
        clause, parameters = _CRITICAL_ORDER.clause(page)
        rows = con.execute(
            f"""SELECT m.artifact_id, m.availability, m.model_mode, m.limitations_json,
                       s.metric, s.score_value, s.score_unit, s.score_components_json,
                       s.regulatory_label
                  FROM mn_artifact_manifests AS m
                  JOIN mn_score_results AS s USING (artifact_id)
                  WHERE m.artifact_kind='score' AND m.geography_id=?
                    AND s.metric='critical_element'
                  {clause}""",
            [region, *parameters],
        ).fetchall()
        if not rows:
            raise _unavailable("no_qualified_result", artifact="critical_elements")
        elements: list[dict[str, Any]] = []
        for row in rows:
            try:
                score, components = _score_payload(con, row)
                if score["model_mode"] != "topology":
                    raise _unavailable(
                        "unsupported_model_mode", artifact="critical_elements"
                    )
                element_id = _as_string(
                    components.get("element_id"), label="element_id"
                )
                kind = components.get("kind")
                if kind not in {"line", "bus", "gen"}:
                    raise _PersistedInvalid("kind must be line, bus, or gen")
                runs = components.get("runs")
                if not isinstance(runs, int) or isinstance(runs, bool) or runs < 0:
                    raise _PersistedInvalid("runs must be a non-negative integer")
                elements.append(
                    {
                        **score,
                        "scenario_id": _as_string(
                            components.get("scenario_id"), label="scenario_id"
                        ),
                        "element_id": element_id,
                        "kind": kind,
                        "lost_load_mw": score["score_value"],
                        "critical_loads_lost": _as_string_list(
                            components.get("critical_loads_lost"),
                            label="critical_loads_lost",
                        ),
                        "runs": runs,
                    }
                )
            except _DeclaredUnavailable as exc:
                raise _unavailable(
                    "artifact_unavailable", artifact="critical_elements"
                ) from exc
            except _PersistedInvalid as exc:
                raise _unavailable(
                    "invalid_persisted_result", artifact="critical_elements"
                ) from exc
        return {
            "region": region,
            "n": n,
            "offset": offset,
            "elements": elements,
            "partial": len(elements) < n,
        }
    except duckdb.BinderException as exc:
        raise _unavailable("schema_mismatch", artifact="mn_score_results") from exc
    except duckdb.Error as exc:
        raise _unavailable("query_failed", artifact="mn_score_results") from exc
    finally:
        con.close()

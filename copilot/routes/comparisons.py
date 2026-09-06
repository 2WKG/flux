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
from copilot.routes.scenarios import _derive_labels

router = APIRouter(tags=["comparisons"])

_REQUIRED_TABLES: Final = ("mn_artifact_manifests",)
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


class _MissingDelta(ValueError):
    """A persisted comparison artifact does not carry a documented A8 field."""


class _UnlabelledSource(ValueError):
    """Persisted provenance does not identify the artifact's source class."""


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
        "ambiguous_identity": (
            "More than one persisted result claims the requested identity."
        ),
        "source_kind_unavailable": (
            "The persisted provenance does not identify the artifact's source "
            "class, so no truthful evidence reference can be built."
        ),
        "persisted_delta_unavailable": (
            "The persisted comparison artifact does not carry the documented "
            "A8 comparison fields, and this route never derives them."
        ),
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


def _has_tables(con: duckdb.DuckDBPyConnection, *tables: str) -> bool:
    present = {
        name
        for (name,) in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    return set(tables) <= present


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


def _require_identity_keys(
    value: dict[str, Any], *, keys: set[str], label: str
) -> dict[str, Any]:
    if set(value) != keys:
        raise _PersistedInvalid(f"{label} has incompatible keys")
    return value


def _as_finite(value: object, *, label: str) -> float:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise _PersistedInvalid(f"{label} must be a finite number")
    return float(value)


def _required_component(components: dict[str, Any], key: str) -> Any:
    """Read one persisted A8 component or fail by name; never default it."""

    if key not in components:
        raise _MissingDelta(key)
    return components[key]


def _a8_intervention(
    intervention_id: str, components: dict[str, Any]
) -> dict[str, Any]:
    """Project one persisted comparison score onto the frozen A8 shape.

    Every value is read from the persisted component payload.  ``kind`` is the
    prefix of the persisted intervention identity itself (``site:`` / ``line:``,
    already pinned by ``CompareRequest``), not a guess.  A component the
    artifact does not carry is a named failure, never a zero.
    """

    lol = _as_finite(
        _required_component(components, "lol_reduction_mwh"),
        label="lol_reduction_mwh",
    )
    customer_hours = _as_finite(
        _required_component(components, "customer_hours_avoided"),
        label="customer_hours_avoided",
    )
    if lol < 0 or customer_hours < 0:
        raise _PersistedInvalid("A8 comparison measures must be non-negative")
    return {
        "intervention_id": intervention_id,
        "kind": "site" if intervention_id.startswith("site:") else "line",
        "run_id": _as_string(_required_component(components, "run_id"), label="run_id"),
        "lol_reduction_mwh": lol,
        "customer_hours_avoided": customer_hours,
        "critical_loads_protected": _as_string_list(
            _required_component(components, "critical_loads_protected"),
            label="critical_loads_protected",
        ),
    }


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


def _artifact_refs(
    artifact_id: str, provenance: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build the frozen `ArtifactRef` evidence list from persisted provenance.

    Every value is persisted: the manifest's `artifact_id`, and each provenance
    row's `source_version` and `source_ref`.  `source_kind` is derived from the
    persisted source labels by the same `_derive_labels` the cascade and
    site-score reads use; a source it cannot label is a named failure rather
    than a guessed class.
    """

    refs: list[dict[str, Any]] = []
    for entry in provenance:
        source_kind, _ = _derive_labels(entry["source_name"], entry["source_ref"])
        if source_kind is None:
            raise _UnlabelledSource(artifact_id)
        refs.append(
            {
                "artifact_id": artifact_id,
                "artifact_version": entry["source_version"],
                "source_kind": source_kind,
                "source_ref": entry["source_ref"],
            }
        )
    return refs


def _merge_refs(
    refs: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    for ref in new:
        if ref not in refs:
            refs.append(ref)
    return refs


def _comparison_score_rows(
    con: duckdb.DuckDBPyConnection,
    *,
    scenario_id: str,
    intervention_ids: list[str],
) -> list[tuple[object, ...]]:
    placeholders = ", ".join("?" for _ in intervention_ids)
    return con.execute(
        f"""SELECT m.artifact_id, m.availability, m.model_mode, m.identity_json, m.limitations_json,
                  s.metric, s.score_value, s.score_unit, s.score_components_json,
                  s.regulatory_label, m.assumptions_json
             FROM mn_artifact_manifests AS m
             JOIN mn_score_results AS s USING (artifact_id)
             WHERE m.artifact_kind='score' AND m.geography_id='mn'
               AND json_extract_string(m.identity_json, '$.source_identity.family')='comparison'
               AND json_extract_string(m.identity_json, '$.source_identity.scenario_id')=?
               AND json_extract_string(m.identity_json, '$.source_identity.intervention_id')
                   IN ({placeholders})
             ORDER BY m.artifact_id ASC""",
        [scenario_id, *intervention_ids],
    ).fetchall()


def _unavailable_comparison_manifests(
    con: duckdb.DuckDBPyConnection,
    *,
    scenario_id: str,
    intervention_ids: list[str],
) -> list[tuple[object, ...]]:
    placeholders = ", ".join("?" for _ in intervention_ids)
    return con.execute(
        f"""SELECT artifact_id, identity_json,
                   json_extract_string(identity_json, '$.source_identity.intervention_id')
              FROM mn_artifact_manifests
             WHERE artifact_kind='score' AND geography_id='mn'
               AND availability='unavailable' AND model_mode='not_applicable'
               AND json_extract_string(identity_json, '$.source_identity.family')='comparison'
               AND json_extract_string(identity_json, '$.source_identity.scenario_id')=?
               AND json_extract_string(identity_json, '$.source_identity.intervention_id')
                   IN ({placeholders})
             ORDER BY artifact_id ASC""",
        [scenario_id, *intervention_ids],
    ).fetchall()


def _unavailable_critical_manifests(
    con: duckdb.DuckDBPyConnection, *, region: str
) -> list[tuple[object, ...]]:
    return con.execute(
        """SELECT artifact_id, identity_json FROM mn_artifact_manifests
             WHERE artifact_kind='score' AND geography_id=?
               AND availability='unavailable' AND model_mode='not_applicable'
               AND json_extract_string(identity_json, '$.source_identity.family')='critical_elements'
               AND json_extract_string(identity_json, '$.source_identity.region')=?
               AND json_extract_string(identity_json, '$.source_identity.status')='unavailable'
             ORDER BY artifact_id ASC""",
        [region, region],
    ).fetchall()


def _score_payload(
    con: duckdb.DuckDBPyConnection, row: tuple[object, ...]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    (
        artifact_id,
        availability,
        model_mode,
        identity_json,
        limitations_json,
        metric,
        score_value,
        score_unit,
        components_json,
        regulatory_label,
        assumptions_json,
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
        "assumptions": _as_limitations(assumptions_json),
    }
    identity = _as_object(identity_json, label="identity_json")
    source_identity = _as_object(
        identity.get("source_identity"), label="identity_json.source_identity"
    )
    return payload, payload["score_components"], source_identity


def _unavailable_source_identity(value: object, *, keys: set[str]) -> dict[str, Any]:
    identity = _as_object(value, label="identity_json")
    return _require_identity_keys(
        _as_object(
            identity.get("source_identity"), label="identity_json.source_identity"
        ),
        keys=keys,
        label="identity_json.source_identity",
    )


@router.post("/compare")
def compare(payload: CompareRequest, request: Request) -> dict[str, Any]:
    """Read named topology comparison scores; never derive an intervention delta."""

    con = _connect(request)
    try:
        missing = _missing_tables(con)
        if missing:
            raise _unavailable("missing", artifact=missing[0])
        rows = (
            _comparison_score_rows(
                con,
                scenario_id=payload.scenario_id,
                intervention_ids=payload.intervention_ids,
            )
            if _has_tables(con, "mn_score_results", "mn_artifact_provenance")
            else []
        )
        selected: dict[str, dict[str, Any]] = {}
        a8: dict[str, dict[str, Any]] = {}
        baselines: set[str] = set()
        assumptions: list[str] = []
        refs: list[dict[str, Any]] = []
        unsupported = False
        for row in rows:
            try:
                score, components, source_identity = _score_payload(con, row)
            except _DeclaredUnavailable as exc:
                raise _unavailable(
                    "artifact_unavailable", artifact="comparison"
                ) from exc
            except _PersistedInvalid as exc:
                raise _unavailable(
                    "invalid_persisted_result", artifact="mn_score_results"
                ) from exc
            if (
                components.get("scenario_id") != payload.scenario_id
                or _require_identity_keys(
                    source_identity,
                    keys={"family", "scenario_id", "intervention_id"},
                    label="comparison source identity",
                ).get("family")
                != "comparison"
                or source_identity.get("scenario_id") != payload.scenario_id
            ):
                raise _unavailable("invalid_persisted_result", artifact="comparison")
            intervention_id = components.get("intervention_id")
            if (
                intervention_id not in payload.intervention_ids
                or source_identity.get("intervention_id") != intervention_id
            ):
                raise _unavailable("invalid_persisted_result", artifact="comparison")
            if score["model_mode"] != "topology":
                unsupported = True
                continue
            key = str(intervention_id)
            if key in selected:
                raise _unavailable("ambiguous_identity", artifact="comparison")
            try:
                a8[key] = _a8_intervention(key, components)
                baselines.add(
                    _as_string(
                        _required_component(components, "baseline_run_id"),
                        label="baseline_run_id",
                    )
                )
            except _MissingDelta as exc:
                raise _unavailable(
                    "persisted_delta_unavailable",
                    artifact="comparison",
                    field=str(exc.args[0]),
                    intervention_id=key,
                ) from exc
            except _PersistedInvalid as exc:
                raise _unavailable(
                    "invalid_persisted_result", artifact="comparison"
                ) from exc
            try:
                _merge_refs(
                    refs, _artifact_refs(score["artifact_id"], score["provenance"])
                )
            except _UnlabelledSource as exc:
                raise _unavailable(
                    "source_kind_unavailable", artifact="comparison"
                ) from exc
            for assumption in score["assumptions"]:
                if assumption not in assumptions:
                    assumptions.append(assumption)
            selected[key] = {
                **score,
                "scenario_id": payload.scenario_id,
                "intervention_id": str(intervention_id),
            }
        if unsupported:
            raise _unavailable("unsupported_model_mode", artifact="comparison")
        if set(selected) != set(payload.intervention_ids):
            unavailable = _unavailable_comparison_manifests(
                con,
                scenario_id=payload.scenario_id,
                intervention_ids=[
                    item for item in payload.intervention_ids if item not in selected
                ],
            )
            for _, identity_json, intervention_id in unavailable:
                try:
                    identity = _unavailable_source_identity(
                        identity_json,
                        keys={"family", "scenario_id", "intervention_id"},
                    )
                except _PersistedInvalid as exc:
                    raise _unavailable(
                        "invalid_persisted_result", artifact="comparison"
                    ) from exc
                if identity == {
                    "family": "comparison",
                    "scenario_id": payload.scenario_id,
                    "intervention_id": intervention_id,
                }:
                    raise _unavailable("artifact_unavailable", artifact="comparison")
            raise _unavailable("no_qualified_result", artifact="comparison")
        if len(baselines) != 1:
            # Two qualified artifacts citing different baselines cannot be
            # compared; saying so is the only honest answer.
            raise _unavailable("ambiguous_identity", artifact="comparison")
        return {
            # The frozen A8 `compare_interventions` fields, read from the
            # persisted components and never derived here.
            "status": "available",
            "provenance": refs,
            "scenario_id": payload.scenario_id,
            "baseline_run_id": next(iter(baselines)),
            "interventions": [a8[item] for item in payload.intervention_ids],
            "assumptions": assumptions,
            # The persisted evidence behind each A8 row, keyed by intervention.
            # Documented in docs/specs/05-copilot.md as this route's addition to
            # the A8 dict; the A8 half above validates against InterventionsData.
            "evidence": [selected[item] for item in payload.intervention_ids],
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
        rows = (
            con.execute(
                f"""SELECT m.artifact_id, m.availability, m.model_mode, m.identity_json, m.limitations_json,
                       s.metric, s.score_value, s.score_unit, s.score_components_json,
                       s.regulatory_label, m.assumptions_json
                  FROM mn_artifact_manifests AS m
                  JOIN mn_score_results AS s USING (artifact_id)
                  WHERE m.artifact_kind='score' AND m.geography_id=?
                    AND json_extract_string(m.identity_json, '$.source_identity.family')='critical_elements'
                    AND json_extract_string(m.identity_json, '$.source_identity.region')=?
                    AND s.metric='critical_element'
                  {clause}""",
                [region, region, *parameters],
            ).fetchall()
            if _has_tables(con, "mn_score_results", "mn_artifact_provenance")
            else []
        )
        if not rows:
            for _, identity_json in _unavailable_critical_manifests(con, region=region):
                try:
                    identity = _unavailable_source_identity(
                        identity_json,
                        keys={"family", "region", "status"},
                    )
                except _PersistedInvalid as exc:
                    raise _unavailable(
                        "invalid_persisted_result", artifact="critical_elements"
                    ) from exc
                if identity == {
                    "family": "critical_elements",
                    "region": region,
                    "status": "unavailable",
                }:
                    raise _unavailable(
                        "artifact_unavailable", artifact="critical_elements"
                    )
            raise _unavailable("no_qualified_result", artifact="critical_elements")
        elements: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        for row in rows:
            try:
                score, components, source_identity = _score_payload(con, row)
                if score["model_mode"] != "topology":
                    raise _unavailable(
                        "unsupported_model_mode", artifact="critical_elements"
                    )
                element_id = _as_string(
                    components.get("element_id"), label="element_id"
                )
                if (
                    _require_identity_keys(
                        source_identity,
                        keys={"family", "region", "scenario_id", "element_id"},
                        label="critical source identity",
                    ).get("family")
                    != "critical_elements"
                    or source_identity.get("region") != region
                    or source_identity.get("element_id") != element_id
                    or source_identity.get("scenario_id")
                    != components.get("scenario_id")
                ):
                    raise _PersistedInvalid(
                        "critical score identity disagrees with values"
                    )
                kind = components.get("kind")
                if kind not in {"line", "bus", "gen"}:
                    raise _PersistedInvalid("kind must be line, bus, or gen")
                runs = components.get("runs")
                if not isinstance(runs, int) or isinstance(runs, bool) or runs < 0:
                    raise _PersistedInvalid("runs must be a non-negative integer")
                _merge_refs(
                    refs, _artifact_refs(score["artifact_id"], score["provenance"])
                )
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
            except _UnlabelledSource as exc:
                raise _unavailable(
                    "source_kind_unavailable", artifact="critical_elements"
                ) from exc
            except _DeclaredUnavailable as exc:
                raise _unavailable(
                    "artifact_unavailable", artifact="critical_elements"
                ) from exc
            except _PersistedInvalid as exc:
                raise _unavailable(
                    "invalid_persisted_result", artifact="critical_elements"
                ) from exc
        matching = con.execute(
            """SELECT count(*)
                 FROM mn_artifact_manifests AS m
                 JOIN mn_score_results AS s USING (artifact_id)
                WHERE m.artifact_kind='score' AND m.geography_id=?
                  AND json_extract_string(m.identity_json,
                        '$.source_identity.family')='critical_elements'
                  AND json_extract_string(m.identity_json,
                        '$.source_identity.region')=?
                  AND s.metric='critical_element'""",
            [region, region],
        ).fetchone()
        total = int(matching[0]) if matching else 0
        return {
            # The frozen A8 `top_critical_elements` fields.
            "status": "available",
            "provenance": refs,
            "region": region,
            "n": n,
            "scenario_ids": sorted({element["scenario_id"] for element in elements}),
            "elements": [
                {
                    "element_id": element["element_id"],
                    "kind": element["kind"],
                    "lost_load_mw": element["lost_load_mw"],
                    "critical_loads_lost": element["critical_loads_lost"],
                    "runs": element["runs"],
                }
                for element in elements
            ],
            # `partial` means "fewer than n elements have any persisted run"
            # (docs/specs/05-copilot.md), counted over the whole filtered
            # relation - not "this page ended", which offset would make false.
            "partial": total < n,
            # This route's documented addition to the A8 dict: the page cursor
            # and the persisted evidence behind each element above.
            "offset": offset,
            "evidence": elements,
        }
    except duckdb.BinderException as exc:
        raise _unavailable("schema_mismatch", artifact="mn_score_results") from exc
    except duckdb.Error as exc:
        raise _unavailable("query_failed", artifact="mn_score_results") from exc
    finally:
        con.close()

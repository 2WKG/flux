"""Read the persisted Minnesota aggregate stress artifact without computing it.

``GET /minnesota/aggregate`` selects one, and only one, available aggregate
model result whose persisted identity names the Minnesota aggregate manifest.
The route deliberately has no fallback to a fixture, topology model, or derived
value: absent, ambiguous, or malformed persistence is an unavailable response.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any, Final

import duckdb
from fastapi import APIRouter, Request

from copilot.api import UnavailableError
from copilot.config import Settings
from pipelines.fixtures.builder import artifact_id_for
from pipelines.minnesota_aggregate_runtime import (
    FORMULA,
    METRIC_NAME,
    METRIC_UNIT,
    MODEL_NAME,
    MODEL_VERSION,
    AggregateRuntimeError,
    aggregate_identity,
    expected_aggregate_provenance,
    expected_aggregate_score_components,
    load_aggregate_inputs,
)
from pipelines.minnesota_schema import SCHEMA_VERSION

router = APIRouter(tags=["minnesota"])

ARTIFACT: Final = "mn_artifact_manifests"
SOURCE_IDENTITY: Final = "minnesota_aggregate_manifest_v1"
REQUIRED_TABLES: Final = (
    "mn_artifact_manifests",
    "mn_model_results",
    "mn_score_results",
    "mn_artifact_provenance",
)

_SELECTED_MANIFEST_SQL: Final = """
    SELECT artifact_id, contract_version, identity_json, limitations_json
    FROM mn_artifact_manifests
    WHERE artifact_kind = 'model_result'
      AND geography_id = 'mn'
      AND availability = 'available'
      AND model_mode = 'aggregate'
      AND json_extract_string(identity_json, '$.source_identity') = ?
    ORDER BY artifact_id ASC
"""
_ARTIFACT_SQL: Final = """
    SELECT m.artifact_id, m.availability, m.model_mode, m.limitations_json,
           r.model_name, r.model_version, r.model_run_id, r.input_manifest_sha256,
           r.validation_status, r.metric_name, r.metric_value, r.metric_unit, r.formula,
           r.base_mva, r.solver_version, r.converter_version,
           s.metric, s.score_value, s.score_unit, s.score_components_json
    FROM mn_artifact_manifests AS m
    JOIN mn_model_results AS r USING (artifact_id)
    JOIN mn_score_results AS s USING (artifact_id)
    WHERE m.artifact_id = ?
"""
_PROVENANCE_SQL: Final = """
    SELECT source_name, source_ref, source_version, retrieved_at,
           license_or_terms, source_record_id, content_sha256, is_derived
    FROM mn_artifact_provenance
    WHERE artifact_id = ?
    ORDER BY provenance_ordinal ASC
"""


class _PersistedInvalid(ValueError):
    """A row exists but cannot support the published aggregate contract."""


def _unavailable(reason: str, *, artifact: str = ARTIFACT) -> UnavailableError:
    messages = {
        "database_missing": "The Minnesota artifact database is unavailable.",
        "missing": "The required Minnesota aggregate persistence is unavailable.",
        "missing_identity": "No persisted Minnesota aggregate artifact matches the required identity.",
        "ambiguous_identity": "Multiple persisted Minnesota aggregate artifacts match the required identity.",
        "invalid_persisted_artifact": "The persisted Minnesota aggregate artifact is incomplete or invalid.",
        "schema_mismatch": "The Minnesota aggregate persistence schema is incompatible.",
        "query_failed": "The Minnesota aggregate artifact could not be read.",
    }
    return UnavailableError(
        messages[reason], details={"artifact": artifact, "reason": reason}
    )


def _connect(settings: Settings) -> duckdb.DuckDBPyConnection:
    try:
        return duckdb.connect(str(settings.duckdb_path), read_only=True)
    except duckdb.Error as exc:
        raise _unavailable("database_missing") from exc


def _missing_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    present = {
        name
        for (name,) in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    return [table for table in REQUIRED_TABLES if table not in present]


def _json_object(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise _PersistedInvalid(f"{label} is not JSON") from exc
    if not isinstance(value, dict):
        raise _PersistedInvalid(f"{label} must be a JSON object")
    return value


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise _PersistedInvalid(f"{label} must be a non-empty string")
    return value


def _finite_number(value: object, *, label: str) -> float:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise _PersistedInvalid(f"{label} must be a finite number")
    return float(value)


def _string_list(value: object, *, label: str) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise _PersistedInvalid(f"{label} is not JSON") from exc
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise _PersistedInvalid(f"{label} must be a non-empty string array")
    return value


def _aggregate_manifest(value: object) -> dict[str, Any]:
    manifest = _json_object(value, label="aggregate_manifest")
    if manifest.get("format") != "flux-minnesota-aggregate-v1":
        raise _PersistedInvalid("aggregate_manifest.format is invalid")
    if manifest.get("model_mode") != "aggregate":
        raise _PersistedInvalid("aggregate_manifest.model_mode is invalid")
    if manifest.get("allocation_status") != "unavailable":
        raise _PersistedInvalid("aggregate_manifest.allocation_status is invalid")
    _string(
        manifest.get("allocation_limit"), label="aggregate_manifest.allocation_limit"
    )
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise _PersistedInvalid("aggregate_manifest.sources must be non-empty")
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        source_object = _json_object(
            source, label=f"aggregate_manifest.sources[{index}]"
        )
        source_ids.add(
            _string(
                source_object.get("id"), label=f"aggregate_manifest.sources[{index}].id"
            )
        )
    if source_ids != {
        "tiger_counties_2024",
        "mngeo_service_areas_2026",
        "eia860_2024",
        "eia930_balance_2024_h1",
    }:
        raise _PersistedInvalid(
            "aggregate_manifest.sources does not name the accepted inputs"
        )
    return manifest


def _stress_metric(
    *,
    metric_name: object,
    metric_value: object,
    metric_unit: object,
    formula: object,
    context: object,
) -> dict[str, Any]:
    stress_context = _json_object(context, label="stress_context")
    required_strings = (
        "source_label",
        "time_basis",
        "window_start_utc",
        "window_end_utc",
        "window_peak_hour_utc",
    )
    for key in required_strings:
        _string(stress_context.get(key), label=f"stress_context.{key}")
    for key in (
        "window_peak_demand_mw",
        "scored_hours",
        "min_index",
        "mean_index",
        "p95_index",
    ):
        _finite_number(stress_context.get(key), label=f"stress_context.{key}")
    return {
        "metric_name": _string(metric_name, label="metric_name"),
        "metric_value": _finite_number(metric_value, label="metric_value"),
        "unit": _string(metric_unit, label="metric_unit"),
        "formula": _string(formula, label="formula"),
        **stress_context,
    }


def _identity(
    value: object,
    *,
    artifact_id: str,
    input_manifest_sha256: object,
    expected_identity: dict[str, str],
) -> dict[str, str]:
    identity = _json_object(value, label="identity_json")
    expected_artifact_id = artifact_id_for(expected_identity)
    if artifact_id != expected_artifact_id or identity != expected_identity:
        raise _PersistedInvalid(
            "identity_json does not name the accepted aggregate result"
        )
    if input_manifest_sha256 != expected_identity["content_sha256"]:
        raise _PersistedInvalid("input_manifest_sha256 does not match identity_json")
    return {
        "artifact_id": artifact_id,
        **expected_identity,
    }


def _provenance(rows: list[tuple[object, ...]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
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
            raise _PersistedInvalid("provenance.source_record_id is invalid")
        if not isinstance(retrieved_at, datetime):
            raise _PersistedInvalid("provenance.retrieved_at is invalid")
        if not isinstance(is_derived, bool):
            raise _PersistedInvalid("provenance.is_derived is invalid")
        result.append(
            {
                "source_name": _string(source_name, label="provenance.source_name"),
                "source_ref": _string(source_ref, label="provenance.source_ref"),
                "source_version": _string(
                    source_version, label="provenance.source_version"
                ),
                "retrieved_at": retrieved_at.replace(tzinfo=UTC)
                .isoformat()
                .replace("+00:00", "Z"),
                "license_or_terms": _string(
                    license_or_terms, label="provenance.license_or_terms"
                ),
                "source_record_id": source_record_id,
                "content_sha256": _string(
                    content_sha256, label="provenance.content_sha256"
                ),
                "is_derived": is_derived,
            }
        )
    if not result:
        raise _PersistedInvalid("aggregate artifact has no provenance")
    return result


def _expected_provenance(inputs: Any) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "retrieved_at": row["retrieved_at"]
            .replace(tzinfo=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
        }
        for row in expected_aggregate_provenance(inputs)
    ]


def resolve_minnesota_aggregate(settings: Settings) -> dict[str, Any]:
    """Read one persisted aggregate result for bounded HTTP/tool context use."""

    try:
        inputs = load_aggregate_inputs()
    except AggregateRuntimeError as exc:
        raise _unavailable("invalid_persisted_artifact") from exc
    expected_identity = aggregate_identity(inputs.manifest_sha256)
    con = _connect(settings)
    try:
        missing = _missing_tables(con)
        if missing:
            raise _unavailable("missing", artifact=missing[0])
        try:
            selected = con.execute(
                _SELECTED_MANIFEST_SQL, [expected_identity["source_identity"]]
            ).fetchall()
            if not selected:
                raise _unavailable("missing_identity")
            if len(selected) != 1:
                raise _unavailable("ambiguous_identity")
            artifact_id, contract_version, identity_json, limitations_json = selected[0]
            row = con.execute(_ARTIFACT_SQL, [artifact_id]).fetchone()
            provenance_rows = con.execute(_PROVENANCE_SQL, [artifact_id]).fetchall()
        except duckdb.BinderException as exc:
            raise _unavailable("schema_mismatch") from exc
        except duckdb.Error as exc:
            raise _unavailable("query_failed") from exc
    finally:
        con.close()

    if row is None:
        raise _unavailable("invalid_persisted_artifact")
    try:
        (
            persisted_artifact_id,
            availability,
            model_mode,
            persisted_limitations,
            model_name,
            model_version,
            model_run_id,
            input_manifest_sha256,
            validation_status,
            metric_name,
            metric_value,
            metric_unit,
            formula,
            base_mva,
            solver_version,
            converter_version,
            score_metric,
            score_value,
            score_unit,
            components_json,
        ) = row
        if artifact_id != persisted_artifact_id or contract_version != SCHEMA_VERSION:
            raise _PersistedInvalid("selected artifact identity changed")
        if availability != "available" or model_mode != "aggregate":
            raise _PersistedInvalid("selected manifest is not available aggregate mode")
        if limitations_json != persisted_limitations:
            raise _PersistedInvalid("selected limitations changed")
        if (
            base_mva is not None
            or solver_version is not None
            or converter_version is not None
        ):
            raise _PersistedInvalid("aggregate solver fields must be null")
        identity = _identity(
            identity_json,
            artifact_id=_string(artifact_id, label="artifact_id"),
            input_manifest_sha256=input_manifest_sha256,
            expected_identity=expected_identity,
        )
        components = _json_object(components_json, label="score_components_json")
        if components != expected_aggregate_score_components(inputs):
            raise _PersistedInvalid("score components do not match accepted evidence")
        manifest = _aggregate_manifest(components.get("aggregate_manifest"))
        stress_metric = _stress_metric(
            metric_name=metric_name,
            metric_value=metric_value,
            metric_unit=metric_unit,
            formula=formula,
            context=components.get("stress_context"),
        )
        if (
            model_name != MODEL_NAME
            or model_version != MODEL_VERSION
            or model_run_id != f"aggregate-runtime-v1:{inputs.manifest_sha256[:16]}"
            or validation_status != "validated"
            or stress_metric["metric_name"] != METRIC_NAME
            or stress_metric["metric_value"] != inputs.peak_demand_mw
            or stress_metric["unit"] != METRIC_UNIT
            or stress_metric["formula"] != FORMULA
        ):
            raise _PersistedInvalid("model result does not match accepted evidence")
        if (
            score_metric != stress_metric["metric_name"]
            or _finite_number(score_value, label="score_value")
            != stress_metric["metric_value"]
            or score_unit != stress_metric["unit"]
        ):
            raise _PersistedInvalid("score result does not match the model metric")
        provenance = _provenance(provenance_rows)
        if provenance != _expected_provenance(inputs):
            raise _PersistedInvalid("provenance does not match accepted evidence")
        return {
            "artifact_id": _string(artifact_id, label="artifact_id"),
            "artifact_contract_version": _string(
                contract_version, label="contract_version"
            ),
            "artifact_identity": identity,
            "model_mode": "aggregate",
            "availability": "available",
            "aggregate_manifest": manifest,
            "stress_metric": stress_metric,
            "provenance": provenance,
            "limitations": _string_list(limitations_json, label="limitations_json"),
            "prohibited_claims": _string_list(
                components.get("prohibited_claims"), label="prohibited_claims"
            ),
            "base_mva": None,
            "solver_version": None,
            "converter_version": None,
        }
    except _PersistedInvalid as exc:
        raise _unavailable("invalid_persisted_artifact") from exc


@router.get("/minnesota/aggregate")
def minnesota_aggregate(request: Request) -> dict[str, Any]:
    """Serve the one persisted aggregate Minnesota stress artifact."""

    settings: Settings = request.app.state.settings
    return resolve_minnesota_aggregate(settings)

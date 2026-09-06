"""Build a truthful Minnesota aggregate runtime copy from approved evidence.

The builder deliberately reads no raw geography and writes no facility points,
allocations, topology, flow, loading, outage, or solver data.  It copies an
existing DuckDB store to a new path, then appends one aggregate-mode model result
whose only numeric output is the peak of the committed MISO balancing-authority
context series.  That metric is explicitly not Minnesota demand.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from pipelines.fixtures.builder import artifact_id_for
from pipelines.minnesota_schema import SCHEMA_VERSION, ensure_minnesota_schema

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = Path("data/sources/minnesota-accepted-artifact-inventory.json")
MANIFEST_PATH = Path("pipelines/fixtures/inputs/minnesota_aggregate_manifest_v1.json")
EXPECTED_ARTIFACT_IDS = (
    "mn:aggregate:manifest:v1",
    "mn:facility_capacity:county:2024",
    "mn:facility_context:unassigned:2024",
    "mn:ba_context:miso:2024-h1",
)
MISO_ARTIFACT_ID = "mn:ba_context:miso:2024-h1"
MODEL_NAME = "minnesota_aggregate_peak_context"
MODEL_VERSION = "1"
METRIC_NAME = "miso_ba_peak_demand_mw"
METRIC_UNIT = "MW"
FORMULA = (
    "MAX(`Demand (MW)`) across the committed EIA-930 MISO balancing-authority "
    "context rows for 2024 H1; this is MISO BA context, not Minnesota demand."
)
PROHIBITED_CLAIMS = (
    "Minnesota demand allocation",
    "county or service-area load allocation",
    "facility dispatch",
    "topology, line, bus, flow, loading, trip, cascade, or outage inference",
    "an interconnection study",
)
SOURCE_VERSIONS = {
    "mn:aggregate:manifest:v1": "v1",
    "mn:facility_capacity:county:2024": "2024",
    "mn:facility_context:unassigned:2024": "2024",
    "mn:ba_context:miso:2024-h1": "2024-h1",
}


class AggregateRuntimeError(RuntimeError):
    """The approved aggregate evidence cannot safely produce a runtime copy."""


@dataclass(frozen=True)
class ApprovedInput:
    artifact_id: str
    source_path: Path
    content_sha256: str
    inventory_entry: dict[str, Any]


@dataclass(frozen=True)
class AggregateInputs:
    manifest: dict[str, Any]
    manifest_sha256: str
    approved: tuple[ApprovedInput, ...]
    peak_demand_mw: float
    peak_hour_utc: str
    scored_hours: int
    window_start_utc: str
    window_end_utc: str
    min_index: float
    mean_index: float
    p95_index: float


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonical_text_sha256(path: Path) -> str:
    """Hash committed text as UTF-8 with CRLF normalized to LF."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AggregateRuntimeError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise AggregateRuntimeError(f"{label} must be an object: {path}")
    return value


def _sha_from_inventory(value: object, artifact_id: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise AggregateRuntimeError(
            f"approved artifact {artifact_id!r} has no SHA-256 inventory digest"
        )
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise AggregateRuntimeError(
            f"approved artifact {artifact_id!r} has an invalid SHA-256 inventory digest"
        )
    return digest


def _path_under_root(root: Path, relative: object, artifact_id: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise AggregateRuntimeError(
            f"approved artifact {artifact_id!r} has no source_path"
        )
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise AggregateRuntimeError(
            f"approved artifact {artifact_id!r} source_path escapes repository"
        ) from exc
    if not path.is_file():
        raise AggregateRuntimeError(
            f"approved artifact {artifact_id!r} source file is missing: {relative}"
        )
    return path


def verify_gate0_inputs(
    *, repository_root: Path = REPOSITORY_ROOT, inventory_path: Path = INVENTORY_PATH
) -> tuple[dict[str, Any], tuple[ApprovedInput, ...]]:
    """Verify all and only the four Gate 0-approved input artifacts and digests."""
    root = repository_root.resolve()
    inventory_file = (
        inventory_path if inventory_path.is_absolute() else root / inventory_path
    )
    inventory = _load_json(inventory_file, "Minnesota accepted-artifact inventory")
    entries = inventory.get("accepted_product_artifacts")
    if not isinstance(entries, list):
        raise AggregateRuntimeError("inventory has no accepted_product_artifacts list")
    if len(entries) != len(EXPECTED_ARTIFACT_IDS):
        raise AggregateRuntimeError(
            "inventory accepted artifacts must be exactly the four Gate 0 aggregate inputs"
        )
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise AggregateRuntimeError(
                "inventory has a malformed accepted artifact entry"
            )
        artifact_id = entry.get("artifact_id")
        if artifact_id not in EXPECTED_ARTIFACT_IDS:
            raise AggregateRuntimeError(
                "inventory accepted artifacts must be exactly the four Gate 0 aggregate inputs"
            )
        if artifact_id in by_id:
            raise AggregateRuntimeError(
                f"inventory repeats approved artifact {artifact_id!r}"
            )
        by_id[artifact_id] = entry
    if set(by_id) != set(EXPECTED_ARTIFACT_IDS):
        raise AggregateRuntimeError(
            "inventory accepted artifacts must be exactly the four Gate 0 aggregate inputs"
        )

    approved: list[ApprovedInput] = []
    for artifact_id in EXPECTED_ARTIFACT_IDS:
        entry = by_id[artifact_id]
        policy = entry.get("truth_label_policy")
        if not isinstance(policy, dict) or policy.get("default") != "source_backed":
            raise AggregateRuntimeError(
                f"approved artifact {artifact_id!r} must remain source_backed"
            )
        source_path = _path_under_root(root, entry.get("source_path"), artifact_id)
        expected_digest = _sha_from_inventory(entry.get("content_sha256"), artifact_id)
        actual_digest = _canonical_text_sha256(source_path)
        if actual_digest != expected_digest:
            raise AggregateRuntimeError(
                f"approved artifact {artifact_id!r} SHA-256 mismatch: "
                f"expected {expected_digest}, got {actual_digest}"
            )
        approved.append(
            ApprovedInput(
                artifact_id=artifact_id,
                source_path=source_path,
                content_sha256=actual_digest,
                inventory_entry=entry,
            )
        )
    return inventory, tuple(approved)


def _manifest_from(approved: tuple[ApprovedInput, ...]) -> tuple[dict[str, Any], str]:
    manifest_input = next(
        item for item in approved if item.artifact_id == EXPECTED_ARTIFACT_IDS[0]
    )
    manifest = _load_json(manifest_input.source_path, "aggregate manifest")
    if manifest.get("format") != "flux-minnesota-aggregate-v1":
        raise AggregateRuntimeError("aggregate manifest format is incompatible")
    if manifest.get("model_mode") != "aggregate":
        raise AggregateRuntimeError(
            "aggregate manifest must declare aggregate model mode"
        )
    if manifest.get("allocation_status") != "unavailable":
        raise AggregateRuntimeError(
            "aggregate manifest must keep allocation unavailable"
        )
    if (
        not isinstance(manifest.get("allocation_limit"), str)
        or not manifest["allocation_limit"]
    ):
        raise AggregateRuntimeError("aggregate manifest needs an allocation limitation")
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise AggregateRuntimeError("aggregate manifest has no sources")
    source_ids = {source.get("id") for source in sources if isinstance(source, dict)}
    if source_ids != {
        "tiger_counties_2024",
        "mngeo_service_areas_2026",
        "eia860_2024",
        "eia930_balance_2024_h1",
    }:
        raise AggregateRuntimeError(
            "aggregate manifest source inventory is incompatible"
        )
    return manifest, manifest_input.content_sha256


def _miso_peak(
    context_path: Path, manifest: dict[str, Any]
) -> tuple[float, str, int, str, str, float, float, float]:
    sources = {source["id"]: source for source in manifest["sources"]}
    context = sources["eia930_balance_2024_h1"]
    expected_rows = context.get("rows")
    if not isinstance(expected_rows, int) or expected_rows <= 0:
        raise AggregateRuntimeError("aggregate manifest lacks MISO context row count")
    try:
        with context_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except OSError as exc:
        raise AggregateRuntimeError(
            f"cannot read MISO context: {context_path}"
        ) from exc
    required = {"UTC Time at End of Hour", "Demand (MW)"}
    if not rows or not required <= set(rows[0]):
        raise AggregateRuntimeError("MISO context lacks UTC end-of-hour demand columns")
    if len(rows) != expected_rows:
        raise AggregateRuntimeError(
            f"MISO context rows mismatch: expected {expected_rows}, got {len(rows)}"
        )
    peak_value: float | None = None
    peak_time: datetime | None = None
    seen: set[datetime] = set()
    values: list[float] = []
    for row in rows:
        try:
            timestamp = datetime.fromisoformat(row["UTC Time at End of Hour"])
            value = float(row["Demand (MW)"])
        except (TypeError, ValueError) as exc:
            raise AggregateRuntimeError(
                "MISO context contains invalid timestamp or demand"
            ) from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() != UTC.utcoffset(
            timestamp
        ):
            raise AggregateRuntimeError("MISO context timestamp must be UTC")
        if timestamp in seen:
            raise AggregateRuntimeError(
                "MISO context repeats a UTC end-of-hour timestamp"
            )
        if not math.isfinite(value):
            raise AggregateRuntimeError("MISO context demand must be finite")
        seen.add(timestamp)
        values.append(value)
        if peak_value is None or value > peak_value:
            peak_value, peak_time = value, timestamp
    assert peak_value is not None and peak_time is not None
    start, end = min(seen), max(seen)
    sorted_values = sorted(values)
    # Nearest-rank p95 is explicit and deterministic for the full fixed window.
    p95_value = sorted_values[math.ceil(0.95 * len(sorted_values)) - 1]
    return (
        peak_value,
        peak_time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        len(rows),
        start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        min(values) / peak_value,
        (sum(values) / len(values)) / peak_value,
        p95_value / peak_value,
    )


def load_aggregate_inputs(
    *, repository_root: Path = REPOSITORY_ROOT, inventory_path: Path = INVENTORY_PATH
) -> AggregateInputs:
    """Load verified evidence and calculate the one permitted aggregate metric."""
    _, approved = verify_gate0_inputs(
        repository_root=repository_root, inventory_path=inventory_path
    )
    manifest, manifest_sha256 = _manifest_from(approved)
    context_input = next(
        item for item in approved if item.artifact_id == MISO_ARTIFACT_ID
    )
    (
        peak_demand_mw,
        peak_hour_utc,
        scored_hours,
        window_start_utc,
        window_end_utc,
        min_index,
        mean_index,
        p95_index,
    ) = _miso_peak(context_input.source_path, manifest)
    return AggregateInputs(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        approved=approved,
        peak_demand_mw=peak_demand_mw,
        peak_hour_utc=peak_hour_utc,
        scored_hours=scored_hours,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        min_index=min_index,
        mean_index=mean_index,
        p95_index=p95_index,
    )


def aggregate_identity(manifest_sha256: str) -> dict[str, str]:
    """Return the contract's complete canonical identity for this model result."""
    return {
        "artifact_kind": "model_result",
        "geography_id": "mn",
        "model_mode": "aggregate",
        "source_identity": "minnesota_aggregate_manifest_v1",
        "source_version": "v1",
        "content_sha256": manifest_sha256,
    }


def expected_aggregate_provenance(
    inputs: AggregateInputs,
) -> tuple[dict[str, Any], ...]:
    """Return the complete ordered provenance contract for the accepted inputs."""
    manifest = inputs.manifest
    retrieved_at = _utc_timestamp(
        manifest["retrieved_at"], "aggregate manifest retrieved_at"
    )
    return tuple(
        {
            "source_name": item.artifact_id,
            "source_ref": item.inventory_entry["source_path"],
            "source_version": SOURCE_VERSIONS[item.artifact_id],
            "retrieved_at": retrieved_at,
            "license_or_terms": "unknown",
            "source_record_id": item.artifact_id,
            "content_sha256": item.content_sha256,
            "is_derived": False,
        }
        for item in inputs.approved
    )


def _utc_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise AggregateRuntimeError(f"{field} must be an ISO-8601 timestamp")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AggregateRuntimeError(f"{field} is not ISO-8601") from exc
    if timestamp.tzinfo is None:
        raise AggregateRuntimeError(f"{field} must include UTC offset")
    return timestamp.astimezone(UTC).replace(tzinfo=None)


def expected_aggregate_score_components(inputs: AggregateInputs) -> dict[str, Any]:
    """Return the exact score-component contract derived from approved evidence."""
    return {
        "artifact_version": "v1",
        "aggregate_manifest": {
            key: inputs.manifest[key]
            for key in (
                "format",
                "model_mode",
                "allocation_status",
                "allocation_limit",
                "sources",
            )
        },
        "stress_context": {
            "source_label": "MISO balancing authority (not Minnesota demand)",
            "time_basis": "UTC end of hour",
            "window_start_utc": inputs.window_start_utc,
            "window_end_utc": inputs.window_end_utc,
            "window_peak_demand_mw": inputs.peak_demand_mw,
            "window_peak_hour_utc": inputs.peak_hour_utc,
            "scored_hours": inputs.scored_hours,
            "min_index": inputs.min_index,
            "mean_index": inputs.mean_index,
            "p95_index": inputs.p95_index,
        },
        "prohibited_claims": list(PROHIBITED_CLAIMS),
    }


def _write_aggregate_record(
    con: duckdb.DuckDBPyConnection, inputs: AggregateInputs
) -> str:
    identity = aggregate_identity(inputs.manifest_sha256)
    artifact_id = artifact_id_for(identity)
    assumptions = [
        "The metric takes the maximum committed EIA-930 MISO balancing-authority demand value over the retained 2024 H1 rows.",
        "MISO balancing-authority context is retained without allocation to Minnesota, counties, service areas, or facilities.",
    ]
    limitations = [
        "This is MISO balancing-authority context, not Minnesota demand.",
        "No reviewed BA-to-Minnesota allocation crosswalk is available.",
        "This aggregate result is not a transmission-flow, outage, cascade, or interconnection simulation.",
    ]
    input_ids = [item.artifact_id for item in inputs.approved]
    con.execute("BEGIN")
    try:
        con.execute(
            "INSERT INTO mn_artifact_manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                artifact_id,
                "model_result",
                SCHEMA_VERSION,
                "mn",
                "available",
                "aggregate",
                _canonical_json(identity),
                _utc_timestamp(
                    inputs.manifest["retrieved_at"], "aggregate manifest retrieved_at"
                ),
                _canonical_json(assumptions),
                _canonical_json(limitations),
                _canonical_json(input_ids),
            ],
        )
        for ordinal, provenance in enumerate(expected_aggregate_provenance(inputs)):
            con.execute(
                "INSERT INTO mn_artifact_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    artifact_id,
                    ordinal,
                    provenance["source_name"],
                    provenance["source_ref"],
                    provenance["source_version"],
                    provenance["retrieved_at"],
                    provenance["license_or_terms"],
                    provenance["source_record_id"],
                    provenance["content_sha256"],
                    provenance["is_derived"],
                ],
            )
        for field_name, ordinal in (
            ("aggregate_manifest", 0),
            ("metric_value", 3),
            ("metric_unit", 3),
            ("formula", 3),
            ("window_peak_demand_mw", 3),
            ("window_peak_hour_utc", 3),
            ("scored_hours", 3),
            ("min_index", 3),
            ("mean_index", 3),
            ("p95_index", 3),
        ):
            con.execute(
                "INSERT INTO mn_artifact_field_provenance VALUES (?, ?, ?, ?)",
                [
                    artifact_id,
                    field_name,
                    ordinal,
                    "direct value from approved committed evidence",
                ],
            )
        con.execute(
            "INSERT INTO mn_model_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                artifact_id,
                MODEL_NAME,
                MODEL_VERSION,
                f"aggregate-runtime-v1:{inputs.manifest_sha256[:16]}",
                inputs.manifest_sha256,
                "validated",
                METRIC_NAME,
                inputs.peak_demand_mw,
                METRIC_UNIT,
                FORMULA,
                None,
                None,
                None,
            ],
        )
        con.execute(
            "INSERT INTO mn_score_results VALUES (?, ?, ?, ?, ?, ?)",
            [
                artifact_id,
                METRIC_NAME,
                inputs.peak_demand_mw,
                METRIC_UNIT,
                _canonical_json(expected_aggregate_score_components(inputs)),
                "source_supported",
            ],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return artifact_id


def _verify_read_only_source(source: Path) -> None:
    try:
        con = duckdb.connect(str(source), read_only=True)
    except duckdb.Error as exc:
        raise AggregateRuntimeError(
            f"source is not a readable DuckDB database: {source}"
        ) from exc
    try:
        mn_tables = [
            name
            for (name,) in con.execute("SHOW TABLES").fetchall()
            if name.startswith("mn_")
        ]
        if mn_tables:
            raise AggregateRuntimeError(
                "source database already has a Minnesota namespace; "
                "build from the unmodified runtime store"
            )
    finally:
        con.close()


def build_aggregate_runtime(
    *,
    source_db: Path,
    output_db: Path,
    repository_root: Path = REPOSITORY_ROOT,
    inventory_path: Path = INVENTORY_PATH,
) -> dict[str, Any]:
    """Atomically copy ``source_db`` and persist the approved aggregate result.

    ``output_db`` must be a new path.  The input is opened read-only before the
    file copy, and the copied database is the only file ever opened for writes.
    """
    if source_db.is_symlink():
        raise AggregateRuntimeError("source database path must not be a symlink")
    if output_db.is_symlink():
        raise AggregateRuntimeError("output database path must not be a symlink")
    source = source_db.resolve()
    output = output_db.resolve()
    if not source.is_file():
        raise AggregateRuntimeError(f"source database is missing: {source}")
    if source == output:
        raise AggregateRuntimeError("source and output database paths must differ")
    if output.exists():
        raise AggregateRuntimeError(f"output database already exists: {output}")
    inputs = load_aggregate_inputs(
        repository_root=repository_root, inventory_path=inventory_path
    )
    _verify_read_only_source(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(tempfile.mkdtemp(prefix=f".{output.stem}-", dir=output.parent))
    stage_db = stage_dir / output.name
    try:
        shutil.copy2(source, stage_db)
        con = duckdb.connect(str(stage_db))
        try:
            ensure_minnesota_schema(con)
            artifact_id = _write_aggregate_record(con, inputs)
            ensure_minnesota_schema(con)
        finally:
            con.close()
        os.replace(stage_db, output)
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)
    return {
        "output_db": output,
        "artifact_id": artifact_id,
        "manifest_sha256": inputs.manifest_sha256,
        "metric_name": METRIC_NAME,
        "metric_value": inputs.peak_demand_mw,
        "metric_unit": METRIC_UNIT,
        "window_peak_hour_utc": inputs.peak_hour_utc,
        "scored_hours": inputs.scored_hours,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = build_aggregate_runtime(
        source_db=args.source_db, output_db=args.output_db
    )
    print(json.dumps(receipt, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

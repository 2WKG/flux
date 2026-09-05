"""Build source-backed Minnesota fixture metadata.

This framework deliberately does not ship a Minnesota topology, scenario, or
source claim. A caller supplies an accepted Minnesota artifact manifest; this
module validates its stable identity and provenance, then writes only the
``mn_*`` artifact relations owned by :mod:`pipelines.minnesota_schema`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from pipelines.minnesota_schema import SCHEMA_VERSION, ensure_minnesota_schema

INPUTS = Path(__file__).parent / "inputs"
MANIFEST = INPUTS / "manifest.json"

IDENTITY_FIELDS = (
    "artifact_kind",
    "geography_id",
    "model_mode",
    "source_identity",
    "source_version",
    "content_sha256",
)
COMMON_FIELDS = (
    "artifact_kind",
    "geography_id",
    "availability",
    "model_mode",
    "identity",
    "created_at",
    "assumptions",
    "limitations",
    "input_artifact_ids",
    "provenance",
)
PROVENANCE_FIELDS = (
    "source_name",
    "source_ref",
    "source_version",
    "retrieved_at",
    "license_or_terms",
    "source_record_id",
    "content_sha256",
    "is_derived",
)


class FixtureError(RuntimeError):
    """A Minnesota fixture was incomplete or contradicted the artifact contract."""


def _utc_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise FixtureError(f"{field} must be an ISO-8601 timestamp string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise FixtureError(f"{field} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise FixtureError(f"{field} must include an explicit UTC offset")
    return parsed.astimezone(UTC).replace(tzinfo=None)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def artifact_id_for(identity: dict[str, Any]) -> str:
    """Derive the contract artifact ID from a complete canonical identity."""
    if set(identity) != set(IDENTITY_FIELDS):
        raise FixtureError(f"identity fields must be exactly {list(IDENTITY_FIELDS)!r}")
    if not _is_sha256(identity["content_sha256"]):
        raise FixtureError("identity content_sha256 must be a lowercase SHA-256")
    kind = identity["artifact_kind"]
    if not isinstance(kind, str) or not kind:
        raise FixtureError("identity artifact_kind must be non-empty")
    digest = hashlib.sha256(_canonical_json(identity).encode()).hexdigest()[:16]
    return f"mn:{kind}:{digest}"


def load_manifest(manifest_path: Path = MANIFEST) -> dict[str, Any]:
    """Load a versioned Minnesota artifact manifest without inventing defaults."""
    if not manifest_path.exists():
        raise FixtureError(
            "no Minnesota fixture manifest is bundled; an accepted source manifest is required"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureError(f"manifest {manifest_path} is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise FixtureError("manifest must be an object")
    if "tables" in manifest:
        raise FixtureError(
            "legacy table fixtures are not compatible with the Minnesota contract"
        )
    if manifest.get("contract_version") != SCHEMA_VERSION:
        raise FixtureError(
            f"manifest contract_version must be {SCHEMA_VERSION!r}, got {manifest.get('contract_version')!r}"
        )
    if not isinstance(manifest.get("artifacts"), list) or not manifest["artifacts"]:
        raise FixtureError("manifest artifacts must be a non-empty array")
    return manifest


def _validate_provenance(entries: Any, availability: str) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise FixtureError("provenance must be an array")
    if availability == "available" and not entries:
        raise FixtureError("available artifacts require nonempty provenance")
    if availability == "unavailable" and entries:
        raise FixtureError("unavailable artifacts must have empty provenance")
    validated: list[dict[str, Any]] = []
    for ordinal, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != set(PROVENANCE_FIELDS):
            raise FixtureError(f"provenance[{ordinal}] has an incompatible shape")
        required = ("source_name", "source_ref", "source_version", "license_or_terms")
        if not all(
            isinstance(entry[field], str) and entry[field] for field in required
        ):
            raise FixtureError(
                f"provenance[{ordinal}] has an empty required source field"
            )
        if not _is_sha256(entry["content_sha256"]):
            raise FixtureError(
                f"provenance[{ordinal}] content_sha256 must be lowercase SHA-256"
            )
        if not isinstance(entry["is_derived"], bool):
            raise FixtureError(f"provenance[{ordinal}] is_derived must be boolean")
        if entry["source_record_id"] is not None and not isinstance(
            entry["source_record_id"], str
        ):
            raise FixtureError(
                f"provenance[{ordinal}] source_record_id must be string or null"
            )
        validated.append(
            entry
            | {
                "retrieved_at": _utc_timestamp(
                    entry["retrieved_at"], field=f"provenance[{ordinal}].retrieved_at"
                )
            }
        )
    return validated


def build_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate and normalize the Minnesota fixture artifacts in one manifest."""
    if manifest.get("contract_version") != SCHEMA_VERSION:
        raise FixtureError("manifest has an incompatible Minnesota contract_version")
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise FixtureError("manifest artifacts must be a non-empty array")

    built: list[dict[str, Any]] = []
    for index, artifact in enumerate(raw_artifacts):
        if not isinstance(artifact, dict) or not set(COMMON_FIELDS) <= set(artifact):
            raise FixtureError(
                f"artifacts[{index}] is missing required common-envelope fields"
            )
        if artifact["availability"] not in {"available", "unavailable"}:
            raise FixtureError(f"artifacts[{index}] has invalid availability")
        if artifact["model_mode"] not in {"topology", "aggregate", "not_applicable"}:
            raise FixtureError(f"artifacts[{index}] has invalid model_mode")
        if artifact["artifact_kind"] not in {"source_manifest", "fixture"}:
            raise FixtureError(f"artifacts[{index}] is outside fixture-framework scope")
        if artifact["model_mode"] != "not_applicable":
            raise FixtureError(
                f"artifacts[{index}] fixture metadata must not claim a model mode"
            )
        geography_id = artifact["geography_id"]
        if not isinstance(geography_id, str) or not geography_id.startswith("mn"):
            raise FixtureError(
                f"artifacts[{index}] geography_id must be Minnesota-qualified"
            )
        array_fields = ("assumptions", "limitations", "input_artifact_ids")
        if not all(
            isinstance(artifact[field], list)
            and all(isinstance(item, str) and item for item in artifact[field])
            for field in array_fields
        ):
            raise FixtureError(
                f"artifacts[{index}] arrays must contain non-empty strings"
            )
        identity = artifact["identity"]
        if not isinstance(identity, dict):
            raise FixtureError(f"artifacts[{index}] identity must be an object")
        expected_id = artifact_id_for(identity)
        identity_fields = ("artifact_kind", "geography_id", "model_mode")
        if any(identity[field] != artifact[field] for field in identity_fields):
            raise FixtureError(
                f"artifacts[{index}] identity must agree with its envelope"
            )
        provenance = _validate_provenance(
            artifact["provenance"], artifact["availability"]
        )
        domain = artifact.get("fixture")
        if artifact["artifact_kind"] == "fixture":
            if artifact["availability"] != "available" or not isinstance(domain, dict):
                raise FixtureError(
                    f"artifacts[{index}] available fixture metadata is required"
                )
            expected_domain = {"source_manifest_id", "fixture_label", "fallback_label"}
            if set(domain) != expected_domain:
                raise FixtureError(
                    f"artifacts[{index}] fixture metadata has an incompatible shape"
                )
            required = ("source_manifest_id", "fixture_label")
            if not all(
                isinstance(domain[field], str) and domain[field] for field in required
            ):
                raise FixtureError(
                    f"artifacts[{index}] fixture metadata has empty required fields"
                )
            if domain["fallback_label"] is not None and not isinstance(
                domain["fallback_label"], str
            ):
                raise FixtureError(
                    f"artifacts[{index}] fallback_label must be string or null"
                )
        elif domain is not None:
            raise FixtureError(
                f"artifacts[{index}] source_manifest must not carry fixture metadata"
            )
        built.append(
            {
                "artifact_id": expected_id,
                "artifact_kind": artifact["artifact_kind"],
                "geography_id": geography_id,
                "availability": artifact["availability"],
                "model_mode": artifact["model_mode"],
                "identity_json": _canonical_json(identity),
                "created_at": _utc_timestamp(
                    artifact["created_at"], field=f"artifacts[{index}].created_at"
                ),
                "assumptions": artifact["assumptions"],
                "limitations": artifact["limitations"],
                "input_artifact_ids": artifact["input_artifact_ids"],
                "provenance": provenance,
                "fixture": domain,
            }
        )

    ids = {artifact["artifact_id"] for artifact in built}
    if len(ids) != len(built):
        raise FixtureError("manifest contains duplicate artifact identities")
    for artifact in built:
        domain = artifact["fixture"]
        if domain is not None:
            source_id = domain["source_manifest_id"]
            source = next(
                (
                    candidate
                    for candidate in built
                    if candidate["artifact_id"] == source_id
                ),
                None,
            )
            if source is None or source["artifact_kind"] != "source_manifest":
                raise FixtureError(
                    "fixture source_manifest_id must refer to a source_manifest in the same manifest"
                )
    return sorted(built, key=lambda artifact: artifact["artifact_id"])


def write_minnesota_fixture(artifacts: list[dict[str, Any]], db_path: Path) -> Path:
    """Insert valid fixture metadata without replacing the shared DuckDB file."""
    con = duckdb.connect(str(db_path))
    try:
        ensure_minnesota_schema(con)
        con.execute("BEGIN")
        try:
            for artifact in artifacts:
                con.execute(
                    """INSERT INTO mn_artifact_manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        artifact["artifact_id"],
                        artifact["artifact_kind"],
                        SCHEMA_VERSION,
                        artifact["geography_id"],
                        artifact["availability"],
                        artifact["model_mode"],
                        artifact["identity_json"],
                        artifact["created_at"],
                        _canonical_json(artifact["assumptions"]),
                        _canonical_json(artifact["limitations"]),
                        _canonical_json(artifact["input_artifact_ids"]),
                    ],
                )
            for artifact in artifacts:
                for ordinal, provenance in enumerate(artifact["provenance"]):
                    con.execute(
                        "INSERT INTO mn_artifact_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            artifact["artifact_id"],
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
            for artifact in artifacts:
                if artifact["fixture"] is not None:
                    domain = artifact["fixture"]
                    con.execute(
                        "INSERT INTO mn_fixture_artifacts VALUES (?, ?, ?, ?)",
                        [
                            artifact["artifact_id"],
                            domain["source_manifest_id"],
                            domain["fixture_label"],
                            domain["fallback_label"],
                        ],
                    )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
    return db_path


def main(
    manifest_path: Path = MANIFEST,
    db_path: Path = Path("data/duck/grid.duckdb"),
) -> int:
    artifacts = build_artifacts(load_manifest(manifest_path))
    write_minnesota_fixture(artifacts, db_path)
    print(f"wrote {len(artifacts)} Minnesota artifact(s) to {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

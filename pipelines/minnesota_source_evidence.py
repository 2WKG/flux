"""Persist source-qualified Minnesota county geography without claiming a model.

Artifact kinds and geography identifiers follow docs/specs/10-duckdb-contract.md:
statewide source manifests use ``geography_id="mn"``; the derived county
collection is an ``artifact_kind="geography"`` artifact with the source-qualified
region key ``mn:counties:2024``.

This writer keeps raw aggregate-capacity and balancing-authority files as source
evidence.  It stores only the deterministic county-boundary collection in the
existing Minnesota artifact namespace; it never turns those inputs into a
fixture, topology, allocation, or validated model result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import geopandas as gpd

from pipelines.fixtures.builder import FixtureError, artifact_id_for
from pipelines.minnesota_aggregate import UPSTREAM_SHA_KEY
from pipelines.minnesota_schema import SCHEMA_VERSION, ensure_minnesota_schema


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("retrieved_at must have an explicit UTC offset")
    return parsed.astimezone(UTC).replace(tzinfo=None)


def build_source_evidence(
    *, counties_zip: Path, aggregate_manifest: Path
) -> list[dict[str, Any]]:
    """Build source manifests and one derived, full-Minnesota county geometry."""
    manifest = json.loads(aggregate_manifest.read_text(encoding="utf-8"))
    if manifest.get("format") != "flux-minnesota-aggregate-v1":
        raise ValueError("aggregate manifest has an incompatible format")
    sources = {source["id"]: source for source in manifest["sources"]}
    needed = {"tiger_counties_2024", "eia860_2024", "eia930_balance_2024_h1"}
    if missing := needed - sources.keys():
        raise ValueError(f"aggregate manifest misses sources: {sorted(missing)!r}")
    for source in sources.values():
        if not _is_sha256(source.get(UPSTREAM_SHA_KEY)):
            raise ValueError(
                f"aggregate manifest source {source['id']!r} lacks a lowercase "
                f"SHA-256 under {UPSTREAM_SHA_KEY!r}"
            )
    tiger = sources["tiger_counties_2024"]
    if tiger[UPSTREAM_SHA_KEY] != _sha256(counties_zip):
        raise ValueError("county source checksum does not match aggregate manifest")
    counties = gpd.read_file(f"zip://{counties_zip}")
    counties = counties.loc[counties["STATEFP"].eq("27")].to_crs("EPSG:4326")
    if len(counties) != 87 or counties["GEOID"].duplicated().any():
        raise ValueError(
            "county source must contain exactly 87 unique Minnesota counties"
        )
    geometry = counties.geometry.union_all().wkb
    geometry_sha = hashlib.sha256(geometry).hexdigest()
    retrieved_at = manifest["retrieved_at"]

    def source_artifact(source: dict[str, Any]) -> dict[str, Any]:
        identity = {
            "artifact_kind": "source_manifest",
            "geography_id": "mn",
            "model_mode": "not_applicable",
            "source_identity": source["id"],
            "source_version": "2024",
            "content_sha256": source[UPSTREAM_SHA_KEY],
        }
        return {
            "artifact_id": artifact_id_for(identity),
            "artifact_kind": "source_manifest",
            "geography_id": "mn",
            "availability": "available",
            "model_mode": "not_applicable",
            "identity": identity,
            "created_at": retrieved_at,
            "assumptions": [],
            "limitations": [
                source.get("limit", "source evidence only; no model claim")
            ],
            "input_artifact_ids": [],
            "provenance": [
                {
                    "source_name": source["id"],
                    "source_ref": source["url"],
                    "source_version": "2024",
                    "retrieved_at": retrieved_at,
                    "license_or_terms": "public publisher data; see source publisher terms",
                    "source_record_id": None,
                    "content_sha256": source[UPSTREAM_SHA_KEY],
                    "is_derived": False,
                }
            ],
        }

    source_records = [source_artifact(sources[name]) for name in sorted(needed)]
    tiger_record = next(
        row
        for row in source_records
        if row["identity"]["source_identity"] == "tiger_counties_2024"
    )
    identity = {
        "artifact_kind": "geography",
        "geography_id": "mn:counties:2024",
        "model_mode": "not_applicable",
        "source_identity": "tiger_counties_2024",
        "source_version": "2024",
        "content_sha256": geometry_sha,
    }
    boundary = {
        "artifact_id": artifact_id_for(identity),
        "artifact_kind": "geography",
        "geography_id": "mn:counties:2024",
        "availability": "available",
        "model_mode": "not_applicable",
        "identity": identity,
        "created_at": retrieved_at,
        "assumptions": [],
        "limitations": [
            "Statewide county geometry only; not electrical topology or an allocation crosswalk."
        ],
        "input_artifact_ids": [tiger_record["artifact_id"]],
        "provenance": [
            {
                "source_name": tiger["id"],
                "source_ref": tiger["url"],
                "source_version": "2024",
                "retrieved_at": retrieved_at,
                "license_or_terms": "public publisher data; see source publisher terms",
                "source_record_id": "STATEFP=27",
                "content_sha256": tiger[UPSTREAM_SHA_KEY],
                "is_derived": True,
            }
        ],
        "geometry_wkb": geometry,
        "derivation_method": "filter STATEFP=27; reproject source geometry to EPSG:4326; union county polygons",
    }
    return sorted([*source_records, boundary], key=lambda row: row["artifact_id"])


def write_source_evidence(records: list[dict[str, Any]], db_path: Path) -> Path:
    """Insert exact records once; reject any conflicting persisted evidence."""
    con = duckdb.connect(str(db_path))
    try:
        ensure_minnesota_schema(con)
        con.execute("BEGIN")
        try:
            for row in records:
                identity_json = _canonical(row["identity"])
                manifest = (
                    row["artifact_kind"],
                    SCHEMA_VERSION,
                    row["geography_id"],
                    row["availability"],
                    row["model_mode"],
                    identity_json,
                    _timestamp(row["created_at"]),
                    _canonical(row["assumptions"]),
                    _canonical(row["limitations"]),
                    _canonical(row["input_artifact_ids"]),
                )
                existing = con.execute(
                    "SELECT artifact_kind, contract_version, geography_id, availability, model_mode, identity_json, created_at, assumptions_json, limitations_json, input_artifact_ids_json FROM mn_artifact_manifests WHERE artifact_id=?",
                    [row["artifact_id"]],
                ).fetchone()
                if existing is None:
                    con.execute(
                        "INSERT INTO mn_artifact_manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [row["artifact_id"], *manifest],
                    )
                    created = True
                elif existing != manifest:
                    raise FixtureError(
                        f"existing Minnesota artifact {row['artifact_id']!r} conflicts with source evidence"
                    )
                else:
                    created = False
                expected_provenance = [
                    (
                        p["source_name"],
                        p["source_ref"],
                        p["source_version"],
                        _timestamp(p["retrieved_at"]),
                        p["license_or_terms"],
                        p["source_record_id"],
                        p["content_sha256"],
                        p["is_derived"],
                    )
                    for p in row["provenance"]
                ]
                current = con.execute(
                    "SELECT source_name, source_ref, source_version, retrieved_at, license_or_terms, source_record_id, content_sha256, is_derived FROM mn_artifact_provenance WHERE artifact_id=? ORDER BY provenance_ordinal",
                    [row["artifact_id"]],
                ).fetchall()
                if not created and current != expected_provenance:
                    raise FixtureError(
                        f"existing Minnesota provenance for {row['artifact_id']!r} conflicts with source evidence"
                    )
                if created:
                    for ordinal, value in enumerate(expected_provenance):
                        con.execute(
                            "INSERT INTO mn_artifact_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            [row["artifact_id"], ordinal, *value],
                        )
                if "geometry_wkb" in row:
                    expected_geo = (
                        row["geometry_wkb"],
                        None,
                        None,
                        "derived",
                        "source",
                    )
                    current_geo = con.execute(
                        "SELECT geometry_wkb, lon, lat, coordinate_status, coordinate_precision FROM mn_geography_artifacts WHERE artifact_id=?",
                        [row["artifact_id"]],
                    ).fetchone()
                    if created:
                        con.execute(
                            "INSERT INTO mn_geography_artifacts VALUES (?, ?, ?, ?, ?, ?)",
                            [row["artifact_id"], *expected_geo],
                        )
                        con.execute(
                            "INSERT INTO mn_artifact_field_provenance VALUES (?, ?, ?, ?)",
                            [
                                row["artifact_id"],
                                "geometry_wkb",
                                0,
                                row["derivation_method"],
                            ],
                        )
                    elif current_geo != expected_geo:
                        raise FixtureError(
                            f"existing Minnesota geography for {row['artifact_id']!r} conflicts with source evidence"
                        )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
    return db_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counties-zip", type=Path, required=True)
    parser.add_argument("--aggregate-manifest", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    write_source_evidence(
        build_source_evidence(
            counties_zip=args.counties_zip, aggregate_manifest=args.aggregate_manifest
        ),
        args.db,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

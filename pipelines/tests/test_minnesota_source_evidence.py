from copy import deepcopy
from pathlib import Path

import duckdb
import pytest
from shapely.geometry import Polygon

from pipelines.fixtures.builder import FixtureError
from pipelines.minnesota_source_evidence import write_source_evidence


def _record() -> dict:
    digest = "a" * 64
    return {
        "artifact_id": "mn:geography:test",
        "artifact_kind": "geography",
        "geography_id": "mn:counties:2024",
        "availability": "available",
        "model_mode": "not_applicable",
        "identity": {
            "artifact_kind": "geography",
            "geography_id": "mn:counties:2024",
            "model_mode": "not_applicable",
            "source_identity": "tiger_counties_2024",
            "source_version": "2024",
            "content_sha256": "b" * 64,
        },
        "created_at": "2026-09-05T00:00:00+00:00",
        "assumptions": [],
        "limitations": ["boundary only"],
        "input_artifact_ids": [],
        "provenance": [
            {
                "source_name": "tiger_counties_2024",
                "source_ref": "https://example.test/tiger",
                "source_version": "2024",
                "retrieved_at": "2026-09-05T00:00:00+00:00",
                "license_or_terms": "public publisher data",
                "source_record_id": "STATEFP=27",
                "content_sha256": digest,
                "is_derived": True,
            }
        ],
        "geometry_wkb": Polygon([(0, 0), (1, 0), (0, 1)]).wkb,
        "derivation_method": "filter; reproject; union",
    }


def test_write_source_evidence_is_idempotent_and_persists_derived_geometry(
    tmp_path: Path,
):
    db = tmp_path / "mn.duckdb"
    record = _record()
    write_source_evidence([record], db)
    write_source_evidence([deepcopy(record)], db)
    with duckdb.connect(str(db), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM mn_artifact_manifests").fetchone() == (
            1,
        )
        assert con.execute(
            "SELECT coordinate_status, coordinate_precision FROM mn_geography_artifacts"
        ).fetchone() == ("derived", "source")
        assert con.execute(
            "SELECT derivation_method FROM mn_artifact_field_provenance"
        ).fetchone() == ("filter; reproject; union",)


def test_write_source_evidence_rejects_conflict_without_replacing_geometry(
    tmp_path: Path,
):
    db = tmp_path / "mn.duckdb"
    record = _record()
    write_source_evidence([record], db)
    changed = deepcopy(record)
    changed["geometry_wkb"] = Polygon([(1, 1), (2, 1), (1, 2)]).wkb
    with pytest.raises(FixtureError, match="geography"):
        write_source_evidence([changed], db)
    with duckdb.connect(str(db), read_only=True) as con:
        assert con.execute(
            "SELECT geometry_wkb FROM mn_geography_artifacts"
        ).fetchone() == (record["geometry_wkb"],)


def test_write_source_evidence_rejects_an_incomplete_existing_artifact(tmp_path: Path):
    db = tmp_path / "mn.duckdb"
    record = _record()
    write_source_evidence([record], db)
    with duckdb.connect(str(db)) as con:
        con.execute("DELETE FROM mn_artifact_field_provenance")
        con.execute("DELETE FROM mn_geography_artifacts")
    with pytest.raises(FixtureError, match="geography"):
        write_source_evidence([record], db)


def _aggregate_manifest(
    tmp_path: Path,
    *,
    counties_zip: Path,
    service_areas_gpkg: Path,
    eia860_zip: Path,
    eia930_csv: Path,
) -> Path:
    from pipelines.minnesota_aggregate import MANIFEST_FILE, build_aggregate_evidence

    output_dir = tmp_path / "aggregate"
    build_aggregate_evidence(
        counties_zip=counties_zip,
        service_areas_gpkg=service_areas_gpkg,
        eia860_zip=eia860_zip,
        eia930_csv=eia930_csv,
        output_dir=output_dir,
        retrieved_at="2026-09-06T02:11:00Z",
    )
    return output_dir / MANIFEST_FILE


@pytest.fixture
def synthetic_aggregate_manifest(
    tmp_path: Path,
    synthetic_tiger_zip: Path,
    synthetic_service_areas_gpkg: Path,
    synthetic_eia860_zip: Path,
    synthetic_eia930_csv: Path,
    patch_eia860_reader,
) -> Path:
    patch_eia860_reader()
    return _aggregate_manifest(
        tmp_path,
        counties_zip=synthetic_tiger_zip,
        service_areas_gpkg=synthetic_service_areas_gpkg,
        eia860_zip=synthetic_eia860_zip,
        eia930_csv=synthetic_eia930_csv,
    )


def test_build_source_evidence_end_to_end_uses_contract_kinds_and_geographies(
    tmp_path: Path, synthetic_tiger_zip: Path, synthetic_aggregate_manifest: Path
):
    from pipelines.minnesota_source_evidence import build_source_evidence

    records = build_source_evidence(
        counties_zip=synthetic_tiger_zip,
        aggregate_manifest=synthetic_aggregate_manifest,
    )
    again = build_source_evidence(
        counties_zip=synthetic_tiger_zip,
        aggregate_manifest=synthetic_aggregate_manifest,
    )

    assert records == again  # deterministic for identical inputs
    assert len(records) == 4
    # docs/specs/10-duckdb-contract.md: kinds are drawn from the contract enum and a
    # statewide artifact is `mn`; the derived county collection is source-qualified.
    assert {row["artifact_kind"] for row in records} == {"source_manifest", "geography"}
    assert {row["geography_id"] for row in records} == {"mn", "mn:counties:2024"}
    for row in records:
        assert row["artifact_id"].startswith(f"mn:{row['artifact_kind']}:")
        assert row["identity"]["artifact_kind"] == row["artifact_kind"]
        assert row["identity"]["geography_id"] == row["geography_id"]
        assert row["model_mode"] == "not_applicable"
        assert row["availability"] == "available"
    boundary = next(row for row in records if row["artifact_kind"] == "geography")
    tiger = next(
        row
        for row in records
        if row["identity"]["source_identity"] == "tiger_counties_2024"
        and row["artifact_kind"] == "source_manifest"
    )
    assert boundary["input_artifact_ids"] == [tiger["artifact_id"]]
    assert boundary["provenance"][0]["is_derived"] is True
    assert (
        boundary["provenance"][0]["content_sha256"]
        == tiger["identity"]["content_sha256"]
    )

    db = tmp_path / "mn.duckdb"
    write_source_evidence(records, db)
    with duckdb.connect(str(db), read_only=True) as con:
        assert con.execute(
            "SELECT count(*) FROM mn_artifact_manifests WHERE artifact_kind IN ('source_manifest','geography')"
        ).fetchone() == (4,)
        assert con.execute(
            "SELECT DISTINCT geography_id FROM mn_artifact_manifests ORDER BY 1"
        ).fetchall() == [("mn",), ("mn:counties:2024",)]
        assert con.execute(
            "SELECT count(*) FROM mn_geography_artifacts"
        ).fetchone() == (1,)


def test_build_source_evidence_rejects_tiger_checksum_mismatch(
    tmp_path: Path, synthetic_tiger_zip: Path, synthetic_aggregate_manifest: Path
):
    import json

    from pipelines.minnesota_aggregate import UPSTREAM_SHA_KEY
    from pipelines.minnesota_source_evidence import build_source_evidence

    manifest = json.loads(synthetic_aggregate_manifest.read_text())
    tiger = next(s for s in manifest["sources"] if s["id"] == "tiger_counties_2024")
    tiger[UPSTREAM_SHA_KEY] = "0" * 64  # well-formed, but not this zip
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="checksum does not match"):
        build_source_evidence(
            counties_zip=synthetic_tiger_zip, aggregate_manifest=tampered
        )


def test_build_source_evidence_rejects_malformed_upstream_digest(
    tmp_path: Path, synthetic_tiger_zip: Path, synthetic_aggregate_manifest: Path
):
    import json

    from pipelines.minnesota_aggregate import UPSTREAM_SHA_KEY
    from pipelines.minnesota_source_evidence import build_source_evidence

    manifest = json.loads(synthetic_aggregate_manifest.read_text())
    eia = next(s for s in manifest["sources"] if s["id"] == "eia860_2024")
    eia[UPSTREAM_SHA_KEY] = "z" * 64
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="lacks a lowercase SHA-256"):
        build_source_evidence(
            counties_zip=synthetic_tiger_zip, aggregate_manifest=tampered
        )


def test_write_source_evidence_rejects_provenance_conflict(tmp_path: Path):
    db = tmp_path / "mn.duckdb"
    record = _record()
    write_source_evidence([record], db)
    changed = deepcopy(record)
    changed["provenance"][0]["license_or_terms"] = "different terms"

    with pytest.raises(FixtureError, match="provenance"):
        write_source_evidence([changed], db)
    with duckdb.connect(str(db), read_only=True) as con:
        assert con.execute(
            "SELECT license_or_terms FROM mn_artifact_provenance"
        ).fetchall() == [("public publisher data",)]

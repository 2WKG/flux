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
        "artifact_id": "mn:county_boundary:test",
        "artifact_kind": "county_boundary",
        "geography_id": "mn:counties:2024",
        "availability": "available",
        "model_mode": "not_applicable",
        "identity": {
            "artifact_kind": "county_boundary",
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

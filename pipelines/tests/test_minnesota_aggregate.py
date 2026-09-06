"""Checks for the committed, aggregate-only Minnesota source evidence."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from pipelines import minnesota_aggregate
from pipelines.minnesota_aggregate import (
    CAPACITY_FILE,
    CONTEXT_FILE,
    FORMAT,
    MANIFEST_FILE,
    MISO_LABEL,
    UNASSIGNED_FILE,
    UPSTREAM_SHA_KEY,
    _miso_context,
    build_aggregate_evidence,
    load_evidence_files,
    write_evidence_files,
)
from pipelines.tests.minnesota_synthetic import (
    MN_COUNTY_FIPS,
    write_synthetic_tiger_zip,
)

INPUTS = Path(__file__).parents[1] / "fixtures" / "inputs"
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
COMMITTED_FILES = (CAPACITY_FILE, UNASSIGNED_FILE, CONTEXT_FILE)


def _sha256(path: Path) -> str:
    """Exact bytes: only for the upstream binary releases the manifest records."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(path: Path) -> str:
    """Canonical LF content, matching how the builder digests committed CSVs.

    Hashing raw bytes here would assert a digest that only reproduces on the
    platform whose checkout wrote it: CRLF on Windows, LF on the Linux runner.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _committed_manifest() -> dict:
    return json.loads((INPUTS / MANIFEST_FILE).read_text(encoding="utf-8"))


def test_committed_aggregate_manifest_pins_sources_and_refuses_allocation():
    manifest = _committed_manifest()

    assert manifest["format"] == FORMAT
    assert manifest["model_mode"] == "aggregate"
    assert manifest["allocation_status"] == "unavailable"
    assert manifest["upstream_checksum_status"].startswith(UPSTREAM_SHA_KEY)
    sources = {source["id"]: source for source in manifest["sources"]}
    assert sources["tiger_counties_2024"]["rows"] == 87
    assert sources["mngeo_service_areas_2026"]["rows"] == 181
    assert sources["eia930_balance_2024_h1"]["label"] == MISO_LABEL
    for source in sources.values():
        # The upstream digests are recorded claims, not something verifiable here;
        # the key says so and no source may still carry a bare `sha256`.
        assert "sha256" not in source
        assert SHA256_HEX.fullmatch(source[UPSTREAM_SHA_KEY]), source["id"]


def test_committed_manifest_file_digests_match_committed_evidence_bytes():
    manifest = _committed_manifest()
    pinned: dict[str, str] = {}
    for source in manifest["sources"]:
        for name, digest in source.get("file_sha256", {}).items():
            assert name not in pinned, f"{name} pinned twice"
            pinned[name] = digest

    assert set(pinned) == set(COMMITTED_FILES)
    for name, digest in pinned.items():
        assert SHA256_HEX.fullmatch(digest), name
        assert digest == _text_sha256(INPUTS / name), name


def test_committed_evidence_is_a_fixed_point_of_the_builder_writer(tmp_path: Path):
    """Reload the committed CSVs and write them again through the builder.

    Byte identity means the committed evidence carries exactly the builder's
    number formats; a drift in either the fixture or `write_evidence_files`
    breaks it.
    """
    capacity, unassigned, miso = load_evidence_files(INPUTS)
    written = write_evidence_files(
        capacity=capacity,
        unassigned_capacity=unassigned,
        miso=miso,
        output_dir=tmp_path,
    )

    assert set(written) == set(COMMITTED_FILES)
    for name, path in written.items():
        assert path.read_bytes() == (INPUTS / name).read_bytes(), name
    # The capacity file is written with %.3f, so no float noise may survive.
    for line in (INPUTS / CAPACITY_FILE).read_text().splitlines()[1:]:
        assert re.fullmatch(r"\d{5},\d+,\d+\.\d{3}", line), line


def test_compact_evidence_preserves_capacity_units_and_ba_identity():
    capacity = pd.read_csv(INPUTS / CAPACITY_FILE, dtype={"county_fips": str})
    unassigned = pd.read_csv(INPUTS / UNASSIGNED_FILE)
    manifest = _committed_manifest()
    context = pd.read_csv(INPUTS / CONTEXT_FILE)

    assert set(capacity) == {"county_fips", "plant_count", "summer_capacity_mw"}
    assert (capacity["summer_capacity_mw"] >= 0).all()
    assert (capacity["summer_capacity_mw"] > 0).any()
    assert set(unassigned) == {
        "plant_code",
        "plant_name",
        "Latitude",
        "Longitude",
        "summer_capacity_mw",
        "geography_status",
    }
    assert unassigned.loc[0, "plant_name"] == "Huneke I CSG"
    assert unassigned.loc[0, "geography_status"] == "unassigned"
    source = next(item for item in manifest["sources"] if item["id"] == "eia860_2024")
    assert capacity["plant_count"].sum() == source["assigned_plant_count"] == 836
    assert unassigned.shape[0] == source["unassigned_plant_count"] == 1
    assert source["assigned_summer_capacity_mw"] == round(
        float(capacity["summer_capacity_mw"].sum()), 3
    )
    assert source["unassigned_summer_capacity_mw"] == round(
        float(unassigned["summer_capacity_mw"].sum()), 3
    )
    assert source["assigned_summer_capacity_mw"] + source[
        "unassigned_summer_capacity_mw"
    ] == pytest.approx(18212.53)
    assert source["geography_limit"].startswith("Plants without exactly one")
    assert len(context) == 4368
    assert context["UTC Time at End of Hour"].is_unique
    assert context["Demand (MW)"].notna().all()


def test_committed_county_coverage_is_explicit_about_absent_counties():
    """73 counties with plants + 14 without = all 87; absence is documented, not zero."""
    capacity = pd.read_csv(INPUTS / CAPACITY_FILE, dtype={"county_fips": str})
    source = next(
        item for item in _committed_manifest()["sources"] if item["id"] == "eia860_2024"
    )
    present = set(capacity["county_fips"])
    absent = source["counties_without_assigned_plants"]

    assert source["county_capacity_rows"] == len(capacity) == 73
    assert absent == sorted(absent) and len(absent) == 14
    assert present.isdisjoint(absent)
    assert present | set(absent) == set(MN_COUNTY_FIPS)
    assert "not a zero-capacity claim" in source["county_coverage_note"]
    assert (capacity["plant_count"] > 0).all()


def test_miso_context_rejects_duplicate_or_missing_utc_rows(tmp_path):
    frame = pd.DataFrame(
        {
            "Balancing Authority": ["MISO", "MISO"],
            "UTC Time at End of Hour": ["2024-01-01T01:00:00Z"] * 2,
            "Demand (MW)": [1.0, 1.0],
            "Demand (MW) (Adjusted)": [1.0, 1.0],
            "Net Generation (MW)": [1.0, 1.0],
            "Total Interchange (MW)": [0.0, 0.0],
        }
    )
    path = tmp_path / "bad.csv"
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="repeat a UTC hour"):
        _miso_context(path)


def test_capacity_keeps_unmatched_and_ambiguous_plants_out_of_counties(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, synthetic_eia860_zip: Path
):
    plants = pd.DataFrame(
        {
            "Plant Code": [1, 2, 3],
            "Plant Name": ["Assigned", "Unmatched", "Ambiguous"],
            "State": ["MN", "MN", "MN"],
            "Latitude": [0.25, 3.0, 0.75],
            "Longitude": [0.25, 3.0, 0.75],
        }
    )
    generators = pd.DataFrame(
        {
            "Plant Code": [1, 2, 3],
            "State": ["MN", "MN", "MN"],
            "Summer Capacity (MW)": [10.0, 20.0, 30.0],
        }
    )
    frames = iter([plants, generators])
    monkeypatch.setattr(
        minnesota_aggregate.pd, "read_excel", lambda *args, **kwargs: next(frames)
    )
    counties = gpd.GeoDataFrame(
        {"GEOID": ["001", "003"]},
        geometry=[
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)]),
        ],
        crs="EPSG:4326",
    )

    assigned, unassigned = minnesota_aggregate._eia860_capacity(
        synthetic_eia860_zip, counties
    )

    assert assigned.to_dict("records") == [
        {"county_fips": "001", "plant_count": 1, "summer_capacity_mw": 10.0}
    ]
    assert unassigned[["plant_name", "summer_capacity_mw", "geography_status"]].to_dict(
        "records"
    ) == [
        {
            "plant_name": "Unmatched",
            "summer_capacity_mw": 20.0,
            "geography_status": "unassigned",
        },
        {
            "plant_name": "Ambiguous",
            "summer_capacity_mw": 30.0,
            "geography_status": "ambiguous",
        },
    ]


def test_build_aggregate_evidence_end_to_end_on_synthetic_sources(
    tmp_path: Path,
    synthetic_tiger_zip: Path,
    synthetic_service_areas_gpkg: Path,
    synthetic_eia860_zip: Path,
    synthetic_eia930_csv: Path,
    patch_eia860_reader,
):
    patch_eia860_reader()
    output_dir = tmp_path / "out"

    manifest = build_aggregate_evidence(
        counties_zip=synthetic_tiger_zip,
        service_areas_gpkg=synthetic_service_areas_gpkg,
        eia860_zip=synthetic_eia860_zip,
        eia930_csv=synthetic_eia930_csv,
        output_dir=output_dir,
        retrieved_at="2026-09-06T02:11:00Z",
    )

    # The RETURNED manifest, not a committed file, refuses allocation.
    assert manifest["allocation_status"] == "unavailable"
    assert manifest["model_mode"] == "aggregate"
    assert "allocat" in manifest["allocation_limit"]
    assert manifest["upstream_checksum_status"].startswith(UPSTREAM_SHA_KEY)
    assert json.loads((output_dir / MANIFEST_FILE).read_text()) == manifest

    sources = {source["id"]: source for source in manifest["sources"]}
    for name, source in sources.items():
        assert "sha256" not in source, name
        assert SHA256_HEX.fullmatch(source[UPSTREAM_SHA_KEY]), name
    assert sources["tiger_counties_2024"][UPSTREAM_SHA_KEY] == _sha256(
        synthetic_tiger_zip
    )
    assert sources["tiger_counties_2024"]["rows"] == 87  # Iowa row filtered out
    assert sources["mngeo_service_areas_2026"]["rows"] == 2
    assert sources["eia930_balance_2024_h1"]["rows"] == 3  # ERCO row filtered out

    eia860 = sources["eia860_2024"]
    assert eia860["county_capacity_rows"] == 2
    assert eia860["assigned_plant_count"] == 2
    assert eia860["assigned_summer_capacity_mw"] == 847.8  # rounded, no float noise
    assert eia860["unassigned_plant_count"] == 1
    assert eia860["unassigned_summer_capacity_mw"] == 1.0
    assert len(eia860["counties_without_assigned_plants"]) == 85
    assert set(eia860["counties_without_assigned_plants"]) | {"27001", "27003"} == set(
        MN_COUNTY_FIPS
    )

    # Every committed-style file is pinned by the digest of the bytes just written.
    pinned = {
        **eia860["file_sha256"],
        **sources["eia930_balance_2024_h1"]["file_sha256"],
    }
    assert set(pinned) == set(COMMITTED_FILES)
    for name, digest in pinned.items():
        assert digest == _text_sha256(output_dir / name), name
    capacity_lines = (output_dir / CAPACITY_FILE).read_text().splitlines()
    assert capacity_lines == [
        "county_fips,plant_count,summer_capacity_mw",
        "27001,1,0.300",
        "27003,1,847.500",
    ]


def test_build_aggregate_evidence_is_byte_deterministic(
    tmp_path: Path,
    synthetic_tiger_zip: Path,
    synthetic_service_areas_gpkg: Path,
    synthetic_eia860_zip: Path,
    synthetic_eia930_csv: Path,
    patch_eia860_reader,
):
    outputs = []
    for run in ("first", "second"):
        patch_eia860_reader()
        output_dir = tmp_path / run
        build_aggregate_evidence(
            counties_zip=synthetic_tiger_zip,
            service_areas_gpkg=synthetic_service_areas_gpkg,
            eia860_zip=synthetic_eia860_zip,
            eia930_csv=synthetic_eia930_csv,
            output_dir=output_dir,
            retrieved_at="2026-09-06T02:11:00Z",
        )
        outputs.append(
            {
                path.name: path.read_bytes()
                for path in output_dir.iterdir()
                if path.is_file()
            }
        )

    assert set(outputs[0]) == {*COMMITTED_FILES, MANIFEST_FILE}
    assert outputs[0] == outputs[1]


def test_build_aggregate_evidence_raises_when_a_plant_is_not_accounted_for(
    tmp_path: Path,
    synthetic_tiger_zip: Path,
    synthetic_service_areas_gpkg: Path,
    synthetic_eia860_zip: Path,
    synthetic_eia930_csv: Path,
    patch_eia860_reader,
):
    """A repeated plant row cannot be silently collapsed into a county total."""
    patch_eia860_reader(duplicate_plant_code=True)

    with pytest.raises(ValueError, match="account for every Minnesota plant"):
        build_aggregate_evidence(
            counties_zip=synthetic_tiger_zip,
            service_areas_gpkg=synthetic_service_areas_gpkg,
            eia860_zip=synthetic_eia860_zip,
            eia930_csv=synthetic_eia930_csv,
            output_dir=tmp_path / "out",
            retrieved_at="2026-09-06T02:11:00Z",
        )
    assert not (tmp_path / "out" / MANIFEST_FILE).exists()


def test_build_aggregate_evidence_rejects_wrong_county_count(
    tmp_path: Path,
    synthetic_service_areas_gpkg: Path,
    synthetic_eia860_zip: Path,
    synthetic_eia930_csv: Path,
):
    short_zip = write_synthetic_tiger_zip(
        tmp_path / "short.zip", county_fips=MN_COUNTY_FIPS[:-1]
    )

    with pytest.raises(ValueError, match="exactly 87"):
        build_aggregate_evidence(
            counties_zip=short_zip,
            service_areas_gpkg=synthetic_service_areas_gpkg,
            eia860_zip=synthetic_eia860_zip,
            eia930_csv=synthetic_eia930_csv,
            output_dir=tmp_path / "out",
            retrieved_at="2026-09-06T02:11:00Z",
        )

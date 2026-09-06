"""Checks for the committed, aggregate-only Minnesota source evidence."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from pipelines import minnesota_aggregate
from pipelines.minnesota_aggregate import FORMAT, MISO_LABEL, _miso_context

INPUTS = Path(__file__).parents[1] / "fixtures" / "inputs"


def test_committed_aggregate_manifest_pins_sources_and_refuses_allocation():
    manifest = json.loads(
        (INPUTS / "minnesota_aggregate_manifest_v1.json").read_text(encoding="utf-8")
    )

    assert manifest["format"] == FORMAT
    assert manifest["model_mode"] == "aggregate"
    assert manifest["allocation_status"] == "unavailable"
    sources = {source["id"]: source for source in manifest["sources"]}
    assert sources["tiger_counties_2024"]["rows"] == 87
    assert sources["mngeo_service_areas_2026"]["rows"] == 181
    assert sources["eia930_balance_2024_h1"]["label"] == MISO_LABEL
    assert all(len(source["sha256"]) == 64 for source in sources.values())


def test_compact_evidence_preserves_capacity_units_and_ba_identity():
    capacity = pd.read_csv(INPUTS / "mn_county_plant_capacity_2024.csv")
    unassigned = pd.read_csv(INPUTS / "mn_unassigned_plant_capacity_2024.csv")
    manifest = json.loads(
        (INPUTS / "minnesota_aggregate_manifest_v1.json").read_text(encoding="utf-8")
    )
    context = pd.read_csv(INPUTS / "miso_ba_context_2024_h1.csv")

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
    assert capacity["summer_capacity_mw"].sum() + unassigned[
        "summer_capacity_mw"
    ].sum() == pytest.approx(18212.53)
    assert source["geography_limit"].startswith("Plants without exactly one")
    assert len(context) == 4368
    assert context["UTC Time at End of Hour"].is_unique
    assert context["Demand (MW)"].notna().all()


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    archive = tmp_path / "eia.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("2___Plant_Y2024.xlsx", b"")
        zipped.writestr("3_1_Generator_Y2024.xlsx", b"")
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

    assigned, unassigned = minnesota_aggregate._eia860_capacity(archive, counties)

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

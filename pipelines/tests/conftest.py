"""Shared fixtures that stage synthetic Minnesota sources in ``tmp_path``."""

from __future__ import annotations

import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from pipelines.tests.minnesota_synthetic import (
    GENERATOR_MEMBER,
    MN_COUNTY_FIPS,
    PLANT_MEMBER,
    synthetic_eia860_frames,
    write_synthetic_tiger_zip,
)


@pytest.fixture
def synthetic_tiger_zip(tmp_path: Path) -> Path:
    return write_synthetic_tiger_zip(
        tmp_path / "tl_2024_us_county.zip", county_fips=MN_COUNTY_FIPS
    )


@pytest.fixture
def synthetic_service_areas_gpkg(tmp_path: Path) -> Path:
    path = tmp_path / "util_eusa.gpkg"
    gpd.GeoDataFrame(
        {"UTILITY": ["A", "B"]},
        geometry=[box(0, 0, 3, 3), box(3, 3, 6, 6)],
        crs="EPSG:26915",
    ).to_file(path, driver="GPKG")
    return path


@pytest.fixture
def synthetic_eia930_csv(tmp_path: Path) -> Path:
    hours = pd.date_range("2024-01-01T06:00:00Z", periods=4, freq="h")
    frame = pd.DataFrame(
        {
            "Balancing Authority": ["MISO", "MISO", "MISO", "ERCO"],
            "UTC Time at End of Hour": [h.isoformat() for h in hours],
            "Demand (MW)": [65974.0, 64702.0, 63853.0, 1.0],
            "Demand (MW) (Adjusted)": [65974.0, 64702.0, 63853.0, 1.0],
            "Net Generation (MW)": [63332.0, 61900.0, 61000.0, 1.0],
            "Total Interchange (MW)": [-4062.0, -3993.0, -3800.0, 0.0],
        }
    )
    path = tmp_path / "EIA930_BALANCE_2024_Jan_Jun.csv"
    frame.to_csv(path, index=False)
    return path


@pytest.fixture
def synthetic_eia860_zip(tmp_path: Path) -> Path:
    """A zip with the two member names the builder opens; content is stubbed."""
    path = tmp_path / "eia8602024.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(PLANT_MEMBER, b"")
        archive.writestr(GENERATOR_MEMBER, b"")
    return path


@pytest.fixture
def patch_eia860_reader(monkeypatch: pytest.MonkeyPatch):
    """Replace ``pd.read_excel`` so the stubbed zip members yield frames."""
    from pipelines import minnesota_aggregate

    def install(*, duplicate_plant_code: bool = False) -> None:
        frames = iter(
            synthetic_eia860_frames(duplicate_plant_code=duplicate_plant_code)
        )
        monkeypatch.setattr(
            minnesota_aggregate.pd, "read_excel", lambda *args, **kwargs: next(frames)
        )

    return install

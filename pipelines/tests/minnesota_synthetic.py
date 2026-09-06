"""Synthetic Minnesota source files for end-to-end builder tests.

Nothing here is real TIGER, MnGeo, EIA-860, or EIA-930 data.  The files only
have the column names, member names, and shapes the builders read, so the
builders can be driven end to end in ``tmp_path`` without network access.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

MN_COUNTY_FIPS = [f"27{n:03d}" for n in range(1, 174, 2)]
assert len(MN_COUNTY_FIPS) == 87

PLANT_MEMBER = "2___Plant_Y2024.xlsx"
GENERATOR_MEMBER = "3_1_Generator_Y2024.xlsx"


def write_synthetic_tiger_zip(path: Path, *, county_fips: list[str]) -> Path:
    """Write a zipped shapefile of unit squares, one per county, plus one Iowa row."""
    rows = []
    for index, fips in enumerate(county_fips):
        col, row = divmod(index, 10)
        rows.append(
            {
                "STATEFP": "27",
                "GEOID": fips,
                "NAME": f"County {fips}",
                "geometry": box(col, row, col + 1, row + 1),
            }
        )
    rows.append(
        {
            "STATEFP": "19",
            "GEOID": "19001",
            "NAME": "Iowa",
            "geometry": box(50, 50, 51, 51),
        }
    )
    frame = gpd.GeoDataFrame(rows, crs="EPSG:4269")
    shp_dir = path.parent / f"{path.stem}_shp"
    shp_dir.mkdir(exist_ok=True)
    frame.to_file(shp_dir / "tl_2024_us_county.shp")
    with zipfile.ZipFile(path, "w") as archive:
        for member in sorted(shp_dir.iterdir()):
            archive.write(member, member.name)
    return path


def synthetic_eia860_frames(
    *, duplicate_plant_code: bool = False
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Plants: one inside county 27001, one inside 27003, one outside every square."""
    plants = pd.DataFrame(
        {
            "Plant Code": [1, 2, 3] + ([1] if duplicate_plant_code else []),
            "Plant Name": ["Inside 27001", "Inside 27003", "Offshore"]
            + (["Inside 27001 again"] if duplicate_plant_code else []),
            "State": ["MN"] * (4 if duplicate_plant_code else 3),
            "Latitude": [0.5, 1.5, 40.0] + ([0.5] if duplicate_plant_code else []),
            "Longitude": [0.5, 0.5, 40.0] + ([0.5] if duplicate_plant_code else []),
        }
    )
    generators = pd.DataFrame(
        {
            "Plant Code": [1, 1, 2, 3, 9],
            "State": ["MN", "MN", "MN", "MN", "IA"],
            "Summer Capacity (MW)": [0.1, 0.2, 847.5000000000001, 1.0, 5.0],
        }
    )
    return plants, generators

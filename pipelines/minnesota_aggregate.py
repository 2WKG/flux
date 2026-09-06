"""Build compact, source-backed Minnesota aggregate evidence.

The output deliberately contains county geography and plant-capacity context
beside a *MISO balancing-authority* time series.  It has no electrical network
and never allocates BA demand to Minnesota counties or service areas.

Two kinds of digest appear in the manifest and they are not interchangeable:

* ``upstream_sha256_unverified_offline`` is the SHA-256 of the upstream release
  file as downloaded by the author at ``retrieved_at``.  Nothing in this
  repository can recompute it because the upstream files are not committed; it
  is a recorded claim, not something a test verifies.
* ``file_sha256`` maps each committed evidence file written by this builder to
  the SHA-256 of its canonical LF content.  Tests recompute and assert these, so
  the digest must not depend on whether the checkout materialised CRLF or LF.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

FORMAT = "flux-minnesota-aggregate-v1"
MISO_LABEL = "MISO balancing authority (not Minnesota demand)"
UPSTREAM_SHA_KEY = "upstream_sha256_unverified_offline"
UPSTREAM_CHECKSUM_STATUS = (
    "upstream_sha256_unverified_offline values are digests of the author's "
    "downloads at retrieved_at; the upstream files are not committed, so they "
    "cannot be re-verified from this repository. file_sha256 values pin the "
    "committed evidence files and are verified by tests."
)
COUNTY_COVERAGE_NOTE = (
    "county_capacity_rows counts counties with at least one assigned operable "
    "plant. A county absent from the county capacity file appears in "
    "counties_without_assigned_plants; absence is not a zero-capacity claim and "
    "not an unavailable value, it means this source assigned no plant there."
)
CAPACITY_FILE = "mn_county_plant_capacity_2024.csv"
UNASSIGNED_FILE = "mn_unassigned_plant_capacity_2024.csv"
CONTEXT_FILE = "miso_ba_context_2024_h1.csv"
MANIFEST_FILE = "minnesota_aggregate_manifest_v1.json"
CAPACITY_FLOAT_FORMAT = "%.3f"
UNASSIGNED_FLOAT_FORMAT = "%.6f"
CAPACITY_DECIMALS = 3
CONTEXT_TIME_COLUMN = "UTC Time at End of Hour"
CONTEXT_VALUE_COLUMNS = [
    "Demand (MW)",
    "Demand (MW) (Adjusted)",
    "Net Generation (MW)",
    "Total Interchange (MW)",
]


def _sha256(path: Path) -> str:
    """Hash an upstream artifact by its exact bytes. Use only for binary releases."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text_sha256(path: Path) -> str:
    """Hash a Git-tracked text artifact by its canonical LF content.

    The evidence CSVs this builder writes are tracked text, so a Windows checkout
    materialises them with CRLF and a Linux one with LF. Hashing raw bytes would
    pin a digest that only reproduces on the platform that generated it; the LF
    form is the canonical index content and matches on both.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _eia860_capacity(
    path: Path, counties: gpd.GeoDataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return assigned county totals and plants with no unambiguous county.

    A spatial join is evidence, not a license to invent a nearest county.  Every
    Minnesota plant is retained: zero matching polygons is ``unassigned`` and
    more than one is ``ambiguous``.  Only one exact match contributes to a
    county aggregate.
    """
    with zipfile.ZipFile(path) as archive:
        with archive.open("2___Plant_Y2024.xlsx") as stream:
            plants = pd.read_excel(stream, header=1)
        with archive.open("3_1_Generator_Y2024.xlsx") as stream:
            generators = pd.read_excel(stream, sheet_name="Operable", header=1)
    plants = plants.loc[plants["State"].eq("MN")].copy()
    generators = generators.loc[generators["State"].eq("MN")].copy()
    plants["Plant Code"] = pd.to_numeric(plants["Plant Code"], errors="coerce")
    generators["Plant Code"] = pd.to_numeric(generators["Plant Code"], errors="coerce")
    capacity = (
        generators.groupby("Plant Code", dropna=True)["Summer Capacity (MW)"]
        .sum(min_count=1)
        .rename("summer_capacity_mw")
    )
    plants = plants.join(capacity, on="Plant Code")
    plant_capacity = (
        plants.loc[:, ["Plant Code", "Plant Name", "Latitude", "Longitude"]]
        .join(capacity, on="Plant Code")
        .rename(columns={"Plant Code": "plant_code", "Plant Name": "plant_name"})
    )
    points = gpd.GeoDataFrame(
        plant_capacity,
        geometry=gpd.points_from_xy(
            plant_capacity["Longitude"], plant_capacity["Latitude"]
        ),
        crs="EPSG:4326",
    )
    county_shapes = counties[["GEOID", "geometry"]].to_crs("EPSG:4326")
    joined = gpd.sjoin(points, county_shapes, how="left", predicate="within")
    match_counts = joined.groupby("plant_code", dropna=False)["GEOID"].count()
    joined["match_count"] = joined["plant_code"].map(match_counts)
    assigned = joined.loc[joined["match_count"].eq(1)].copy()
    county_capacity = (
        assigned.groupby("GEOID", dropna=True)
        .agg(
            plant_count=("plant_code", "nunique"),
            summer_capacity_mw=("summer_capacity_mw", "sum"),
        )
        .reset_index()
        .rename(columns={"GEOID": "county_fips"})
        .sort_values("county_fips", kind="stable")
    )
    excluded = joined.loc[joined["match_count"].ne(1)].drop_duplicates("plant_code")
    excluded = excluded.loc[
        :,
        [
            "plant_code",
            "plant_name",
            "Latitude",
            "Longitude",
            "summer_capacity_mw",
            "match_count",
        ],
    ].copy()
    excluded["geography_status"] = excluded["match_count"].map(
        lambda count: "unassigned" if count == 0 else "ambiguous"
    )
    excluded = excluded.drop(columns="match_count").sort_values(
        "plant_code", kind="stable"
    )
    if assigned["plant_code"].nunique() + len(excluded) != len(plants):
        raise ValueError("county assignment must account for every Minnesota plant")
    return county_capacity, excluded


def _miso_context(path: Path) -> pd.DataFrame:
    source = pd.read_csv(path)
    required = {"Balancing Authority", CONTEXT_TIME_COLUMN, *CONTEXT_VALUE_COLUMNS}
    missing = required - set(source.columns)
    if missing:
        raise ValueError(f"EIA-930 source is missing columns: {sorted(missing)!r}")
    result = (
        source.loc[source["Balancing Authority"].eq("MISO")]
        .loc[:, [CONTEXT_TIME_COLUMN, *CONTEXT_VALUE_COLUMNS]]
        .copy()
    )
    result[CONTEXT_TIME_COLUMN] = pd.to_datetime(
        result[CONTEXT_TIME_COLUMN], utc=True, errors="coerce"
    )
    if result.empty or result[CONTEXT_TIME_COLUMN].isna().any():
        raise ValueError("EIA-930 MISO rows require parseable UTC timestamps")
    if result[CONTEXT_TIME_COLUMN].duplicated().any():
        raise ValueError("EIA-930 MISO rows repeat a UTC hour")
    return result.sort_values(CONTEXT_TIME_COLUMN, kind="stable")


def write_evidence_files(
    *,
    capacity: pd.DataFrame,
    unassigned_capacity: pd.DataFrame,
    miso: pd.DataFrame,
    output_dir: Path,
) -> dict[str, Path]:
    """Write the three evidence CSVs with the builder's fixed number formats.

    This is the only place the committed evidence bytes are produced, so a
    test can reload the committed files, write them again through this
    function, and require byte identity.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        CAPACITY_FILE: output_dir / CAPACITY_FILE,
        UNASSIGNED_FILE: output_dir / UNASSIGNED_FILE,
        CONTEXT_FILE: output_dir / CONTEXT_FILE,
    }
    capacity.to_csv(
        paths[CAPACITY_FILE], index=False, float_format=CAPACITY_FLOAT_FORMAT
    )
    unassigned_capacity.to_csv(
        paths[UNASSIGNED_FILE], index=False, float_format=UNASSIGNED_FLOAT_FORMAT
    )
    miso.to_csv(paths[CONTEXT_FILE], index=False)
    return paths


def load_evidence_files(
    input_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Reload committed evidence files with the dtypes the builder writes."""
    capacity = pd.read_csv(
        input_dir / CAPACITY_FILE,
        dtype={"county_fips": str, "plant_count": "int64", "summer_capacity_mw": float},
    )
    unassigned_capacity = pd.read_csv(
        input_dir / UNASSIGNED_FILE,
        dtype={
            "plant_code": "int64",
            "plant_name": str,
            "Latitude": float,
            "Longitude": float,
            "summer_capacity_mw": float,
            "geography_status": str,
        },
    )
    miso = pd.read_csv(input_dir / CONTEXT_FILE)
    miso[CONTEXT_TIME_COLUMN] = pd.to_datetime(miso[CONTEXT_TIME_COLUMN], utc=True)
    return capacity, unassigned_capacity, miso


def build_aggregate_evidence(
    *,
    counties_zip: Path,
    service_areas_gpkg: Path,
    eia860_zip: Path,
    eia930_csv: Path,
    output_dir: Path,
    retrieved_at: str,
) -> dict[str, object]:
    """Write compact evidence files and return their deterministic manifest."""
    output_dir.mkdir(parents=True, exist_ok=True)
    counties = gpd.read_file(f"zip://{counties_zip}")
    counties = counties.loc[counties["STATEFP"].eq("27")].copy()
    if len(counties) != 87 or counties["GEOID"].duplicated().any():
        raise ValueError(
            "TIGER source must yield exactly 87 distinct Minnesota counties"
        )
    service_areas = gpd.read_file(service_areas_gpkg)
    if service_areas.empty or service_areas.crs is None:
        raise ValueError(
            "Minnesota service-area source requires nonempty geometry and CRS"
        )
    capacity, unassigned_capacity = _eia860_capacity(eia860_zip, counties)
    miso = _miso_context(eia930_csv)

    paths = write_evidence_files(
        capacity=capacity,
        unassigned_capacity=unassigned_capacity,
        miso=miso,
        output_dir=output_dir,
    )
    counties_without_plants = sorted(
        set(counties["GEOID"].astype(str)) - set(capacity["county_fips"].astype(str))
    )
    manifest = {
        "format": FORMAT,
        "retrieved_at": retrieved_at,
        "model_mode": "aggregate",
        "allocation_status": "unavailable",
        "allocation_limit": (
            "No reviewed complete, non-overlapping BA-to-service-area crosswalk is "
            "available; MISO BA values are not allocated to Minnesota geography."
        ),
        "upstream_checksum_status": UPSTREAM_CHECKSUM_STATUS,
        "sources": [
            {
                "id": "tiger_counties_2024",
                "url": "https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip",
                UPSTREAM_SHA_KEY: _sha256(counties_zip),
                "filter": "STATEFP == '27'",
                "crs": str(counties.crs),
                "units": {"ALAND": "m2", "AWATER": "m2"},
                "rows": len(counties),
            },
            {
                "id": "mngeo_service_areas_2026",
                "url": "https://operations.gis.data.mn.gov/api/publicdownload/download/518/util_eusa.gpkg",
                UPSTREAM_SHA_KEY: _sha256(service_areas_gpkg),
                "crs": str(service_areas.crs),
                "rows": len(service_areas),
                "limit": "retail service-area geometry; not a BA map, bus map, or allocation crosswalk",
            },
            {
                "id": "eia860_2024",
                "url": "https://www.eia.gov/electricity/data/eia860/xls/eia8602024.zip",
                UPSTREAM_SHA_KEY: _sha256(eia860_zip),
                "filter": "Plant/Generator State == 'MN'; Operable generators",
                "units": {"summer_capacity_mw": "MW"},
                "county_capacity_file": paths[CAPACITY_FILE].name,
                "county_capacity_rows": len(capacity),
                "counties_without_assigned_plants": counties_without_plants,
                "county_coverage_note": COUNTY_COVERAGE_NOTE,
                "assigned_plant_count": int(capacity["plant_count"].sum()),
                "assigned_summer_capacity_mw": round(
                    float(capacity["summer_capacity_mw"].sum()), CAPACITY_DECIMALS
                ),
                "unassigned_capacity_file": paths[UNASSIGNED_FILE].name,
                "unassigned_plant_count": len(unassigned_capacity),
                "unassigned_summer_capacity_mw": round(
                    float(unassigned_capacity["summer_capacity_mw"].sum()),
                    CAPACITY_DECIMALS,
                ),
                "geography_limit": "Plants without exactly one containing county remain unassigned or ambiguous; no nearest-county assignment is applied.",
                "file_sha256": {
                    paths[CAPACITY_FILE].name: _text_sha256(paths[CAPACITY_FILE]),
                    paths[UNASSIGNED_FILE].name: _text_sha256(paths[UNASSIGNED_FILE]),
                },
            },
            {
                "id": "eia930_balance_2024_h1",
                "url": "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2024_Jan_Jun.csv",
                UPSTREAM_SHA_KEY: _sha256(eia930_csv),
                "filter": "Balancing Authority == 'MISO'",
                "label": MISO_LABEL,
                "units": {"demand": "MW", "net_generation": "MW", "interchange": "MW"},
                "context_file": paths[CONTEXT_FILE].name,
                "rows": len(miso),
                "time_basis": "UTC end of hour",
                "file_sha256": {
                    paths[CONTEXT_FILE].name: _text_sha256(paths[CONTEXT_FILE]),
                },
            },
        ],
    }
    (output_dir / MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counties-zip", type=Path, required=True)
    parser.add_argument("--service-areas-gpkg", type=Path, required=True)
    parser.add_argument("--eia860-zip", type=Path, required=True)
    parser.add_argument("--eia930-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    args = parser.parse_args(argv)
    build_aggregate_evidence(**vars(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

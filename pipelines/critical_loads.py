"""Public critical-facility loaders; facility-to-bus matches stay explicitly synthetic."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from pipelines.db import log_artifact, replace_frame


def _centroid_counties(con, centroids: gpd.GeoSeries) -> pd.Series:
    """Assign each centroid to a county, preserving missing assignments.

    A centroid outside the loaded county coverage must remain unassigned rather
    than being silently associated with an arbitrary synthetic bus downstream.
    """
    counties = con.execute("SELECT county_fips, geom_wkb FROM counties").fetchdf()
    if counties.empty:
        return pd.Series(pd.NA, index=centroids.index, dtype="string")
    county_geo = gpd.GeoDataFrame(
        counties.drop(columns="geom_wkb"),
        geometry=gpd.GeoSeries.from_wkb(counties.geom_wkb.map(bytes)),
        crs=4326,
    )
    points = gpd.GeoDataFrame(
        {"source_index": centroids.index}, index=centroids.index, geometry=centroids, crs=4326
    )
    assigned = gpd.sjoin(points, county_geo[["county_fips", "geometry"]], how="left", predicate="within")
    assigned = assigned.drop_duplicates("source_index", keep="first").set_index("source_index")["county_fips"]
    return assigned.reindex(centroids.index).astype("string")


def load_dod(con, geojson_path: str, min_area_km2: float = 1.0, release: str = "fy2024") -> int:
    path = Path(geojson_path)
    bases = gpd.read_file(path).to_crs(3083)
    active = bases[(bases["stateNameCode"].str.lower() == "tx") & (bases["siteOperationalStatus"] == "act")].copy()
    active["area_km2"] = active.geometry.area / 1_000_000
    active = active[active.area_km2 >= min_area_km2].copy()
    centroids = active.geometry.centroid.to_crs(4326)
    county_fips = _centroid_counties(con, centroids)
    source_id = active.index.astype(str)
    frame = pd.DataFrame({
        "cl_id": np.arange(1, len(active) + 1), "kind": "dod", "name": active["siteName"].astype(str),
        "lon": centroids.x, "lat": centroids.y, "bus_id": None, "county_fips": county_fips.to_numpy(),
    })
    unassigned = frame[frame.county_fips.isna()]
    if not unassigned.empty:
        con.execute("INSERT INTO ingest_warnings VALUES ('ntad_military_bases', 'county_assignment', ?, current_timestamp)",
                    [f"skipped {len(unassigned)} facilities outside loaded county coverage"])
        frame = frame[frame.county_fips.notna()].copy()
        active = active.loc[frame.index]
    source_id = active.index.astype(str)
    rows = replace_frame(con, "critical_loads", frame, where="kind = 'dod'", source_name="ntad_military_bases",
                         source_ref=path.name, source_version=release, fixture_batch_id=f"p0-ntad-{release}")
    con.execute("""CREATE TABLE IF NOT EXISTS critical_load_geometry(cl_id INTEGER PRIMARY KEY, source_id TEXT,
        reporting_component TEXT, operational_status TEXT, is_joint_base BOOLEAN, area_km2 DOUBLE, geom_wkb BLOB)""")
    geometry = pd.DataFrame({
        "cl_id": frame.cl_id, "source_id": source_id, "reporting_component": active.get("siteReportingComponent"),
        "operational_status": active["siteOperationalStatus"], "is_joint_base": active.get("isJointBase"),
        "area_km2": active.area_km2, "geom_wkb": active.geometry.to_wkb(),
    })
    replace_frame(con, "critical_load_geometry", geometry, where="TRUE")
    log_artifact(con, source="ntad_military_bases", source_release=release, path=path, rows_loaded=rows,
                 schema_fingerprint="siteName,status,state,component,joint-base,polygon")
    return rows

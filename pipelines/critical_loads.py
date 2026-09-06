"""Public critical-facility loaders; facility-to-bus matches stay explicitly synthetic."""

from __future__ import annotations

import hashlib
from pathlib import Path

import geopandas as gpd
import pandas as pd

from pipelines.db import log_artifact, replace_frame
from pipelines.state_scope import StateScope, scope


def _stable_id(namespace: str, source_id: str) -> int:
    """Produce a positive ID compatible with the legacy geometry table."""
    # critical_load_geometry was already published with an INTEGER primary key;
    # keep the derived ID in that range until its schema owner migrates it.
    return int(hashlib.sha256(f"{namespace}:{source_id}".encode()).hexdigest()[:7], 16)


def _ntad_source_ids(active: gpd.GeoDataFrame) -> pd.Series:
    """Use the NTAD record identifier, never a GeoDataFrame row position."""
    for column in ("mirtaLocationsIdpk", "OBJECTID"):
        if column in active and active[column].notna().all():
            return column + ":" + active[column].astype(str)
    # The public NTAD schema supplies mirtaLocationsIdpk.  A content-derived
    # fallback is stable for a release that omits it, unlike the input row index.
    required = [
        "siteName",
        "stateNameCode",
        "siteOperationalStatus",
        "siteReportingComponent",
        "isJointBase",
    ]
    if not set(required).issubset(active.columns):
        raise ValueError(
            "NTAD data lacks a stable facility identity (mirtaLocationsIdpk or required feature fields)"
        )
    return active.apply(
        lambda row: (
            "content:"
            + hashlib.sha256(
                "|".join(str(row[name]) for name in required).encode()
                + bytes(row.geometry.wkb)
            ).hexdigest()
        ),
        axis=1,
    )


def _ntad_cl_ids(active: gpd.GeoDataFrame, source_ids: pd.Series) -> pd.Series:
    """Use source-derived IDs when NTAD supplies one; retain fixture compatibility otherwise."""
    if any(
        column in active and active[column].notna().all()
        for column in ("mirtaLocationsIdpk", "OBJECTID")
    ):
        return source_ids.map(lambda value: _stable_id("ntad_military_bases", value))
    # Hand-authored unit fixtures from before the NTAD identity field use only
    # descriptive properties.  Their canonical ordering is deterministic for a
    # fixed fixture and does not affect real NTAD releases, which take the
    # immutable-ID path above.
    ranks = {
        value: index for index, value in enumerate(sorted(source_ids.unique()), start=1)
    }
    return source_ids.map(ranks)


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
        {"source_index": centroids.index},
        index=centroids.index,
        geometry=centroids,
        crs=4326,
    )
    assigned = gpd.sjoin(
        points, county_geo[["county_fips", "geometry"]], how="left", predicate="within"
    )
    assigned = assigned.drop_duplicates("source_index", keep="first").set_index(
        "source_index"
    )["county_fips"]
    return assigned.reindex(centroids.index).astype("string")


def load_dod(
    con,
    geojson_path: str,
    min_area_km2: float = 1.0,
    release: str = "fy2024",
    states=None,
) -> int:
    path = Path(geojson_path)
    selected_scope = states if isinstance(states, StateScope) else scope(states)
    bases = gpd.read_file(path).to_crs(3083)
    active = bases[
        bases["stateNameCode"].str.upper().isin(selected_scope.usps)
        & (bases["siteOperationalStatus"] == "act")
    ].copy()
    active["area_km2"] = active.geometry.area / 1_000_000
    active = active[active.area_km2 >= min_area_km2].copy()
    centroids = active.geometry.centroid.to_crs(4326)
    county_fips = _centroid_counties(con, centroids)
    source_id = _ntad_source_ids(active)
    frame = pd.DataFrame(
        {
            "cl_id": _ntad_cl_ids(active, source_id),
            "kind": "dod",
            "name": active["siteName"].astype(str),
            "lon": centroids.x,
            "lat": centroids.y,
            "bus_id": None,
            "county_fips": county_fips.to_numpy(),
        }
    )
    unassigned = frame[frame.county_fips.isna()]
    if not unassigned.empty:
        con.execute(
            "INSERT INTO ingest_warnings VALUES ('ntad_military_bases', 'county_assignment', ?, current_timestamp)",
            [f"skipped {len(unassigned)} facilities outside loaded county coverage"],
        )
        frame = frame[frame.county_fips.notna()].copy()
        active = active.loc[frame.index]
    source_id = source_id.loc[frame.index]
    frame["cl_id"] = _ntad_cl_ids(active, source_id).to_numpy()
    con.execute("""CREATE TABLE IF NOT EXISTS critical_load_geometry(cl_id INTEGER PRIMARY KEY, source_id TEXT,
        reporting_component TEXT, operational_status TEXT, is_joint_base BOOLEAN, area_km2 DOUBLE, geom_wkb BLOB)""")
    # Remove only geometry currently owned by DoD before replacing its parent
    # slice.  Other facility sources keep their geometry rows intact.
    scoped_dod = f"kind = 'dod' AND ({selected_scope.county_where()})"
    con.execute(
        "DELETE FROM critical_load_geometry WHERE cl_id IN "
        f"(SELECT cl_id FROM critical_loads WHERE {scoped_dod})"
    )
    rows = replace_frame(
        con,
        "critical_loads",
        frame,
        where=scoped_dod,
        source_name="ntad_military_bases",
        source_ref=path.name,
        source_version=release,
        fixture_batch_id=f"p0-ntad-{release}",
    )
    geometry = pd.DataFrame(
        {
            "cl_id": frame.cl_id,
            "source_id": source_id,
            "reporting_component": active.get("siteReportingComponent"),
            "operational_status": active["siteOperationalStatus"],
            "is_joint_base": active.get("isJointBase"),
            "area_km2": active.area_km2,
            "geom_wkb": active.geometry.to_wkb(),
        }
    )
    replace_frame(
        con,
        "critical_load_geometry",
        geometry,
        where=f"cl_id IN (SELECT cl_id FROM critical_loads WHERE {scoped_dod})",
    )
    log_artifact(
        con,
        source="ntad_military_bases",
        source_release=release,
        path=path,
        rows_loaded=rows,
        schema_fingerprint="siteName,status,state,component,joint-base,polygon",
    )
    return rows

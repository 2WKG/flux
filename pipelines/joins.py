"""Spatial joins that keep synthetic and real-world identities explicitly separate."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd


def join_bus_county(con, fallback_km: float = 30.0) -> int:
    buses = con.execute("SELECT bus_id, lon, lat FROM buses").fetchdf()
    counties = con.execute("SELECT county_fips, geom_wkb FROM counties").fetchdf()
    if counties.empty:
        raise ValueError("counties must load before bus-to-county assignment")
    county_geo = gpd.GeoDataFrame(
        counties[["county_fips"]].rename(columns={"county_fips": "_matched_county_fips"}),
        geometry=gpd.GeoSeries.from_wkb(counties.geom_wkb.map(bytes)), crs=4326,
    )
    bus_geo = gpd.GeoDataFrame(buses, geometry=gpd.points_from_xy(buses.lon, buses.lat), crs=4326)
    # ``intersects`` includes a bus exactly on a county boundary; sorting below
    # then gives that shared boundary a stable, documented FIPS tie-break.
    hit = gpd.sjoin(bus_geo, county_geo[["_matched_county_fips", "geometry"]], how="left", predicate="intersects")
    # County polygons can share an edge or overlap in an input release.  Keep a
    # deterministic county when the containment join returns more than one row.
    hit = hit.sort_values(["bus_id", "_matched_county_fips"], kind="stable").drop_duplicates("bus_id", keep="first")
    unmatched = hit.loc[hit._matched_county_fips.isna(), ["bus_id", "geometry"]]
    if not unmatched.empty:
        nearest = gpd.sjoin_nearest(unmatched.to_crs(3083), county_geo[["_matched_county_fips", "geometry"]].to_crs(3083),
                                    how="left", max_distance=fallback_km * 1000, distance_col="fallback_m")
        nearest = nearest.sort_values(["bus_id", "fallback_m", "_matched_county_fips"], kind="stable")
        nearest = nearest.drop_duplicates("bus_id", keep="first")
        nearest_county = nearest.set_index("bus_id")._matched_county_fips
        hit["_matched_county_fips"] = hit["_matched_county_fips"].fillna(hit["bus_id"].map(nearest_county))
    result = hit[["bus_id", "_matched_county_fips"]].rename(columns={"_matched_county_fips": "county_fips"})
    con.register("_bus_county", result)
    try:
        con.execute("UPDATE buses AS b SET county_fips = m.county_fips FROM _bus_county AS m WHERE b.bus_id = m.bus_id AND b.county_fips IS DISTINCT FROM m.county_fips")
    finally:
        con.unregister("_bus_county")
    missing = int(result.county_fips.isna().sum())
    if missing:
        con.execute("INSERT INTO ingest_warnings VALUES ('joins', 'bus_county', ?, current_timestamp)",
                    [f"{missing} synthetic buses exceeded {fallback_km:g} km county fallback"])
    return len(result) - missing


def join_critical_loads_to_bus(con, min_kv: float = 115.0) -> int:
    facilities = con.execute("SELECT cl_id, county_fips, lon, lat FROM critical_loads").fetchdf()
    buses = con.execute("SELECT bus_id, county_fips, base_kv, lon, lat FROM buses WHERE base_kv >= ?", [min_kv]).fetchdf()
    if facilities.empty:
        return 0
    con.execute("UPDATE critical_loads SET bus_id = NULL")
    con.execute("""CREATE TABLE IF NOT EXISTS critical_load_bus_dist(cl_id INTEGER PRIMARY KEY, bus_id INTEGER,
        distance_km DOUBLE, match_method TEXT)""")
    con.register("_critical_facilities", facilities[["cl_id"]])
    try:
        con.execute("DELETE FROM critical_load_bus_dist WHERE cl_id IN (SELECT cl_id FROM _critical_facilities)")
    finally:
        con.unregister("_critical_facilities")
    if buses.empty:
        return 0
    facility_geo = gpd.GeoDataFrame(facilities, geometry=gpd.points_from_xy(facilities.lon, facilities.lat), crs=4326).to_crs(3083)
    bus_geo = gpd.GeoDataFrame(buses, geometry=gpd.points_from_xy(buses.lon, buses.lat), crs=4326).to_crs(3083)
    matches: list[dict[str, object]] = []
    for row in facility_geo.itertuples():
        if pd.isna(row.county_fips):
            matches.append({"cl_id": row.cl_id, "bus_id": None, "distance_km": None,
                            "match_method": "unassigned_no_county"})
            continue
        same_county = bus_geo[bus_geo.county_fips.eq(row.county_fips)]
        if same_county.empty:
            matches.append({"cl_id": row.cl_id, "bus_id": None, "distance_km": None,
                            "match_method": "unassigned_no_eligible_bus"})
            continue
        pool, method = same_county.sort_values("bus_id", kind="stable"), "same_county"
        distances = pool.geometry.distance(row.geometry)
        minimum = distances.min()
        nearest = pool.loc[distances.eq(minimum)].sort_values("bus_id", kind="stable").iloc[0]
        matches.append({"cl_id": row.cl_id, "bus_id": int(nearest.bus_id), "distance_km": float(minimum / 1000), "match_method": method})
    result = pd.DataFrame(matches).astype({"cl_id": "int64", "bus_id": "Int64", "distance_km": "float64",
                                           "match_method": "string"})
    con.register("_critical_bus", result)
    try:
        con.execute("""UPDATE critical_loads AS c SET bus_id = m.bus_id
                       FROM _critical_bus AS m WHERE c.cl_id = m.cl_id AND m.bus_id IS NOT NULL""")
        con.execute("INSERT OR REPLACE INTO critical_load_bus_dist SELECT * FROM _critical_bus")
    finally:
        con.unregister("_critical_bus")
    return int(result.bus_id.notna().sum())

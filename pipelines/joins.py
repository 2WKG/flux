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
        counties.drop(columns="geom_wkb"), geometry=gpd.GeoSeries.from_wkb(counties.geom_wkb.map(bytes)), crs=4326
    )
    bus_geo = gpd.GeoDataFrame(buses, geometry=gpd.points_from_xy(buses.lon, buses.lat), crs=4326)
    hit = gpd.sjoin(bus_geo, county_geo[["county_fips", "geometry"]], how="left", predicate="within")
    unmatched = hit[hit.county_fips.isna()].drop(columns=["index_right"], errors="ignore")
    if not unmatched.empty:
        nearest = gpd.sjoin_nearest(unmatched.to_crs(3083), county_geo[["county_fips", "geometry"]].to_crs(3083),
                                    how="left", max_distance=fallback_km * 1000, distance_col="fallback_m")
        hit.loc[unmatched.index, "county_fips"] = nearest.set_index("bus_id").reindex(unmatched.bus_id).county_fips.to_numpy()
    result = hit[["bus_id", "county_fips"]].drop_duplicates("bus_id")
    con.register("_bus_county", result)
    try:
        con.execute("UPDATE buses AS b SET county_fips = m.county_fips FROM _bus_county AS m WHERE b.bus_id = m.bus_id")
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
    if facilities.empty or buses.empty:
        return 0
    facility_geo = gpd.GeoDataFrame(facilities, geometry=gpd.points_from_xy(facilities.lon, facilities.lat), crs=4326).to_crs(3083)
    bus_geo = gpd.GeoDataFrame(buses, geometry=gpd.points_from_xy(buses.lon, buses.lat), crs=4326).to_crs(3083)
    matches: list[dict[str, object]] = []
    for row in facility_geo.itertuples():
        same_county = bus_geo[bus_geo.county_fips.eq(row.county_fips)]
        pool, method = (same_county, "same_county") if not same_county.empty else (bus_geo, "nearest_anywhere")
        distances = pool.geometry.distance(row.geometry)
        nearest = pool.loc[distances.idxmin()]
        matches.append({"cl_id": row.cl_id, "bus_id": int(nearest.bus_id), "distance_km": float(distances.loc[distances.idxmin()] / 1000), "match_method": method})
    result = pd.DataFrame(matches)
    con.execute("""CREATE TABLE IF NOT EXISTS critical_load_bus_dist(cl_id INTEGER PRIMARY KEY, bus_id INTEGER,
        distance_km DOUBLE, match_method TEXT)""")
    con.register("_critical_bus", result)
    try:
        con.execute("UPDATE critical_loads AS c SET bus_id = m.bus_id FROM _critical_bus AS m WHERE c.cl_id = m.cl_id")
        con.execute("INSERT OR REPLACE INTO critical_load_bus_dist SELECT * FROM _critical_bus")
    finally:
        con.unregister("_critical_bus")
    return len(result)

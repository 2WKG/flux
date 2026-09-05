"""The versioned DuckDB contract used by fixture-producing pipelines."""

from __future__ import annotations

from pathlib import Path

import duckdb


SCHEMA_VERSION = "1.0.0"
CONTRACT_TABLES = (
    "buses", "lines", "gens", "loads", "counties", "critical_loads",
    "eaglei_outages", "weather_hourly", "storm_events", "hazard_static",
    "ba_load_hourly", "site_candidates", "scenarios", "outage_predictions",
    "cascade_runs", "site_scores", "line_upgrade_scores", "line_upgrade_detail",
    "corpus_chunks",
)

# Every fixture row identifies its source record and reproducible build. Derived
# rows use their Flux module as source_name and their input artifact/run as ref.
PROVENANCE_COLUMNS = """
    source_name TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_version TEXT,
    source_retrieved_at TIMESTAMP,
    fixture_batch_id TEXT NOT NULL
"""

SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    f"""CREATE TABLE IF NOT EXISTS counties (
        county_fips TEXT PRIMARY KEY CHECK (regexp_full_match(county_fips, '[0-9]{{5}}')),
        name TEXT NOT NULL, state TEXT NOT NULL, pop BIGINT NOT NULL CHECK (pop >= 0),
        geom_wkb BLOB NOT NULL, {PROVENANCE_COLUMNS})""",
    f"""CREATE TABLE IF NOT EXISTS buses (
        bus_id BIGINT PRIMARY KEY, name TEXT NOT NULL, base_kv DOUBLE NOT NULL CHECK (base_kv > 0),
        lon DOUBLE NOT NULL CHECK (lon BETWEEN -180 AND 180), lat DOUBLE NOT NULL CHECK (lat BETWEEN -90 AND 90),
        county_fips TEXT REFERENCES counties(county_fips), ba_code TEXT, coord_source TEXT NOT NULL,
        zone INTEGER, area INTEGER, {PROVENANCE_COLUMNS})""",
    f"""CREATE TABLE IF NOT EXISTS lines (
        line_id BIGINT PRIMARY KEY, from_bus BIGINT NOT NULL REFERENCES buses(bus_id),
        to_bus BIGINT NOT NULL REFERENCES buses(bus_id), circuit TEXT NOT NULL,
        base_kv DOUBLE NOT NULL CHECK (base_kv > 0), r_pu DOUBLE NOT NULL, x_pu DOUBLE NOT NULL,
        rate_a_mw DOUBLE, length_km DOUBLE NOT NULL CHECK (length_km >= 0), geom_wkb BLOB,
        is_transformer BOOLEAN NOT NULL, {PROVENANCE_COLUMNS}, UNIQUE (from_bus, to_bus, circuit))""",
    f"""CREATE TABLE IF NOT EXISTS gens (
        gen_id BIGINT PRIMARY KEY, bus_id BIGINT NOT NULL REFERENCES buses(bus_id), fuel TEXT NOT NULL,
        pmax_mw DOUBLE NOT NULL CHECK (pmax_mw >= 0), eia_plant_id BIGINT, source_unit_id TEXT NOT NULL,
        {PROVENANCE_COLUMNS}, UNIQUE (bus_id, source_unit_id))""",
    f"""CREATE TABLE IF NOT EXISTS loads (
        load_id BIGINT PRIMARY KEY, bus_id BIGINT NOT NULL REFERENCES buses(bus_id),
        p_mw_nominal DOUBLE NOT NULL CHECK (p_mw_nominal >= 0), {PROVENANCE_COLUMNS}, UNIQUE (bus_id))""",
    f"""CREATE TABLE IF NOT EXISTS critical_loads (
        cl_id BIGINT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('dod', 'hospital', 'water')),
        name TEXT NOT NULL, lon DOUBLE NOT NULL CHECK (lon BETWEEN -180 AND 180),
        lat DOUBLE NOT NULL CHECK (lat BETWEEN -90 AND 90), bus_id BIGINT REFERENCES buses(bus_id),
        county_fips TEXT NOT NULL REFERENCES counties(county_fips), {PROVENANCE_COLUMNS})""",
    f"""CREATE TABLE IF NOT EXISTS eaglei_outages (
        county_fips TEXT NOT NULL REFERENCES counties(county_fips), ts TIMESTAMP NOT NULL,
        customers_out BIGINT NOT NULL CHECK (customers_out >= 0), {PROVENANCE_COLUMNS},
        PRIMARY KEY (county_fips, ts))""",
    f"""CREATE TABLE IF NOT EXISTS weather_hourly (
        county_fips TEXT NOT NULL REFERENCES counties(county_fips), ts TIMESTAMP NOT NULL,
        wind_ms DOUBLE, gust_ms DOUBLE, temp_c DOUBLE, ice_mm DOUBLE, precip_mm DOUBLE,
        {PROVENANCE_COLUMNS}, PRIMARY KEY (county_fips, ts))""",
    f"""CREATE TABLE IF NOT EXISTS storm_events (
        event_id BIGINT NOT NULL, county_fips TEXT NOT NULL REFERENCES counties(county_fips),
        ts_begin TIMESTAMP NOT NULL, ts_end TIMESTAMP NOT NULL CHECK (ts_end >= ts_begin),
        type TEXT NOT NULL, magnitude DOUBLE, {PROVENANCE_COLUMNS}, PRIMARY KEY (event_id, county_fips))""",
    f"""CREATE TABLE IF NOT EXISTS hazard_static (
        county_fips TEXT PRIMARY KEY REFERENCES counties(county_fips), nri_score DOUBLE,
        wildfire_hazard DOUBLE, seismic_pga DOUBLE CHECK (seismic_pga IS NULL OR seismic_pga >= 0),
        {PROVENANCE_COLUMNS})""",
    f"""CREATE TABLE IF NOT EXISTS ba_load_hourly (
        ba_code TEXT NOT NULL, ts TIMESTAMP NOT NULL, demand_mw DOUBLE NOT NULL CHECK (demand_mw >= 0),
        {PROVENANCE_COLUMNS}, PRIMARY KEY (ba_code, ts))""",
    f"""CREATE TABLE IF NOT EXISTS site_candidates (
        site_id BIGINT PRIMARY KEY, name TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('coal_retired', 'coal_retiring', 'nuclear_existing', 'doe_federal', 'dod')),
        lon DOUBLE NOT NULL CHECK (lon BETWEEN -180 AND 180), lat DOUBLE NOT NULL CHECK (lat BETWEEN -90 AND 90),
        county_fips TEXT NOT NULL REFERENCES counties(county_fips), bus_id BIGINT REFERENCES buses(bus_id),
        capacity_slot_mw DOUBLE NOT NULL CHECK (capacity_slot_mw > 0), source_site_id TEXT NOT NULL,
        {PROVENANCE_COLUMNS}, UNIQUE (source_name, source_site_id))""",
    f"""CREATE TABLE IF NOT EXISTS scenarios (
        scenario_id TEXT PRIMARY KEY, name TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('historical', 'forecast', 'synthetic')),
        ts_start TIMESTAMP NOT NULL, ts_end TIMESTAMP NOT NULL CHECK (ts_end >= ts_start),
        {PROVENANCE_COLUMNS})""",
    f"""CREATE TABLE IF NOT EXISTS outage_predictions (
        scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
        county_fips TEXT NOT NULL REFERENCES counties(county_fips), ts TIMESTAMP NOT NULL,
        p_out DOUBLE NOT NULL CHECK (p_out BETWEEN 0 AND 1),
        customers_at_risk BIGINT NOT NULL CHECK (customers_at_risk >= 0),
        driver TEXT NOT NULL CHECK (driver IN ('ice', 'wind', 'heat', 'wildfire', 'flood', 'other')),
        {PROVENANCE_COLUMNS}, PRIMARY KEY (scenario_id, county_fips, ts))""",
    f"""CREATE TABLE IF NOT EXISTS cascade_runs (
        run_id TEXT NOT NULL, scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
        hour INTEGER NOT NULL CHECK (hour >= 0), tripped_element_ids_json JSON NOT NULL,
        lost_load_mw DOUBLE NOT NULL CHECK (lost_load_mw >= 0), counties_dark_json JSON NOT NULL,
        critical_loads_lost_json JSON NOT NULL, counterfactual_site_id BIGINT REFERENCES site_candidates(site_id),
        {PROVENANCE_COLUMNS}, PRIMARY KEY (run_id, hour))""",
    f"""CREATE TABLE IF NOT EXISTS site_scores (
        site_id BIGINT NOT NULL REFERENCES site_candidates(site_id), scenario_id TEXT NOT NULL,
        unit_mw DOUBLE NOT NULL CHECK (unit_mw > 0), safety_score DOUBLE NOT NULL CHECK (safety_score BETWEEN 0 AND 100),
        safety_flags_json JSON NOT NULL, grid_value_score DOUBLE, lol_reduction_mwh DOUBLE,
        congestion_relief_pct DOUBLE, blackstart_reach_mw DOUBLE, {PROVENANCE_COLUMNS},
        PRIMARY KEY (site_id, scenario_id, unit_mw))""",
    f"""CREATE TABLE IF NOT EXISTS line_upgrade_scores (
        line_id BIGINT PRIMARY KEY REFERENCES lines(line_id), congestion_usd_yr DOUBLE,
        dlr_uplift_mw DOUBLE, reconductor_uplift_mw DOUBLE, dlr_cost_usd DOUBLE,
        reconductor_cost_usd DOUBLE, mw_per_musd DOUBLE, ferc_screen_pass BOOLEAN,
        spark_eligible BOOLEAN, {PROVENANCE_COLUMNS})""",
    f"""CREATE TABLE IF NOT EXISTS line_upgrade_detail (
        line_id BIGINT PRIMARY KEY REFERENCES lines(line_id), owner TEXT, conductor_material TEXT,
        conductor_kcmil DOUBLE, static_rating_mw DOUBLE NOT NULL CHECK (static_rating_mw >= 0),
        aar_rating_mw DOUBLE, dlr_p50_mw DOUBLE, dlr_hours_above_static INTEGER,
        best_tech TEXT CHECK (best_tech IN ('dlr', 'reconductor')), payback_yr DOUBLE,
        congestion_method TEXT NOT NULL CHECK (congestion_method IN ('exact', 'fuzzy', 'twin_proxy', 'unmapped')),
        region TEXT NOT NULL, {PROVENANCE_COLUMNS})""",
    f"""CREATE TABLE IF NOT EXISTS corpus_chunks (
        chunk_id TEXT PRIMARY KEY, doc TEXT NOT NULL, title TEXT NOT NULL,
        page INTEGER NOT NULL CHECK (page > 0), chunk_ordinal INTEGER NOT NULL CHECK (chunk_ordinal >= 0),
        text TEXT NOT NULL, embedding FLOAT[1024], {PROVENANCE_COLUMNS}, UNIQUE (doc, page, chunk_ordinal))""",
)

TABLE_COLUMNS = {
    "buses": ("bus_id", "name", "base_kv", "lon", "lat", "county_fips", "ba_code", "coord_source", "zone", "area"),
    "lines": ("line_id", "from_bus", "to_bus", "circuit", "base_kv", "r_pu", "x_pu", "rate_a_mw", "length_km", "geom_wkb", "is_transformer"),
    "gens": ("gen_id", "bus_id", "fuel", "pmax_mw", "eia_plant_id", "source_unit_id"),
    "loads": ("load_id", "bus_id", "p_mw_nominal"), "counties": ("county_fips", "name", "state", "pop", "geom_wkb"),
    "critical_loads": ("cl_id", "kind", "name", "lon", "lat", "bus_id", "county_fips"),
    "eaglei_outages": ("county_fips", "ts", "customers_out"),
    "weather_hourly": ("county_fips", "ts", "wind_ms", "gust_ms", "temp_c", "ice_mm", "precip_mm"),
    "storm_events": ("event_id", "county_fips", "ts_begin", "ts_end", "type", "magnitude"),
    "hazard_static": ("county_fips", "nri_score", "wildfire_hazard", "seismic_pga"),
    "ba_load_hourly": ("ba_code", "ts", "demand_mw"),
    "site_candidates": ("site_id", "name", "kind", "lon", "lat", "county_fips", "bus_id", "capacity_slot_mw", "source_site_id"),
    "scenarios": ("scenario_id", "name", "kind", "ts_start", "ts_end"),
    "outage_predictions": ("scenario_id", "county_fips", "ts", "p_out", "customers_at_risk", "driver"),
    "cascade_runs": ("run_id", "scenario_id", "hour", "tripped_element_ids_json", "lost_load_mw", "counties_dark_json", "critical_loads_lost_json", "counterfactual_site_id"),
    "site_scores": ("site_id", "scenario_id", "unit_mw", "safety_score", "safety_flags_json", "grid_value_score", "lol_reduction_mwh", "congestion_relief_pct", "blackstart_reach_mw"),
    "line_upgrade_scores": ("line_id", "congestion_usd_yr", "dlr_uplift_mw", "reconductor_uplift_mw", "dlr_cost_usd", "reconductor_cost_usd", "mw_per_musd", "ferc_screen_pass", "spark_eligible"),
    "line_upgrade_detail": ("line_id", "owner", "conductor_material", "conductor_kcmil", "static_rating_mw", "aar_rating_mw", "dlr_p50_mw", "dlr_hours_above_static", "best_tech", "payback_yr", "congestion_method", "region"),
    "corpus_chunks": ("chunk_id", "doc", "title", "page", "chunk_ordinal", "text", "embedding"),
}
PROVENANCE_COLUMN_NAMES = ("source_name", "source_ref", "source_version", "source_retrieved_at", "fixture_batch_id")


def connect(path: str | Path = "data/duck/grid.duckdb", *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=read_only)


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create v1, refusing to silently use a different contract version."""
    for statement in SCHEMA_STATEMENTS:
        con.execute(statement)
    existing = con.execute("SELECT value FROM schema_meta WHERE key = 'contract_version'").fetchone()
    if existing is None:
        con.execute("INSERT INTO schema_meta (key, value) VALUES ('contract_version', ?)", [SCHEMA_VERSION])
    elif existing[0] != SCHEMA_VERSION:
        raise RuntimeError(f"DuckDB contract version is {existing[0]!r}, expected {SCHEMA_VERSION!r}; migrate explicitly.")
    validate_schema(con)


def validate_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Raise when a pre-existing table cannot satisfy this contract."""
    for table, columns in TABLE_COLUMNS.items():
        actual = tuple(row[1] for row in con.execute(f"PRAGMA table_info('{table}')").fetchall())
        expected = columns + PROVENANCE_COLUMN_NAMES
        if actual != expected:
            raise RuntimeError(f"{table} columns are {actual!r}, expected {expected!r}; migrate explicitly.")

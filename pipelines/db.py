"""The versioned DuckDB contract used by fixture-producing pipelines."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from pipelines.common import sha256_file, utc_now

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

P0_HELPER_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS ingest_log(source TEXT, source_release TEXT, source_file TEXT,
        sha256 TEXT, bytes BIGINT, rows_loaded BIGINT, schema_fingerprint TEXT, loader_version TEXT,
        loaded_at TIMESTAMP, PRIMARY KEY(source, source_release, source_file, sha256))""",
    """CREATE TABLE IF NOT EXISTS ingest_warnings(source TEXT, source_key TEXT, warning TEXT,
        created_at TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS synthetic_substations(sub_num INTEGER PRIMARY KEY, sub_name TEXT,
        sub_id TEXT, lon DOUBLE, lat DOUBLE)""",
    """CREATE TABLE IF NOT EXISTS synthetic_bus_electrical(bus_id INTEGER PRIMARY KEY, bus_type INTEGER,
        pd_mw DOUBLE, qd_mvar DOUBLE, gs_mw DOUBLE, bs_mvar DOUBLE, vm_pu DOUBLE, va_deg DOUBLE,
        vmin_pu DOUBLE, vmax_pu DOUBLE)""",
    """CREATE TABLE IF NOT EXISTS synthetic_branch_electrical(line_id INTEGER PRIMARY KEY, b_pu DOUBLE,
        tap_ratio DOUBLE, shift_deg DOUBLE, status INTEGER)""",
    """CREATE TABLE IF NOT EXISTS synthetic_generator_electrical(gen_id INTEGER PRIMARY KEY, p_mw DOUBLE,
        q_mvar DOUBLE, qmax_mvar DOUBLE, qmin_mvar DOUBLE, pmin_mw DOUBLE, status INTEGER,
        generator_type TEXT)""",
    """CREATE TABLE IF NOT EXISTS county_geo_meta(county_fips TEXT, tiger_vintage TEXT, aland_m2 BIGINT,
        awater_m2 BIGINT, PRIMARY KEY(county_fips, tiger_vintage))""",
    """CREATE TABLE IF NOT EXISTS nri_hazards(county_fips TEXT, hazard_code TEXT, risk_score DOUBLE,
        risk_rating TEXT, eal_value DOUBLE, source_release TEXT,
        PRIMARY KEY(county_fips, hazard_code, source_release))""",
    """CREATE TABLE IF NOT EXISTS ba_operations_hourly(ba_code TEXT, ts TIMESTAMP, demand_raw_mw DOUBLE,
        demand_adjusted_mw DOUBLE, demand_imputed_mw DOUBLE, demand_forecast_mw DOUBLE,
        net_generation_mw DOUBLE, total_interchange_mw DOUBLE, valid_dibas_mw DOUBLE,
        PRIMARY KEY(ba_code, ts))""",
    """CREATE TABLE IF NOT EXISTS eaglei_outage_observations(county_fips TEXT, ts TIMESTAMP,
        customers_out INTEGER, source_year INTEGER, source_file TEXT, raw_timestamp TEXT,
        total_customers INTEGER, PRIMARY KEY(county_fips, ts, source_year))""",
    """CREATE TABLE IF NOT EXISTS county_customers(county_fips TEXT, source_year INTEGER,
        customers INTEGER, source TEXT, PRIMARY KEY(county_fips, source_year, source))""",
    """CREATE TABLE IF NOT EXISTS eaglei_coverage(source_year INTEGER, state TEXT, total_customers INTEGER,
        min_covered INTEGER, max_covered INTEGER, min_pct_covered DOUBLE, max_pct_covered DOUBLE,
        PRIMARY KEY(source_year, state))""",
    """CREATE TABLE IF NOT EXISTS eaglei_ingest_quality(source_year INTEGER PRIMARY KEY, source_file TEXT,
        source_timezone TEXT, raw_tx_rows BIGINT, valid_rows BIGINT, missing_customers BIGINT,
        negative_customers BIGINT, duplicate_keys BIGINT, source_counties INTEGER, loaded_at TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS eia_plants(plant_id_eia INTEGER PRIMARY KEY, plant_name TEXT, lon DOUBLE,
        lat DOUBLE, state TEXT, county_fips TEXT, capacity_mw DOUBLE, primary_fuel TEXT,
        retirement_year INTEGER, operational_status TEXT, report_date DATE)""",
    """CREATE TABLE IF NOT EXISTS eia_generator_inventory(plant_id_eia INTEGER, generator_id TEXT,
        report_date DATE, capacity_mw DOUBLE, prime_mover_code TEXT, energy_source_code_1 TEXT,
        fuel_type_code_pudl TEXT, operational_status TEXT, retirement_date DATE,
        planned_retirement_date DATE, PRIMARY KEY(plant_id_eia, generator_id, report_date))""",
)


def connect(path: str | Path = "data/duck/grid.duckdb", *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    output = Path(path)
    if not read_only:
        output.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(output), read_only=read_only)
    if not read_only:
        ensure_schema(con)
    return con


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create v1, refusing to silently use a different contract version."""
    for statement in SCHEMA_STATEMENTS:
        con.execute(statement)
    for statement in P0_HELPER_STATEMENTS:
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


def contract_frame(frame: pd.DataFrame, table: str, *, source_name: str, source_ref: str,
                   source_version: str | None = None, source_retrieved_at: datetime | None = None,
                   fixture_batch_id: str) -> pd.DataFrame:
    """Attach provenance without manufacturing an unavailable retrieval timestamp."""
    if table not in TABLE_COLUMNS:
        return frame
    if source_retrieved_at is not None and source_retrieved_at.tzinfo is None:
        raise ValueError("source_retrieved_at must be UTC-aware when it is known")
    result = frame.copy()
    result["source_name"] = source_name
    result["source_ref"] = source_ref
    result["source_version"] = source_version
    result["source_retrieved_at"] = source_retrieved_at.astimezone(UTC).replace(tzinfo=None) if source_retrieved_at else None
    result["fixture_batch_id"] = fixture_batch_id
    return result


def replace_frame(con: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame, where: str = "TRUE",
                  *, source_name: str | None = None, source_ref: str | None = None,
                  source_version: str | None = None, source_retrieved_at: datetime | None = None,
                  fixture_batch_id: str | None = None) -> int:
    """Replace a logical slice, requiring provenance for canonical contract rows."""
    if table in TABLE_COLUMNS and not all((source_name, source_ref, fixture_batch_id)):
        raise ValueError(f"{table} requires source_name, source_ref, and fixture_batch_id")
    con.execute(f"DELETE FROM {table} WHERE {where}")
    if frame.empty:
        return 0
    if table in TABLE_COLUMNS:
        frame = contract_frame(frame, table, source_name=source_name, source_ref=source_ref,
                               source_version=source_version, source_retrieved_at=source_retrieved_at,
                               fixture_batch_id=fixture_batch_id)
    con.register("_incoming", frame)
    try:
        con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM _incoming")
    finally:
        con.unregister("_incoming")
    return len(frame)


def log_artifact(con: duckdb.DuckDBPyConnection, *, source: str, source_release: str,
                 path: str | Path, rows_loaded: int, schema_fingerprint: str,
                 loader_version: str = "p0-v1") -> None:
    artifact = Path(path)
    con.execute(
        """INSERT OR REPLACE INTO ingest_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [source, source_release, artifact.name, sha256_file(artifact), artifact.stat().st_size,
         rows_loaded, schema_fingerprint, loader_version, utc_now()],
    )


def export_parquet(con: duckdb.DuckDBPyConnection, out_dir: str = "data/parquet") -> list[Path]:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for table in CONTRACT_TABLES:
        if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()[0]:
            path = target / f"{table}.parquet"
            sql_path = "'" + str(path).replace("'", "''") + "'"
            con.execute(f"COPY {table} TO {sql_path} (FORMAT PARQUET, COMPRESSION ZSTD)")
            written.append(path)
    return written

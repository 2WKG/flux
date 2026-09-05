"""Texas P0 DuckDB schema, provenance logging, and Parquet hand-off helpers.

This module owns the legacy Texas ingestion store.  It is deliberately kept
separate from ``pipelines.db``, whose schema is the shared product contract.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from pipelines.common import sha256_file, utc_now

TEXAS_DB_PATH = "data/duck/texas.duckdb"
TEXAS_PARQUET_DIR = "data/parquet/texas"

CONTRACT_TABLES = (
    "buses", "lines", "gens", "loads", "counties", "critical_loads",
    "eaglei_outages", "weather_hourly", "storm_events", "hazard_static",
    "ba_load_hourly", "site_candidates", "scenarios",
)

DDL = """
CREATE TABLE IF NOT EXISTS buses(bus_id INTEGER PRIMARY KEY, name TEXT, base_kv DOUBLE,
  lon DOUBLE, lat DOUBLE, county_fips TEXT, ba_code TEXT, coord_source TEXT, zone INTEGER, area INTEGER);
CREATE TABLE IF NOT EXISTS lines(line_id INTEGER PRIMARY KEY, from_bus INTEGER, to_bus INTEGER,
  base_kv DOUBLE, r_pu DOUBLE, x_pu DOUBLE, rate_a_mw DOUBLE, length_km DOUBLE, geom_wkb BLOB,
  is_transformer BOOLEAN);
CREATE TABLE IF NOT EXISTS gens(gen_id INTEGER PRIMARY KEY, bus_id INTEGER, fuel TEXT,
  pmax_mw DOUBLE, eia_plant_id INTEGER);
CREATE TABLE IF NOT EXISTS loads(load_id INTEGER PRIMARY KEY, bus_id INTEGER, p_mw_nominal DOUBLE);
CREATE TABLE IF NOT EXISTS counties(county_fips TEXT PRIMARY KEY, name TEXT, state TEXT,
  pop INTEGER, geom_wkb BLOB);
CREATE TABLE IF NOT EXISTS critical_loads(cl_id INTEGER PRIMARY KEY, kind TEXT, name TEXT,
  lon DOUBLE, lat DOUBLE, bus_id INTEGER, county_fips TEXT);
CREATE TABLE IF NOT EXISTS eaglei_outages(county_fips TEXT, ts TIMESTAMP, customers_out INTEGER,
  PRIMARY KEY(county_fips, ts));
CREATE TABLE IF NOT EXISTS weather_hourly(county_fips TEXT, ts TIMESTAMP, wind_ms DOUBLE,
  gust_ms DOUBLE, temp_c DOUBLE, ice_mm DOUBLE, precip_mm DOUBLE,
  PRIMARY KEY(county_fips, ts));
CREATE TABLE IF NOT EXISTS storm_events(event_id BIGINT, ts_begin TIMESTAMP, ts_end TIMESTAMP,
  county_fips TEXT, type TEXT, magnitude DOUBLE);
CREATE TABLE IF NOT EXISTS hazard_static(county_fips TEXT PRIMARY KEY, nri_score DOUBLE,
  wildfire_hazard DOUBLE, seismic_pga DOUBLE);
CREATE TABLE IF NOT EXISTS ba_load_hourly(ba_code TEXT, ts TIMESTAMP, demand_mw DOUBLE,
  PRIMARY KEY(ba_code, ts));
CREATE TABLE IF NOT EXISTS site_candidates(site_id INTEGER PRIMARY KEY, name TEXT, kind TEXT,
  lon DOUBLE, lat DOUBLE, county_fips TEXT, bus_id INTEGER, capacity_slot_mw DOUBLE);
CREATE TABLE IF NOT EXISTS scenarios(scenario_id TEXT PRIMARY KEY, name TEXT, kind TEXT,
  ts_start TIMESTAMP, ts_end TIMESTAMP);

CREATE TABLE IF NOT EXISTS ingest_log(source TEXT, source_release TEXT, source_file TEXT,
  sha256 TEXT, bytes BIGINT, rows_loaded BIGINT, schema_fingerprint TEXT, loader_version TEXT,
  loaded_at TIMESTAMP, PRIMARY KEY(source, source_release, source_file, sha256));
CREATE TABLE IF NOT EXISTS ingest_warnings(source TEXT, source_key TEXT, warning TEXT,
  created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS synthetic_substations(sub_num INTEGER PRIMARY KEY, sub_name TEXT,
  sub_id TEXT, lon DOUBLE, lat DOUBLE);
CREATE TABLE IF NOT EXISTS synthetic_bus_electrical(bus_id INTEGER PRIMARY KEY, bus_type INTEGER,
  pd_mw DOUBLE, qd_mvar DOUBLE, gs_mw DOUBLE, bs_mvar DOUBLE, vm_pu DOUBLE, va_deg DOUBLE,
  vmin_pu DOUBLE, vmax_pu DOUBLE);
CREATE TABLE IF NOT EXISTS synthetic_branch_electrical(line_id INTEGER PRIMARY KEY, b_pu DOUBLE,
  tap_ratio DOUBLE, shift_deg DOUBLE, status INTEGER);
CREATE TABLE IF NOT EXISTS synthetic_generator_electrical(gen_id INTEGER PRIMARY KEY, p_mw DOUBLE,
  q_mvar DOUBLE, qmax_mvar DOUBLE, qmin_mvar DOUBLE, pmin_mw DOUBLE, status INTEGER,
  generator_type TEXT);
CREATE TABLE IF NOT EXISTS county_geo_meta(county_fips TEXT, tiger_vintage TEXT, aland_m2 BIGINT,
  awater_m2 BIGINT, PRIMARY KEY(county_fips, tiger_vintage));
CREATE TABLE IF NOT EXISTS nri_hazards(county_fips TEXT, hazard_code TEXT, risk_score DOUBLE,
  risk_rating TEXT, eal_value DOUBLE, source_release TEXT,
  PRIMARY KEY(county_fips, hazard_code, source_release));
CREATE TABLE IF NOT EXISTS ba_operations_hourly(ba_code TEXT, ts TIMESTAMP, demand_raw_mw DOUBLE,
  demand_adjusted_mw DOUBLE, demand_imputed_mw DOUBLE, demand_forecast_mw DOUBLE,
  net_generation_mw DOUBLE, total_interchange_mw DOUBLE, valid_dibas_mw DOUBLE,
  PRIMARY KEY(ba_code, ts));
CREATE TABLE IF NOT EXISTS eaglei_outage_observations(county_fips TEXT, ts TIMESTAMP,
  customers_out INTEGER, source_year INTEGER, source_file TEXT, raw_timestamp TEXT,
  total_customers INTEGER, PRIMARY KEY(county_fips, ts, source_year));
CREATE TABLE IF NOT EXISTS county_customers(county_fips TEXT, source_year INTEGER,
  customers INTEGER, source TEXT, PRIMARY KEY(county_fips, source_year, source));
CREATE TABLE IF NOT EXISTS eaglei_coverage(source_year INTEGER, state TEXT, total_customers INTEGER,
  min_covered INTEGER, max_covered INTEGER, min_pct_covered DOUBLE, max_pct_covered DOUBLE,
  PRIMARY KEY(source_year, state));
CREATE TABLE IF NOT EXISTS eaglei_ingest_quality(source_year INTEGER PRIMARY KEY, source_file TEXT,
  source_timezone TEXT, raw_tx_rows BIGINT, valid_rows BIGINT, missing_customers BIGINT,
  negative_customers BIGINT, duplicate_keys BIGINT, source_counties INTEGER, loaded_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS eia_plants(plant_id_eia INTEGER PRIMARY KEY, plant_name TEXT, lon DOUBLE,
  lat DOUBLE, state TEXT, county_fips TEXT, capacity_mw DOUBLE, primary_fuel TEXT,
  retirement_year INTEGER, operational_status TEXT, report_date DATE);
CREATE TABLE IF NOT EXISTS eia_generator_inventory(plant_id_eia INTEGER, generator_id TEXT,
  report_date DATE, capacity_mw DOUBLE, prime_mover_code TEXT, energy_source_code_1 TEXT,
  fuel_type_code_pudl TEXT, operational_status TEXT, retirement_date DATE,
  planned_retirement_date DATE, PRIMARY KEY(plant_id_eia, generator_id, report_date));
"""


def connect(path: str | Path = TEXAS_DB_PATH, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    output = Path(path)
    if not read_only:
        output.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(output), read_only=read_only)
    if not read_only:
        ensure_schema(con)
    return con


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(DDL)


def replace_frame(con: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame, where: str = "TRUE") -> int:
    """Replace the selected logical slice using registered dataframe insertion."""
    con.execute(f"DELETE FROM {table} WHERE {where}")
    if frame.empty:
        return 0
    con.register("_incoming", frame)
    try:
        con.execute("INSERT INTO " + table + " BY NAME SELECT * FROM _incoming")
    finally:
        con.unregister("_incoming")
    return len(frame)


def log_artifact(
    con: duckdb.DuckDBPyConnection, *, source: str, source_release: str,
    path: str | Path, rows_loaded: int, schema_fingerprint: str, loader_version: str = "texas-p0-v1",
) -> None:
    artifact = Path(path)
    con.execute(
        """INSERT OR REPLACE INTO ingest_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [source, source_release, artifact.name, sha256_file(artifact), artifact.stat().st_size,
         rows_loaded, schema_fingerprint, loader_version, utc_now()],
    )


def export_parquet(con: duckdb.DuckDBPyConnection, out_dir: str | Path = TEXAS_PARQUET_DIR) -> list[Path]:
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

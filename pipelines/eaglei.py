"""Stream EAGLE-I county outages without loading national CSVs into pandas."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pipelines.common import fips5, utc_naive, utc_now
from pipelines.db import log_artifact, replace_frame


def load_county_customers(con, mcc_csv: str, source_year: int = 2022) -> int:
    path = Path(mcc_csv)
    raw = pd.read_csv(path, encoding="utf-8-sig", dtype="string")
    required = {"County_FIPS", "Customers"}
    if missing := required - set(raw.columns):
        raise ValueError(f"MCC.csv missing columns: {sorted(missing)}")
    frame = pd.DataFrame({
        "county_fips": raw["County_FIPS"].map(fips5), "source_year": source_year,
        "customers": pd.to_numeric(raw["Customers"], errors="coerce").astype("Int64"), "source": "mcc_2022",
    })
    frame = frame[frame.county_fips.str.startswith("48", na=False)]
    rows = replace_frame(con, "county_customers", frame, where="source = 'mcc_2022'")
    log_artifact(con, source="eaglei", source_release="mcc_2022", path=path, rows_loaded=rows,
                 schema_fingerprint="County_FIPS,Customers")
    return rows


def load_coverage_history(con, coverage_csv: str) -> int:
    path = Path(coverage_csv)
    raw = pd.read_csv(path)
    selected = raw[raw["state"].eq("TX")].copy()
    selected["source_year"] = pd.to_datetime(selected["year"], errors="coerce").dt.year
    frame = selected.rename(columns={"total_customers": "total_customers", "min_covered": "min_covered",
                                    "max_covered": "max_covered", "min_pct_covered": "min_pct_covered",
                                    "max_pct_covered": "max_pct_covered"})[
        ["source_year", "state", "total_customers", "min_covered", "max_covered", "min_pct_covered", "max_pct_covered"]
    ]
    rows = replace_frame(con, "eaglei_coverage", frame, where="state = 'TX'")
    log_artifact(con, source="eaglei", source_release="coverage_history", path=path, rows_loaded=rows,
                 schema_fingerprint="year,state,total_customers,min/max coverage")
    return rows


def load_eaglei(con, csv_path: str, year: int, source_tz: str | None) -> int:
    """Load a Texas EAGLE-I file after an explicit source-timezone decision.

    `source_tz` is intentionally mandatory: EAGLE-I timestamps arrive without a
    timezone, and an unrecorded assumption would shift Uri by six hours.
    """
    if source_tz is None:
        raise ValueError("EAGLE-I source_tz must be explicitly set after validation")
    path = Path(csv_path)
    # DuckDB projection/filter streams the national file and limits Python work to Texas rows.
    schema = con.execute("DESCRIBE SELECT * FROM read_csv_auto(?)", [str(path)]).fetchdf()
    total_customers = "TRY_CAST(total_customers AS BIGINT)" if "total_customers" in set(schema.column_name) else "NULL::BIGINT"
    query = f"""
        SELECT fips_code, county, state, customers_out, run_start_time,
               {total_customers} AS total_customers
        FROM read_csv_auto(?)
        WHERE state = 'Texas'
    """
    raw = con.execute(query, [str(path)]).fetchdf()
    expected = {"fips_code", "county", "state", "customers_out", "run_start_time"}
    if missing := expected - set(raw.columns):
        raise ValueError(f"{path.name} missing EAGLE-I columns: {sorted(missing)}")
    raw_rows = len(raw)
    customers_out = pd.to_numeric(raw["customers_out"], errors="coerce")
    missing_customers = int(customers_out.isna().sum())
    negative_customers = int((customers_out < 0).sum())
    if negative_customers:
        raise ValueError("EAGLE-I has negative customers_out values")
    # A blank target cannot be interpreted as either no outage or a zero count.
    # Exclude it from the curated target and retain the exact loss count below.
    raw = raw.loc[customers_out.notna()].copy()
    customers_out = customers_out.loc[customers_out.notna()].astype("Int64")
    timestamps = raw["run_start_time"].map(lambda value: utc_naive(value, source_tz))
    frame = pd.DataFrame({
        "county_fips": raw["fips_code"].map(fips5), "ts": timestamps,
        "customers_out": customers_out,
    })
    duplicate_keys = int(frame.duplicated(["county_fips", "ts"]).sum())
    if duplicate_keys:
        raise ValueError("EAGLE-I has duplicate county/timestamp observations")
    observation = frame.copy()
    observation["source_year"] = year
    observation["source_file"] = path.name
    observation["raw_timestamp"] = raw["run_start_time"].astype(str)
    observation["total_customers"] = raw["total_customers"].astype("Int64")
    replace_frame(con, "eaglei_outages", frame, where=f"EXTRACT(year FROM ts) = {year}", source_name="eaglei",
                  source_ref=path.name, source_version=str(year), fixture_batch_id=f"p0-eaglei-{year}")
    rows = replace_frame(con, "eaglei_outage_observations", observation, where=f"source_year = {year}")
    with_denominator = observation[observation.total_customers.notna()][["county_fips", "total_customers"]].drop_duplicates()
    if not with_denominator.empty:
        denominator = with_denominator.rename(columns={"total_customers": "customers"})
        denominator["source_year"] = year
        denominator["source"] = "eaglei_file"
        replace_frame(con, "county_customers", denominator,
                      where=f"source = 'eaglei_file' AND source_year = {year}")
    quality = pd.DataFrame([{
        "source_year": year, "source_file": path.name, "source_timezone": source_tz,
        "raw_tx_rows": raw_rows, "valid_rows": len(frame),
        "missing_customers": missing_customers, "negative_customers": negative_customers,
        "duplicate_keys": duplicate_keys, "source_counties": frame.county_fips.nunique(),
        "loaded_at": utc_now(),
    }])
    replace_frame(con, "eaglei_ingest_quality", quality, where=f"source_year = {year}")
    log_artifact(con, source="eaglei", source_release=str(year), path=path, rows_loaded=rows,
                 schema_fingerprint="fips_code,county,state,customers_out,run_start_time[,total_customers]; null targets excluded and counted")
    return rows

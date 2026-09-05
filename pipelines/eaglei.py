"""Stream EAGLE-I county outages without loading national CSVs into pandas."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pipelines.common import fips5, utc_now
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
    # DuckDB filters and converts the annual national CSV in-process.  Do not
    # materialize Texas' multi-million-row slice in pandas.
    schema = con.execute("DESCRIBE SELECT * FROM read_csv_auto(?)", [str(path)]).fetchall()
    columns = {row[0] for row in schema}
    expected = {"fips_code", "county", "state", "customers_out", "run_start_time"}
    if missing := expected - columns:
        raise ValueError(f"{path.name} missing EAGLE-I columns: {sorted(missing)}")
    total_customers = "TRY_CAST(total_customers AS BIGINT)" if "total_customers" in columns else "NULL::BIGINT"
    con.execute("DROP TABLE IF EXISTS _eaglei_tx")
    con.execute(
        f"""
        CREATE TEMP TABLE _eaglei_tx AS
        SELECT
            LPAD(CAST(TRY_CAST(fips_code AS BIGINT) AS VARCHAR), 5, '0') AS county_fips,
            timezone('UTC', timezone(?, try_strptime(CAST(run_start_time AS VARCHAR), '%Y-%m-%d %H:%M:%S'))) AS ts,
            TRY_CAST(customers_out AS BIGINT) AS customers_out,
            CAST(run_start_time AS VARCHAR) AS raw_timestamp,
            {total_customers} AS total_customers
        FROM read_csv_auto(?)
        WHERE state = 'Texas'
        """,
        [source_tz, str(path)],
    )
    raw_rows, missing_customers, negative_customers, invalid_timestamps, invalid_fips = con.execute(
        """SELECT count(*), count(*) FILTER (WHERE customers_out IS NULL),
                  count(*) FILTER (WHERE customers_out < 0), count(*) FILTER (WHERE ts IS NULL),
                  count(*) FILTER (WHERE county_fips IS NULL)
           FROM _eaglei_tx"""
    ).fetchone()
    if invalid_timestamps:
        raise ValueError("EAGLE-I has unparseable run_start_time values")
    if invalid_fips:
        raise ValueError("EAGLE-I has unparseable county FIPS values")
    if negative_customers:
        raise ValueError("EAGLE-I has negative customers_out values")
    # A blank target is unknown, never zero, and is excluded from the curated
    # target while its loss is recorded in the quality relation.
    duplicate_keys = con.execute(
        """SELECT COALESCE(sum(rows_at_key - 1), 0)
           FROM (SELECT count(*) AS rows_at_key FROM _eaglei_tx
                 WHERE customers_out IS NOT NULL GROUP BY county_fips, ts)"""
    ).fetchone()[0]
    if duplicate_keys:
        raise ValueError("EAGLE-I has duplicate county/timestamp observations")
    valid_rows, source_counties = con.execute(
        "SELECT count(*), count(DISTINCT county_fips) FROM _eaglei_tx WHERE customers_out IS NOT NULL"
    ).fetchone()
    # The source release, rather than the converted UTC timestamp, defines a
    # replaceable slice.  Uri rows can cross a UTC calendar-year boundary.
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            """DELETE FROM eaglei_outages AS outages
               WHERE EXISTS (SELECT 1 FROM eaglei_outage_observations AS observations
                             WHERE observations.source_year = ?
                               AND observations.county_fips = outages.county_fips
                               AND observations.ts = outages.ts)""",
            [year],
        )
        con.execute("DELETE FROM eaglei_outage_observations WHERE source_year = ?", [year])
        con.execute(
            """INSERT INTO eaglei_outage_observations
               (county_fips, ts, customers_out, source_year, source_file, raw_timestamp, total_customers)
               SELECT county_fips, ts, customers_out, ?, ?, raw_timestamp, total_customers
               FROM _eaglei_tx WHERE customers_out IS NOT NULL""",
            [year, path.name],
        )
        con.execute(
            """INSERT INTO eaglei_outages
               (county_fips, ts, customers_out, source_name, source_ref, source_version,
                source_retrieved_at, fixture_batch_id)
               SELECT county_fips, ts, customers_out, 'eaglei', ?, ?, NULL, ?
               FROM _eaglei_tx WHERE customers_out IS NOT NULL""",
            [path.name, str(year), f"p0-eaglei-{year}"],
        )
        con.execute("DELETE FROM county_customers WHERE source = 'eaglei_file' AND source_year = ?", [year])
        # Select the denominator from the latest actual source timestamp for
        # each county. Duplicate county/timestamp observations were rejected
        # above, so this is a stable one-row county/year/source replacement.
        con.execute(
            """INSERT INTO county_customers (county_fips, source_year, customers, source)
               SELECT county_fips, ?, total_customers, 'eaglei_file'
               FROM (
                   SELECT county_fips, total_customers,
                          row_number() OVER (PARTITION BY county_fips ORDER BY ts DESC, raw_timestamp DESC) AS ordinal
                   FROM _eaglei_tx
                   WHERE customers_out IS NOT NULL AND total_customers IS NOT NULL
               ) WHERE ordinal = 1""",
            [year],
        )
        con.execute("DELETE FROM eaglei_ingest_quality WHERE source_year = ?", [year])
        con.execute(
            """INSERT INTO eaglei_ingest_quality VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [year, path.name, source_tz, raw_rows, valid_rows, missing_customers,
             negative_customers, duplicate_keys, source_counties, utc_now()],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    rows = int(valid_rows)
    log_artifact(con, source="eaglei", source_release=str(year), path=path, rows_loaded=rows,
                 schema_fingerprint="fips_code,county,state,customers_out,run_start_time[,total_customers]; null targets excluded and counted")
    return rows

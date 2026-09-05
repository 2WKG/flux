"""Stream EAGLE-I county outages without loading national CSVs into pandas."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pipelines.common import fips5, utc_now
from pipelines.db import log_artifact, replace_frame
from pipelines.state_scope import StateScope, scope, sql_in


def load_county_customers(
    con, mcc_csv: str, source_year: int = 2022, states=None
) -> int:
    path = Path(mcc_csv)
    selected_scope = states if isinstance(states, StateScope) else scope(states)
    raw = pd.read_csv(path, encoding="utf-8-sig", dtype="string")
    required = {"County_FIPS", "Customers"}
    if missing := required - set(raw.columns):
        raise ValueError(f"MCC.csv missing columns: {sorted(missing)}")
    frame = pd.DataFrame(
        {
            "county_fips": raw["County_FIPS"].map(fips5),
            "source_year": source_year,
            "customers": pd.to_numeric(raw["Customers"], errors="coerce").astype(
                "Int64"
            ),
            "source": "mcc_2022",
        }
    )
    frame = frame[frame.county_fips.str[:2].isin(selected_scope.fips)]
    rows = replace_frame(
        con,
        "county_customers",
        frame,
        where=f"source = 'mcc_2022' AND source_year = {source_year} AND ({selected_scope.county_where()})",
    )
    log_artifact(
        con,
        source="eaglei",
        source_release="mcc_2022",
        path=path,
        rows_loaded=rows,
        scope_key=selected_scope.slug,
        schema_fingerprint="County_FIPS,Customers",
    )
    return rows


def load_coverage_history(con, coverage_csv: str, states=None) -> int:
    path = Path(coverage_csv)
    selected_scope = states if isinstance(states, StateScope) else scope(states)
    raw = pd.read_csv(path)
    selected = raw[
        raw["state"].isin(selected_scope.source_values("eaglei_coverage"))
    ].copy()
    selected["source_year"] = pd.to_datetime(selected["year"], errors="coerce").dt.year
    frame = selected.rename(
        columns={
            "total_customers": "total_customers",
            "min_covered": "min_covered",
            "max_covered": "max_covered",
            "min_pct_covered": "min_pct_covered",
            "max_pct_covered": "max_pct_covered",
        }
    )[
        [
            "source_year",
            "state",
            "total_customers",
            "min_covered",
            "max_covered",
            "min_pct_covered",
            "max_pct_covered",
        ]
    ]
    predicate, parameters = sql_in(
        "state", selected_scope.source_values("eaglei_coverage")
    )
    if (
        frame.source_year.isna().any()
        or frame.duplicated(["source_year", "state"]).any()
    ):
        raise ValueError("coverage history requires unique valid state/year rows")
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"DELETE FROM eaglei_coverage WHERE {predicate}", parameters)
        if not frame.empty:
            con.register("_coverage", frame)
            try:
                con.execute(
                    "INSERT INTO eaglei_coverage BY NAME SELECT * FROM _coverage"
                )
            finally:
                con.unregister("_coverage")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    rows = len(frame)
    log_artifact(
        con,
        source="eaglei",
        source_release="coverage_history",
        path=path,
        rows_loaded=rows,
        scope_key=selected_scope.slug,
        schema_fingerprint="year,state,total_customers,min/max coverage",
    )
    return rows


def load_eaglei(
    con, csv_path: str, year: int, source_tz: str | None, states=None
) -> int:
    """Load selected states after an explicit source-timezone decision.

    `source_tz` is intentionally mandatory: EAGLE-I timestamps arrive without a
    timezone, and an unrecorded assumption would shift Uri by six hours.
    """
    if source_tz is None:
        raise ValueError("EAGLE-I source_tz must be explicitly set after validation")
    path = Path(csv_path)
    selected_scope = states if isinstance(states, StateScope) else scope(states)
    scope_where = selected_scope.county_where()
    predicate, state_parameters = sql_in("state", selected_scope.names)
    # DuckDB filters and converts the annual national CSV in-process.  Do not
    # materialize a multi-million-row state slice in pandas.
    schema = con.execute(
        "DESCRIBE SELECT * FROM read_csv_auto(?)", [str(path)]
    ).fetchall()
    columns = {row[0] for row in schema}
    expected = {"fips_code", "county", "state", "customers_out", "run_start_time"}
    if missing := expected - columns:
        raise ValueError(f"{path.name} missing EAGLE-I columns: {sorted(missing)}")
    total_customers = (
        "TRY_CAST(total_customers AS BIGINT)"
        if "total_customers" in columns
        else "NULL::BIGINT"
    )
    con.execute("DROP TABLE IF EXISTS _eaglei_tx")
    con.execute(
        f"""
        CREATE TEMP TABLE _eaglei_tx AS
        SELECT
            CASE WHEN regexp_full_match(trim(CAST(fips_code AS VARCHAR)), '[0-9]{{1,5}}')
                 THEN LPAD(trim(CAST(fips_code AS VARCHAR)), 5, '0') END AS county_fips,
            CAST(state AS VARCHAR) AS source_state,
            timezone('UTC', timezone(?, try_strptime(CAST(run_start_time AS VARCHAR), '%Y-%m-%d %H:%M:%S'))) AS ts,
            TRY_CAST(customers_out AS BIGINT) AS customers_out,
            CAST(run_start_time AS VARCHAR) AS raw_timestamp,
            {total_customers} AS total_customers
        FROM read_csv_auto(?)
        WHERE {predicate}
        """,
        [source_tz, str(path), *state_parameters],
    )
    (
        _raw_rows,
        _missing_customers,
        negative_customers,
        invalid_timestamps,
        invalid_fips,
    ) = con.execute(
        """SELECT count(*), count(*) FILTER (WHERE customers_out IS NULL),
                  count(*) FILTER (WHERE customers_out < 0), count(*) FILTER (WHERE ts IS NULL),
                  count(*) FILTER (WHERE county_fips IS NULL)
           FROM _eaglei_tx"""
    ).fetchone()
    inconsistent = con.execute(
        f"SELECT count(*) FROM _eaglei_tx WHERE county_fips IS NOT NULL AND NOT ({scope_where})"
    ).fetchone()[0]
    for state in selected_scope.states:
        inconsistent += con.execute(
            "SELECT count(*) FROM _eaglei_tx WHERE source_state = ? AND substr(county_fips, 1, 2) != ?",
            [state.name, state.fips],
        ).fetchone()[0]
    if inconsistent:
        raise ValueError("EAGLE-I county FIPS does not match source state")
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
    valid_rows, _source_counties = con.execute(
        "SELECT count(*), count(DISTINCT county_fips) FROM _eaglei_tx WHERE customers_out IS NOT NULL"
    ).fetchone()
    # The source release, rather than the converted UTC timestamp, defines a
    # replaceable slice.  Uri rows can cross a UTC calendar-year boundary.
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            f"""DELETE FROM eaglei_outages AS outages
               WHERE ({selected_scope.county_where("outages.county_fips")}) AND EXISTS (SELECT 1 FROM eaglei_outage_observations AS observations
                             WHERE observations.source_year = ?
                               AND observations.county_fips = outages.county_fips
                               AND observations.ts = outages.ts)""",
            [year],
        )
        con.execute(
            f"DELETE FROM eaglei_outage_observations WHERE source_year = ? AND ({scope_where})",
            [year],
        )
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
            [path.name, str(year), f"p0-eaglei-{year}-{selected_scope.slug}"],
        )
        con.execute(
            f"DELETE FROM county_customers WHERE source = 'eaglei_file' AND source_year = ? AND ({scope_where})",
            [year],
        )
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
        for state in selected_scope.states:
            counts = con.execute(
                """SELECT count(*), count(*) FILTER (WHERE customers_out IS NOT NULL),
                          count(*) FILTER (WHERE customers_out IS NULL),
                          count(DISTINCT county_fips) FILTER (WHERE customers_out IS NOT NULL)
                   FROM _eaglei_tx WHERE source_state = ?""",
                [state.name],
            ).fetchone()
            state_raw, state_valid, state_missing, state_counties = counts
            con.execute(
                "DELETE FROM eaglei_ingest_quality_by_state WHERE source_year = ? AND state_fips = ?",
                [year, state.fips],
            )
            con.execute(
                """INSERT INTO eaglei_ingest_quality_by_state
                   (source_year, state_fips, source_file, source_timezone, raw_rows, valid_rows,
                    missing_customers, negative_customers, duplicate_keys, source_counties, loaded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    year,
                    state.fips,
                    path.name,
                    source_tz,
                    state_raw,
                    state_valid,
                    state_missing,
                    0,
                    0,
                    state_counties,
                    utc_now(),
                ],
            )
            # Keep the existing Texas quality relation compatible with its readers.
            if state.usps == "TX":
                con.execute(
                    "DELETE FROM eaglei_ingest_quality WHERE source_year = ?", [year]
                )
                con.execute(
                    """INSERT INTO eaglei_ingest_quality VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        year,
                        path.name,
                        source_tz,
                        state_raw,
                        state_valid,
                        state_missing,
                        0,
                        0,
                        state_counties,
                        utc_now(),
                    ],
                )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    rows = int(valid_rows)
    log_artifact(
        con,
        source="eaglei",
        source_release=str(year),
        path=path,
        rows_loaded=rows,
        scope_key=selected_scope.slug,
        schema_fingerprint="fips_code,county,state,customers_out,run_start_time[,total_customers]; null targets excluded and counted",
    )
    return rows

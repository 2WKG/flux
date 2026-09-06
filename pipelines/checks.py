"""High-signal quality gates for curated P0 data, scoped by state."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from pipelines.db import connect
from pipelines.state_scope import scope, StateScope


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


def run_checks(db_path: str, states=None) -> list[Check]:
    selected = scope(states)
    con = connect(db_path, read_only=True)
    try:
        buses = _scalar(con, "SELECT count(*) FROM buses")
        coord_missing = _scalar(con, "SELECT count(*) FROM buses WHERE source_name = 'activsg2000' AND (lon IS NULL OR lat IS NULL OR coord_source IS DISTINCT FROM 'tamu_aux')")
        branches = _scalar(con, "SELECT count(*) FROM lines WHERE source_name = 'activsg2000'")
        buses = _scalar(con, "SELECT count(*) FROM buses WHERE source_name = 'activsg2000'")
        loads = _scalar(con, "SELECT count(*) FROM loads WHERE source_name = 'activsg2000'")
        transformers = _scalar(con, "SELECT count(*) FROM lines WHERE source_name = 'activsg2000' AND is_transformer")
        counties = _scalar(con, "SELECT count(*) FROM counties")
        fips_bad = _scalar(con, "SELECT count(*) FROM counties WHERE length(county_fips) <> 5")
        fips_clause = selected.county_where()
        nri_rows = _scalar(con, f"SELECT count(*) FROM hazard_static WHERE {fips_clause}")
        nri_missing = _scalar(con, f"SELECT count(*) FROM hazard_static WHERE {fips_clause} AND nri_score IS NULL")
        eaglei_years = _scalar(con, "SELECT count(*) FROM eaglei_ingest_quality WHERE source_year IN (2021, 2024)")
        eaglei_bad = _scalar(con, "SELECT count(*) FROM eaglei_ingest_quality WHERE negative_customers <> 0 OR duplicate_keys <> 0")
        storm_rows = _scalar(con, "SELECT count(*) FROM storm_events")
        ba_rows = _scalar(con, "SELECT count(*) FROM ba_load_hourly")
        critical_bad = _scalar(con, "SELECT count(*) FROM critical_loads WHERE county_fips IS NULL")
        candidate_bad = _scalar(con, "SELECT count(*) FROM site_candidates WHERE county_fips IS NULL OR capacity_slot_mw <= 0")
        scope_label = selected.slug

        if selected.is_texas_only:
            checks = [
                Check("synthetic-case-counts", buses == 2000 and branches == 3206 and loads == 1125 and transformers == 847,
                      f"buses={buses}, branches={branches}, transformers={transformers}, loads={loads}"),
                Check("synthetic-coordinates", coord_missing == 0, f"invalid/missing AUX coordinates={coord_missing}"),
                Check("texas-counties", counties == 254 and fips_bad == 0, f"counties={counties}, invalid_fips={fips_bad}"),
                Check("fema-nri-texas", nri_rows == 254 and nri_missing == 0,
                      f"county rows={nri_rows}, missing composite score={nri_missing}"),
                Check("eaglei-target-quality", eaglei_years == 2 and eaglei_bad == 0,
                      f"loaded years={eaglei_years}, negative-or-duplicate releases={eaglei_bad}"),
                Check("loaded-p0-domains", storm_rows > 0 and ba_rows > 0 and critical_bad == 0 and candidate_bad == 0,
                      f"storm={storm_rows}, ba={ba_rows}, critical_invalid={critical_bad}, candidate_invalid={candidate_bad}"),
            ]
        else:
            checks = [
                Check("synthetic-topology-absent",
                      buses == 0, f"synthetic topology not supported for {scope_label}; buses={buses}"),
                Check("scope-counties",
                      counties > 0 and fips_bad == 0, f"counties={counties}, invalid_fips={fips_bad}"),
                Check("scope-nri", nri_rows > 0 and nri_missing < nri_rows,
                      f"county rows={nri_rows}, missing composite score={nri_missing}"),
                Check("eaglei-target-quality", eaglei_years == 2 and eaglei_bad == 0,
                      f"loaded years={eaglei_years}, negative-or-duplicate releases={eaglei_bad}"),
                Check("loaded-p0-domains", storm_rows > 0 and ba_rows > 0 and critical_bad == 0 and candidate_bad == 0,
                      f"storm={storm_rows}, ba={ba_rows}, critical_invalid={critical_bad}, candidate_invalid={candidate_bad}"),
            ]
        return checks
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/duck/grid.duckdb")
    parser.add_argument(
        "--states",
        action="append",
        help="USPS names/codes or comma-separated state scope",
    )
    args = parser.parse_args()
    checks = run_checks(args.db, args.states)
    for check in checks:
        print(f"{'PASS' if check.passed else 'FAIL'} {check.name}: {check.detail}")
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

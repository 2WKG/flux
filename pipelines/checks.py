"""High-signal quality gates for curated P0 data."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from pipelines.db import connect


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


def run_checks(db_path: str) -> list[Check]:
    con = connect(db_path, read_only=True)
    try:
        buses = _scalar(con, "SELECT count(*) FROM buses")
        coord_missing = _scalar(con, "SELECT count(*) FROM buses WHERE lon IS NULL OR lat IS NULL OR coord_source <> 'tamu_aux'")
        branches = _scalar(con, "SELECT count(*) FROM lines")
        loads = _scalar(con, "SELECT count(*) FROM loads")
        counties = _scalar(con, "SELECT count(*) FROM counties WHERE state = 'TX'")
        fips_bad = _scalar(con, "SELECT count(*) FROM counties WHERE length(county_fips) <> 5")
        nri_rows = _scalar(con, "SELECT count(*) FROM hazard_static WHERE county_fips LIKE '48%'")
        nri_missing = _scalar(con, "SELECT count(*) FROM hazard_static WHERE county_fips LIKE '48%' AND nri_score IS NULL")
        eaglei_years = _scalar(con, "SELECT count(*) FROM eaglei_ingest_quality WHERE source_year IN (2021, 2024)")
        eaglei_bad = _scalar(con, "SELECT count(*) FROM eaglei_ingest_quality WHERE negative_customers <> 0 OR duplicate_keys <> 0")
        return [
            Check("synthetic-case-counts", buses == 2000 and branches == 3206 and loads == 1125,
                  f"buses={buses}, branches={branches}, loads={loads}"),
            Check("synthetic-coordinates", coord_missing == 0, f"invalid/missing AUX coordinates={coord_missing}"),
            Check("texas-counties", counties == 254 and fips_bad == 0, f"counties={counties}, invalid_fips={fips_bad}"),
            Check("fema-nri-texas", nri_rows == 254 and nri_missing == 0,
                  f"county rows={nri_rows}, missing composite score={nri_missing}"),
            Check("eaglei-target-quality", eaglei_years == 2 and eaglei_bad == 0,
                  f"loaded years={eaglei_years}, negative-or-duplicate releases={eaglei_bad}"),
        ]
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/duck/grid.duckdb")
    args = parser.parse_args()
    checks = run_checks(args.db)
    for check in checks:
        print(f"{'PASS' if check.passed else 'FAIL'} {check.name}: {check.detail}")
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

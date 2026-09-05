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
        transformers = _scalar(con, "SELECT count(*) FROM lines WHERE is_transformer")
        gens = _scalar(con, "SELECT count(*) FROM gens")
        loads = _scalar(con, "SELECT count(*) FROM loads")
        counties = _scalar(con, "SELECT count(*) FROM counties WHERE state = 'TX'")
        fips_bad = _scalar(con, "SELECT count(*) FROM counties WHERE length(county_fips) <> 5")
        nri_rows = _scalar(con, "SELECT count(*) FROM hazard_static WHERE county_fips LIKE '48%'")
        nri_missing = _scalar(con, "SELECT count(*) FROM hazard_static WHERE county_fips LIKE '48%' AND nri_score IS NULL")
        eaglei_years = _scalar(con, "SELECT count(*) FROM eaglei_ingest_quality WHERE source_year IN (2021, 2024)")
        eaglei_bad = _scalar(con, "SELECT count(*) FROM eaglei_ingest_quality WHERE negative_customers <> 0 OR duplicate_keys <> 0")
        erco_hours = _scalar(con, """SELECT count(*) FROM ba_load_hourly
            WHERE ba_code = 'ERCO' AND ts >= TIMESTAMP '2021-01-01 07:00:00'
              AND ts < TIMESTAMP '2021-07-01 06:00:00'""")
        erco_invalid = _scalar(con, """SELECT count(*) FROM ba_load_hourly
            WHERE ba_code = 'ERCO' AND ts >= TIMESTAMP '2021-01-01 07:00:00'
              AND ts < TIMESTAMP '2021-07-01 06:00:00'
              AND (demand_mw IS NULL OR demand_mw <= 0)""")
        uri_before_shedding = _scalar(con, """SELECT count(*) FROM ba_load_hourly
            WHERE ba_code = 'ERCO' AND ts = TIMESTAMP '2021-02-14 18:00:00'
              AND demand_mw > 60000""")
        uri_shedding = _scalar(con, """SELECT count(*) FROM ba_load_hourly
            WHERE ba_code = 'ERCO' AND ts = TIMESTAMP '2021-02-15 18:00:00'
              AND demand_mw < 50000""")
        storm_winter_rows = _scalar(con, """SELECT count(*) FROM storm_events
            WHERE ts_begin >= TIMESTAMP '2021-02-01 00:00:00'
              AND ts_begin < TIMESTAMP '2021-03-01 00:00:00'
              AND type IN ('Winter Storm', 'Winter Weather', 'Ice Storm', 'Extreme Cold/Wind Chill')""")
        storm_invalid = _scalar(con, """SELECT count(*) FROM storm_events
            WHERE county_fips IS NULL OR length(county_fips) <> 5
               OR ts_begin IS NULL OR ts_end IS NULL OR ts_end < ts_begin""")
        dod_rows = _scalar(con, "SELECT count(*) FROM critical_loads WHERE kind = 'dod'")
        dod_unmatched = _scalar(con, """SELECT count(*) FROM critical_loads
            WHERE kind = 'dod' AND (county_fips IS NULL OR bus_id IS NULL)""")
        cavazos_matched = _scalar(con, """SELECT count(*) FROM critical_loads
            WHERE kind = 'dod' AND (name ILIKE '%Cavazos%' OR name ILIKE '%Hood%')
              AND bus_id IS NOT NULL""")
        candidate_coal = _scalar(con, """SELECT count(*) FROM site_candidates
            WHERE kind IN ('coal_retired', 'coal_retiring')""")
        candidate_nuclear = _scalar(con, "SELECT count(*) FROM site_candidates WHERE kind = 'nuclear_existing'")
        candidate_invalid = _scalar(con, """SELECT count(*) FROM site_candidates AS candidate
            LEFT JOIN buses AS bus ON bus.bus_id = candidate.bus_id
            WHERE candidate.kind IS NULL OR candidate.kind NOT IN ('coal_retired', 'coal_retiring', 'nuclear_existing')
               OR candidate.lon IS NULL OR candidate.lat IS NULL
               OR candidate.county_fips IS NULL OR candidate.bus_id IS NULL
               OR bus.bus_id IS NULL OR bus.base_kv < 230""")
        return [
            Check("synthetic-case-counts", buses == 2000 and branches == 3206 and transformers == 847
                  and gens == 544 and loads == 1125,
                  f"buses={buses}, branches={branches}, transformers={transformers}, gens={gens}, loads={loads}"),
            Check("synthetic-coordinates", coord_missing == 0, f"invalid/missing AUX coordinates={coord_missing}"),
            Check("texas-counties", counties == 254 and fips_bad == 0, f"counties={counties}, invalid_fips={fips_bad}"),
            Check("fema-nri-texas", nri_rows == 254 and nri_missing == 0,
                  f"county rows={nri_rows}, missing composite score={nri_missing}"),
            Check("eaglei-target-quality", eaglei_years == 2 and eaglei_bad == 0,
                  f"loaded years={eaglei_years}, negative-or-duplicate releases={eaglei_bad}"),
            Check("eia930-erco-uri", erco_hours == 4343 and erco_invalid == 0
                  and uri_before_shedding == 1 and uri_shedding == 1,
                  f"2021-H1 ERCO hours={erco_hours}, invalid={erco_invalid}, "
                  f"pre-shedding-anchor={uri_before_shedding}, shedding-anchor={uri_shedding}"),
            Check("storm-events-uri", storm_winter_rows >= 150 and storm_invalid == 0,
                  f"Feb-2021 winter rows={storm_winter_rows}, invalid rows={storm_invalid}"),
            Check("critical-loads-dod", dod_rows >= 12 and dod_unmatched == 0 and cavazos_matched >= 1,
                  f"DoD rows={dod_rows}, unmatched={dod_unmatched}, Cavazos/Hood matches={cavazos_matched}"),
            Check("site-candidates", candidate_coal >= 15 and candidate_nuclear >= 2 and candidate_invalid == 0,
                  f"coal={candidate_coal}, nuclear={candidate_nuclear}, invalid or unlinked={candidate_invalid}"),
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

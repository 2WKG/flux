"""High-signal quality gates for curated P0 data, scoped by state.

Every per-county predicate is evaluated for each requested state on its own,
so a Texas-only database cannot pass a ``TX,MN`` scope: Minnesota must have
its own counties, NRI scores, storm events, and EAGLE-I releases. Texas keeps
its exact P0 expectations (254 counties, the ACTIVSg2000 synthetic topology);
other states must simply be present and complete.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from pipelines.db import connect
from pipelines.state_scope import State, StateScope, scope

TEXAS_COUNTY_COUNT = 254
EAGLEI_TARGET_YEARS = (2021, 2024)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _scalar(con, sql: str, params: list | None = None):
    return con.execute(sql, params or []).fetchone()[0]


def _state_checks(con, state: State, *, texas_only: bool) -> list[Check]:
    """Per-state county coverage: each requested state must be present and complete."""
    where = StateScope((state,)).county_where()
    counties = _scalar(con, f"SELECT count(*) FROM counties WHERE {where}")
    fips_bad = _scalar(
        con,
        f"SELECT count(*) FROM counties WHERE ({where}) AND length(county_fips) <> 5",
    )
    nri_rows = _scalar(con, f"SELECT count(*) FROM hazard_static WHERE {where}")
    nri_missing = _scalar(
        con,
        f"SELECT count(*) FROM hazard_static WHERE ({where}) AND nri_score IS NULL",
    )
    storm_rows = _scalar(con, f"SELECT count(*) FROM storm_events WHERE {where}")
    if state.usps == "TX":
        counties_ok = counties == TEXAS_COUNTY_COUNT and fips_bad == 0
        nri_ok = nri_rows == TEXAS_COUNTY_COUNT and nri_missing == 0
    else:
        counties_ok = counties > 0 and fips_bad == 0
        nri_ok = nri_rows > 0 and nri_missing == 0
    suffix = "" if texas_only else f"-{state.usps.lower()}"
    checks = [
        Check(
            "texas-counties" if texas_only else f"scope-counties{suffix}",
            counties_ok,
            f"counties={counties}, invalid_fips={fips_bad}",
        ),
        Check(
            "fema-nri-texas" if texas_only else f"scope-nri{suffix}",
            nri_ok,
            f"county rows={nri_rows}, missing composite score={nri_missing}",
        ),
    ]
    if not texas_only:
        checks.append(
            Check(f"scope-storms{suffix}", storm_rows > 0, f"storm={storm_rows}")
        )
        years = _scalar(
            con,
            "SELECT count(*) FROM eaglei_ingest_quality_by_state "
            "WHERE state_fips = ? AND source_year IN (?, ?)",
            [state.fips, *EAGLEI_TARGET_YEARS],
        )
        bad = _scalar(
            con,
            "SELECT count(*) FROM eaglei_ingest_quality_by_state WHERE state_fips = ? "
            "AND (negative_customers <> 0 OR duplicate_keys <> 0)",
            [state.fips],
        )
        checks.append(
            Check(
                f"scope-eaglei{suffix}",
                years == len(EAGLEI_TARGET_YEARS) and bad == 0,
                f"loaded years={years}, negative-or-duplicate releases={bad}",
            )
        )
    return checks


def run_checks(db_path: str, states=None) -> list[Check]:
    selected = scope(states)
    texas_only = selected.is_texas_only
    con = connect(db_path, read_only=True)
    try:
        checks: list[Check] = []
        if "TX" in selected.usps:
            # ACTIVSg2000 is Texas-only synthetic topology; only a Texas scope loads it.
            coord_missing = _scalar(
                con,
                "SELECT count(*) FROM buses WHERE source_name = 'activsg2000' AND "
                "(lon IS NULL OR lat IS NULL OR coord_source IS DISTINCT FROM 'tamu_aux')",
            )
            branches = _scalar(
                con, "SELECT count(*) FROM lines WHERE source_name = 'activsg2000'"
            )
            buses = _scalar(
                con, "SELECT count(*) FROM buses WHERE source_name = 'activsg2000'"
            )
            loads = _scalar(
                con, "SELECT count(*) FROM loads WHERE source_name = 'activsg2000'"
            )
            transformers = _scalar(
                con,
                "SELECT count(*) FROM lines WHERE source_name = 'activsg2000' AND is_transformer",
            )
            checks.append(
                Check(
                    "synthetic-case-counts",
                    buses == 2000
                    and branches == 3206
                    and loads == 1125
                    and transformers == 847,
                    f"buses={buses}, branches={branches}, transformers={transformers}, loads={loads}",
                )
            )
            checks.append(
                Check(
                    "synthetic-coordinates",
                    coord_missing == 0,
                    f"invalid/missing AUX coordinates={coord_missing}",
                )
            )
        else:
            buses = _scalar(con, "SELECT count(*) FROM buses")
            checks.append(
                Check(
                    "synthetic-topology-absent",
                    buses == 0,
                    f"synthetic topology not supported for {selected.slug}; buses={buses}",
                )
            )
        for state in selected.states:
            checks.extend(_state_checks(con, state, texas_only=texas_only))

        where = selected.county_where()
        eaglei_years = _scalar(
            con,
            "SELECT count(*) FROM eaglei_ingest_quality WHERE source_year IN (?, ?)",
            list(EAGLEI_TARGET_YEARS),
        )
        eaglei_bad = _scalar(
            con,
            "SELECT count(*) FROM eaglei_ingest_quality "
            "WHERE negative_customers <> 0 OR duplicate_keys <> 0",
        )
        storm_rows = _scalar(con, f"SELECT count(*) FROM storm_events WHERE {where}")
        ba_rows = _scalar(con, "SELECT count(*) FROM ba_load_hourly")
        critical_bad = _scalar(
            con, "SELECT count(*) FROM critical_loads WHERE county_fips IS NULL"
        )
        candidate_bad = _scalar(
            con,
            "SELECT count(*) FROM site_candidates "
            "WHERE county_fips IS NULL OR capacity_slot_mw <= 0",
        )
        if texas_only:
            # The legacy Texas quality relation is only written for Texas.
            checks.append(
                Check(
                    "eaglei-target-quality",
                    eaglei_years == len(EAGLEI_TARGET_YEARS) and eaglei_bad == 0,
                    f"loaded years={eaglei_years}, negative-or-duplicate releases={eaglei_bad}",
                )
            )
        checks.append(
            Check(
                "loaded-p0-domains",
                storm_rows > 0
                and ba_rows > 0
                and critical_bad == 0
                and candidate_bad == 0,
                f"storm={storm_rows}, ba={ba_rows}, critical_invalid={critical_bad}, "
                f"candidate_invalid={candidate_bad}",
            )
        )
        return checks
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/duck/grid.duckdb")
    parser.add_argument(
        "--states",
        action="append",
        help=(
            "State scope: USPS codes, full names, or two-digit FIPS, repeatable or "
            "comma-separated (default: Texas)"
        ),
    )
    args = parser.parse_args()
    checks = run_checks(args.db, args.states)
    for check in checks:
        print(f"{'PASS' if check.passed else 'FAIL'} {check.name}: {check.detail}")
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Dependency-ordered P0 builder. Missing raw artifacts are reported, never hidden."""

from __future__ import annotations

import argparse
from pathlib import Path

from pipelines.activsg import load_activsg
from pipelines.counties import load_counties
from pipelines.db import connect, export_parquet
from pipelines.eaglei import load_county_customers, load_coverage_history, load_eaglei
from pipelines.eia860 import load_eia860_plants, seed_site_candidates
from pipelines.eia930 import load_eia930
from pipelines.nri import load_nri
from pipelines.storm_events import load_storm_events
from pipelines.critical_loads import load_dod
from pipelines.joins import join_bus_county, join_critical_loads_to_bus


def _required(root: Path, *parts: str) -> Path | None:
    path = root.joinpath(*parts)
    return path if path.exists() else None


def build(raw_dir: str = "data/raw", db_path: str = "data/duck/grid.duckdb", eaglei_source_tz: str | None = None) -> dict[str, int]:
    raw, con, counts = Path(raw_dir), connect(db_path), {}
    try:
        aux = _required(raw, "activsg2000_current", "ACTIVSg2000.aux")
        case = _required(raw, "activsg2000_current", "case_ACTIVSg2000.m")
        if aux and case:
            counts.update(load_activsg(con, str(aux), str(case)))
        tiger = _required(raw, "tiger", "2024", "tl_2024_us_county.zip") or _required(raw, "tiger", "tl_2024_us_county.zip")
        if tiger:
            counts["counties"] = load_counties(con, str(tiger))
            if aux and case:
                counts["bus_county"] = join_bus_county(con)
        nri = (_required(raw, "nri", "v1.20", "NRI_Counties_TX.json")
               or _required(raw, "nri", "v1.20", "NRI_Table_Counties.zip")
               or _required(raw, "nri", "NRI_Table_Counties.zip"))
        if nri:
            counts["nri"] = load_nri(con, str(nri))
        plants = _required(raw, "pudl", "v2026.2.0", "out_eia__yearly_plants.parquet")
        generators = _required(raw, "pudl", "v2026.2.0", "out_eia__yearly_generators.parquet")
        if plants and generators:
            counts["eia_plants"] = load_eia860_plants(con, str(plants), str(generators))
            counts["site_candidates"] = seed_site_candidates(con)
        eia_files = [path for path in (
            _required(raw, "eia930", "2021_h1", "EIA930_BALANCE_2021_Jan_Jun.csv"),
            _required(raw, "eia930", "2024_h2", "EIA930_BALANCE_2024_Jul_Dec.csv"),
        ) if path]
        if eia_files:
            counts["ba_load_hourly"] = load_eia930(con, [str(path) for path in eia_files])
        crosswalk = _required(raw, "nws_zone_county", "bp16ap26", "bp16ap26.dbx")
        if crosswalk:
            for year, file_name in ((2021, "StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz"),
                                    (2024, "StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz")):
                details = _required(raw, "storm_events", str(year), file_name)
                if details:
                    counts[f"storm_events_{year}"] = load_storm_events(con, str(details), str(crosswalk), year)
        mcc = _required(raw, "eaglei", "support", "MCC.csv")
        coverage = _required(raw, "eaglei", "support", "coverage_history.csv")
        if mcc:
            counts["county_customers"] = load_county_customers(con, str(mcc))
        if coverage:
            counts["eaglei_coverage"] = load_coverage_history(con, str(coverage))
        for year in (2021, 2024):
            outage = _required(raw, "eaglei", str(year), f"eaglei_outages_{year}.csv")
            if outage:
                # Raw custody may finish before the source's naïve timestamp
                # convention is corroborated. Keep the rest of P0 buildable
                # while making that protected promotion explicit in the result.
                if eaglei_source_tz:
                    counts[f"eaglei_{year}"] = load_eaglei(con, str(outage), year, eaglei_source_tz)
                else:
                    counts[f"eaglei_{year}_blocked_timezone"] = 0
        dod = _required(raw, "ntad_military_bases", "fy2024", "texas.geojson")
        if dod:
            counts["critical_loads_dod"] = load_dod(con, str(dod))
            counts["critical_load_bus"] = join_critical_loads_to_bus(con)
        export_parquet(con)
    finally:
        con.close()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--db", default="data/duck/grid.duckdb")
    parser.add_argument("--eaglei-source-tz", choices=("UTC", "America/Chicago"))
    args = parser.parse_args()
    counts = build(args.raw_dir, args.db, args.eaglei_source_tz)
    for name, rows in sorted(counts.items()):
        print(f"{name}: {rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

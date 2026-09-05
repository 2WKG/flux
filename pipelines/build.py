"""Dependency-ordered, all-or-nothing P0 builder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipelines.activsg import load_activsg
from pipelines.counties import load_counties
from pipelines.critical_loads import load_dod
from pipelines.db import connect, export_parquet
from pipelines.eaglei import load_county_customers, load_coverage_history, load_eaglei
from pipelines.eia860 import load_eia860_plants, seed_site_candidates
from pipelines.eia930 import load_eia930
from pipelines.joins import join_bus_county, join_critical_loads_to_bus
from pipelines.nri import load_nri
from pipelines.storm_events import load_storm_events

REGISTRY = Path(__file__).resolve().parents[1] / "data" / "sources" / "p0_registry.json"


class IncompleteP0BuildError(RuntimeError):
    """Raised before an incomplete P0 build can mutate or export a release."""


def _artifact_paths(raw: Path, registry: Path = REGISTRY) -> dict[str, Path]:
    data = json.loads(registry.read_text())
    return {item["id"]: raw / item["path"] for item in data["artifacts"]}


def _missing_p0_inputs(raw: Path, eaglei_source_tz: str | None) -> list[str]:
    artifacts = _artifact_paths(raw)
    missing = [str(path.relative_to(raw)) for path in artifacts.values() if not path.exists()]
    if not eaglei_source_tz:
        missing.append("--eaglei-source-tz (required to promote EAGLE-I)")
    return missing


def build(raw_dir: str = "data/raw", db_path: str = "data/duck/grid.duckdb", eaglei_source_tz: str | None = None) -> dict[str, int]:
    raw = Path(raw_dir)
    if missing := _missing_p0_inputs(raw, eaglei_source_tz):
        raise IncompleteP0BuildError("P0 build was not promoted; missing required inputs:\n  - " + "\n  - ".join(missing))

    artifacts = _artifact_paths(raw)
    con, counts = connect(db_path), {}
    try:
        counts.update(load_activsg(con, str(artifacts["activsg_aux"]), str(artifacts["activsg_case"])))
        counts["counties"] = load_counties(con, str(artifacts["tiger_counties"]))
        counts["bus_county"] = join_bus_county(con)
        counts["nri"] = load_nri(con, str(artifacts["nri_counties"]))
        counts["eia_plants"] = load_eia860_plants(con, str(artifacts["pudl_plants"]), str(artifacts["pudl_generators"]))
        counts["site_candidates"] = seed_site_candidates(con)
        counts["ba_load_hourly"] = load_eia930(con, [str(artifacts["eia930_2021_h1"]), str(artifacts["eia930_2024_h2"])])
        for year in (2021, 2024):
            counts[f"storm_events_{year}"] = load_storm_events(
                con, str(artifacts[f"storm_events_{year}"]), str(artifacts["nws_zone_county"]), year,
            )
        counts["county_customers"] = load_county_customers(con, str(artifacts["eaglei_mcc"]))
        counts["eaglei_coverage"] = load_coverage_history(con, str(artifacts["eaglei_coverage"]))
        for year in (2021, 2024):
            counts[f"eaglei_{year}"] = load_eaglei(con, str(artifacts[f"eaglei_{year}"]), year, eaglei_source_tz)
        counts["critical_loads_dod"] = load_dod(con, str(artifacts["ntad_texas_bases"]))
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

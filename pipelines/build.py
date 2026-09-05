"""Dependency-ordered P0 builder. Missing raw artifacts are reported, never hidden."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import duckdb

from pipelines.activsg import load_activsg
from pipelines.checks import run_checks
from pipelines.common import sha256_file
from pipelines.counties import load_counties
from pipelines.critical_loads import load_dod
from pipelines.db import connect, export_parquet, validate_schema
from pipelines.eaglei import load_county_customers, load_coverage_history, load_eaglei
from pipelines.eia860 import load_eia860_plants, seed_site_candidates
from pipelines.eia930 import load_eia930
from pipelines.joins import join_bus_county, join_critical_loads_to_bus
from pipelines.nri import load_nri
from pipelines.storm_events import load_storm_events


class IncompleteP0BuildError(RuntimeError):
    """Raised before a partial P0 build can mutate or export the curated release."""


def _required(root: Path, *parts: str) -> Path | None:
    path = root.joinpath(*parts)
    return path if path.exists() else None


def _missing_p0_inputs(raw: Path, eaglei_source_tz: str | None) -> list[str]:
    """Return P0 inputs handled by this builder that are absent or not promotable."""
    required: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
        ("activsg2000_current/ACTIVSg2000.aux", (("activsg2000_current", "ACTIVSg2000.aux"),)),
        ("activsg2000_current/case_ACTIVSg2000.m", (("activsg2000_current", "case_ACTIVSg2000.m"),)),
        ("tiger/2024/tl_2024_us_county.zip", (("tiger", "2024", "tl_2024_us_county.zip"), ("tiger", "tl_2024_us_county.zip"))),
        ("NRI v1.20 county data", (("nri", "v1.20", "NRI_Counties_TX.json"), ("nri", "v1.20", "NRI_Table_Counties.zip"), ("nri", "NRI_Table_Counties.zip"))),
        ("pudl/v2026.2.0/out_eia__yearly_plants.parquet", (("pudl", "v2026.2.0", "out_eia__yearly_plants.parquet"),)),
        ("pudl/v2026.2.0/out_eia__yearly_generators.parquet", (("pudl", "v2026.2.0", "out_eia__yearly_generators.parquet"),)),
        ("eia930/2021_h1/EIA930_BALANCE_2021_Jan_Jun.csv", (("eia930", "2021_h1", "EIA930_BALANCE_2021_Jan_Jun.csv"),)),
        ("eia930/2024_h2/EIA930_BALANCE_2024_Jul_Dec.csv", (("eia930", "2024_h2", "EIA930_BALANCE_2024_Jul_Dec.csv"),)),
        ("nws_zone_county/bp16ap26/bp16ap26.dbx", (("nws_zone_county", "bp16ap26", "bp16ap26.dbx"),)),
        ("storm_events/2021/StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz", (("storm_events", "2021", "StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz"),)),
        ("storm_events/2024/StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz", (("storm_events", "2024", "StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz"),)),
        ("eaglei/support/MCC.csv", (("eaglei", "support", "MCC.csv"),)),
        ("eaglei/support/coverage_history.csv", (("eaglei", "support", "coverage_history.csv"),)),
        ("eaglei/2021/eaglei_outages_2021.csv", (("eaglei", "2021", "eaglei_outages_2021.csv"),)),
        ("eaglei/2024/eaglei_outages_2024.csv", (("eaglei", "2024", "eaglei_outages_2024.csv"),)),
        ("ntad_military_bases/fy2024/texas.geojson", (("ntad_military_bases", "fy2024", "texas.geojson"),)),
    )
    missing = [label for label, alternatives in required if not any(raw.joinpath(*parts).exists() for parts in alternatives)]
    if not eaglei_source_tz:
        missing.append("--eaglei-source-tz (required to promote EAGLE-I)")
    return missing


def _verified_activsg_retrieval(aux: Path, case: Path) -> datetime | None:
    """Use the checked-in receipt only when it matches the exact raw inputs."""
    receipt = Path("data/sources/activsg2000.json")
    if not receipt.exists():
        return None
    metadata = json.loads(receipt.read_text())
    files = metadata.get("files", {})
    if (files.get(aux.name, {}).get("sha256") != sha256_file(aux)
            or files.get(case.name, {}).get("sha256") != sha256_file(case)):
        return None
    value = metadata.get("retrieved_at")
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else None


def _build_mutating(raw_dir: str, db_path: str, eaglei_source_tz: str | None, parquet_dir: str) -> dict[str, int]:
    raw = Path(raw_dir)
    if missing := _missing_p0_inputs(raw, eaglei_source_tz):
        formatted = "\n  - ".join(missing)
        raise IncompleteP0BuildError(
            "P0 build was not promoted; missing required inputs:\n  - " + formatted
        )

    con, counts = connect(db_path), {}
    try:
        aux = _required(raw, "activsg2000_current", "ACTIVSg2000.aux")
        case = _required(raw, "activsg2000_current", "case_ACTIVSg2000.m")
        assert aux and case
        counts.update(load_activsg(con, str(aux), str(case), source_retrieved_at=_verified_activsg_retrieval(aux, case)))
        nri = (_required(raw, "nri", "v1.20", "NRI_Counties_TX.json")
               or _required(raw, "nri", "v1.20", "NRI_Table_Counties.zip")
               or _required(raw, "nri", "NRI_Table_Counties.zip"))
        tiger = _required(raw, "tiger", "2024", "tl_2024_us_county.zip") or _required(raw, "tiger", "tl_2024_us_county.zip")
        assert tiger and nri
        counts["counties"] = load_counties(con, str(tiger), str(nri))
        counts["bus_county"] = join_bus_county(con)
        counts["nri"] = load_nri(con, str(nri))
        plants = _required(raw, "pudl", "v2026.2.0", "out_eia__yearly_plants.parquet")
        generators = _required(raw, "pudl", "v2026.2.0", "out_eia__yearly_generators.parquet")
        assert plants and generators
        counts["eia_plants"] = load_eia860_plants(con, str(plants), str(generators))
        counts["site_candidates"] = seed_site_candidates(con)
        eia_files = [
            _required(raw, "eia930", "2021_h1", "EIA930_BALANCE_2021_Jan_Jun.csv"),
            _required(raw, "eia930", "2024_h2", "EIA930_BALANCE_2024_Jul_Dec.csv"),
        ]
        assert all(eia_files)
        counts["ba_load_hourly"] = load_eia930(con, [str(path) for path in eia_files])
        crosswalk = _required(raw, "nws_zone_county", "bp16ap26", "bp16ap26.dbx")
        assert crosswalk
        for year, file_name in ((2021, "StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz"),
                                (2024, "StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz")):
            details = _required(raw, "storm_events", str(year), file_name)
            assert details
            counts[f"storm_events_{year}"] = load_storm_events(con, str(details), str(crosswalk), year)
        mcc = _required(raw, "eaglei", "support", "MCC.csv")
        coverage = _required(raw, "eaglei", "support", "coverage_history.csv")
        assert mcc and coverage
        counts["county_customers"] = load_county_customers(con, str(mcc))
        counts["eaglei_coverage"] = load_coverage_history(con, str(coverage))
        for year in (2021, 2024):
            outage = _required(raw, "eaglei", str(year), f"eaglei_outages_{year}.csv")
            assert outage and eaglei_source_tz
            counts[f"eaglei_{year}"] = load_eaglei(con, str(outage), year, eaglei_source_tz)
        dod = _required(raw, "ntad_military_bases", "fy2024", "texas.geojson")
        assert dod
        counts["critical_loads_dod"] = load_dod(con, str(dod))
        counts["critical_load_bus"] = join_critical_loads_to_bus(con)
        validate_schema(con)
        export_parquet(con, parquet_dir)
    finally:
        con.close()
    return counts


def _copy_database(source: Path, stage: Path) -> None:
    if not source.exists():
        connect(stage).close()
        return
    con = duckdb.connect()
    try:
        quote = lambda path: "'" + str(path).replace("'", "''") + "'"
        con.execute(f"ATTACH {quote(source)} AS live (READ_ONLY)")
        con.execute(f"ATTACH {quote(stage)} AS staged")
        con.execute("COPY FROM DATABASE live TO staged")
    finally:
        con.close()


def _promote(stage_db: Path, live_db: Path, stage_parquet: Path, live_parquet: Path, root: Path) -> None:
    old_db, old_parquet = root / "previous.duckdb", root / "previous-parquet"
    moved_db = moved_parquet = False
    try:
        if live_db.exists():
            os.replace(live_db, old_db)
        os.replace(stage_db, live_db); moved_db = True
        if live_parquet.exists():
            os.replace(live_parquet, old_parquet)
        os.replace(stage_parquet, live_parquet); moved_parquet = True
    except Exception:
        if moved_parquet and live_parquet.exists(): shutil.rmtree(live_parquet)
        if old_parquet.exists(): os.replace(old_parquet, live_parquet)
        if moved_db and live_db.exists(): live_db.unlink()
        if old_db.exists(): os.replace(old_db, live_db)
        raise
    finally:
        if old_db.exists(): old_db.unlink()
        if old_parquet.exists(): shutil.rmtree(old_parquet)


def build(raw_dir: str = "data/raw", db_path: str = "data/duck/grid.duckdb", eaglei_source_tz: str | None = None) -> dict[str, int]:
    raw, live_db = Path(raw_dir), Path(db_path)
    if missing := _missing_p0_inputs(raw, eaglei_source_tz):
        formatted = "\n  - ".join(missing)
        raise IncompleteP0BuildError("P0 build was not promoted; missing required inputs:\n  - " + formatted)
    live_db.parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f".{live_db.stem}-stage-", dir=live_db.parent))
    stage_db, live_parquet, stage_parquet = root / live_db.name, Path("data/parquet"), root / "parquet"
    try:
        _copy_database(live_db, stage_db)
        if live_parquet.exists(): shutil.copytree(live_parquet, stage_parquet)
        else: stage_parquet.mkdir()
        counts = _build_mutating(str(raw), str(stage_db), eaglei_source_tz, str(stage_parquet))
        checks = run_checks(str(stage_db))
        if not all(check.passed for check in checks):
            raise RuntimeError("staged P0 quality checks failed: " + "; ".join(check.name for check in checks if not check.passed))
        _promote(stage_db, live_db, stage_parquet, live_parquet, root)
        return counts
    finally:
        shutil.rmtree(root, ignore_errors=True)


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

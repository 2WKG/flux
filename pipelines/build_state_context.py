"""Build non-Texas public context in the shared database from local artifacts."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from pipelines.build import (
    PublicationRecoveryError,
    _copy_database,
    _nws_crosswalk_releases,
    _promote,
    _write_stage_manifest,
)
from pipelines.counties import load_counties
from pipelines.db import connect, export_parquet, validate_schema
from pipelines.eaglei import load_county_customers, load_coverage_history, load_eaglei
from pipelines.eia860 import load_eia860_plants
from pipelines.nri import load_nri
from pipelines.state_context import context_db_path
from pipelines.state_scope import scope
from pipelines.storm_events import load_storm_events


def _year_artifacts(values, option: str, parser) -> list[tuple[int, str]]:
    """Parse repeated YEAR=PATH options without inventing a default year."""
    artifacts = []
    for item in values or []:
        year, separator, path = item.partition("=")
        if (
            not separator
            or not year.isdigit()
            or not 1900 <= int(year) <= 2100
            or not path
        ):
            parser.error(f"{option} requires YEAR=PATH with a valid four-digit year")
        artifacts.append((int(year), path))
    return artifacts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", action="append", required=True)
    parser.add_argument("--db-root", default="data/duck")
    parser.add_argument("--parquet-dir", default="data/parquet")
    parser.add_argument("--tiger")
    parser.add_argument("--nri")
    parser.add_argument("--eaglei", action="append", metavar="YEAR=PATH")
    parser.add_argument("--eaglei-source-tz", choices=("UTC", "America/Chicago"))
    parser.add_argument("--mcc", help="EAGLE-I MCC.csv customer denominators")
    parser.add_argument("--coverage", help="EAGLE-I coverage_history.csv")
    parser.add_argument("--storm-events", action="append", metavar="YEAR=PATH")
    parser.add_argument("--pudl-plants", help="PUDL out_eia__yearly_plants.parquet")
    parser.add_argument(
        "--pudl-generators", help="PUDL out_eia__yearly_generators.parquet"
    )
    parser.add_argument("--pudl-release", default="v2026.2.0")
    parser.add_argument(
        "--raw-dir",
        default="data/raw",
        help="root holding the catalog-pinned NWS crosswalk releases",
    )
    args = parser.parse_args(argv)
    try:
        selected = scope(args.state)
    except ValueError as error:
        parser.error(str(error))
    if selected.is_texas_only:
        parser.error("Texas P0 uses python -m pipelines.build")
    if not any(
        (
            args.tiger,
            args.nri,
            args.eaglei,
            args.mcc,
            args.coverage,
            args.storm_events,
            args.pudl_plants,
        )
    ):
        parser.error("supply explicit local artifacts; no implicit downloads")
    if bool(args.tiger) != bool(args.nri):
        parser.error("--tiger and --nri are required together")
    if bool(args.pudl_plants) != bool(args.pudl_generators):
        parser.error("--pudl-plants and --pudl-generators are required together")
    if args.eaglei and not args.eaglei_source_tz:
        parser.error("--eaglei-source-tz is required with --eaglei")
    artifacts = _year_artifacts(args.eaglei, "--eaglei", parser)
    storm_artifacts = _year_artifacts(args.storm_events, "--storm-events", parser)
    for path in [
        args.tiger,
        args.nri,
        args.mcc,
        args.coverage,
        args.pudl_plants,
        args.pudl_generators,
        *(path for _, path in artifacts),
        *(path for _, path in storm_artifacts),
    ]:
        if path and not Path(path).is_file():
            parser.error(f"artifact does not exist: {path}")
    # Storm Events zone rows expand through source-pinned NWS editions. Reading
    # them before staging keeps a missing or altered crosswalk from touching the
    # live release.
    crosswalk_releases = ()
    if storm_artifacts:
        try:
            crosswalk_releases = _nws_crosswalk_releases(Path(args.raw_dir))
        except RuntimeError as error:
            parser.error(str(error))
    live_db = context_db_path(selected, args.db_root)
    live_db.parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=".context-stage-", dir=live_db.parent))
    stage_db, stage_parquet = root / "grid.duckdb", root / "parquet"
    live_parquet = Path(args.parquet_dir)
    live_parquet.parent.mkdir(parents=True, exist_ok=True)
    retain_recovery = False
    try:
        _copy_database(live_db, stage_db)
        if live_parquet.exists():
            shutil.copytree(live_parquet, stage_parquet)
        else:
            stage_parquet.mkdir()
        con = connect(stage_db)
        try:
            county_dependent = [
                option
                for option, requested in (
                    ("--eaglei", artifacts),
                    ("--storm-events", storm_artifacts),
                    ("--mcc", args.mcc),
                    # PUDL plants derive county_fips with the canonical county
                    # geometry; without it, a context-only load would publish
                    # plants with silently missing county assignments.
                    ("--pudl-plants", args.pudl_plants),
                )
                if requested
            ]
            if county_dependent and not args.tiger:
                for state in selected.states:
                    if not con.execute(
                        "SELECT count(*) FROM counties WHERE substr(county_fips, 1, 2) = ?",
                        [state.fips],
                    ).fetchone()[0]:
                        parser.error(
                            f"{'/'.join(county_dependent)} requires loaded counties for "
                            f"{state.usps}; supply --tiger and --nri"
                        )
            if args.tiger:
                load_counties(con, args.tiger, args.nri, selected)
            if args.nri:
                load_nri(con, args.nri, states=selected)
            for year, path in storm_artifacts:
                load_storm_events(con, path, crosswalk_releases, year, selected)
            if args.pudl_plants:
                # Observed generation inventory only. `seed_site_candidates` is
                # deliberately not called: siting rides on the synthetic Texas
                # bus model, which no context state has.
                load_eia860_plants(
                    con,
                    args.pudl_plants,
                    args.pudl_generators,
                    args.pudl_release,
                    states=selected,
                )
            if args.mcc:
                load_county_customers(con, args.mcc, states=selected)
            if args.coverage:
                load_coverage_history(con, args.coverage, states=selected)
            for year, path in artifacts:
                load_eaglei(con, path, year, args.eaglei_source_tz, selected)
            validate_schema(con)
            export_parquet(con, stage_parquet)
        finally:
            con.close()
        # The staged database now contains both its previous scope and this
        # context state's rows. Rebuild the full-store manifest before the
        # database and Parquet directory are promoted together.
        _write_stage_manifest(stage_db, stage_parquet, selected)
        _promote(stage_db, live_db, stage_parquet, live_parquet, root)
    except PublicationRecoveryError:
        retain_recovery = True
        raise
    finally:
        if not retain_recovery:
            shutil.rmtree(root, ignore_errors=True)
    print(context_db_path(selected, args.db_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

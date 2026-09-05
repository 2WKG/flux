"""Build non-Texas public context in the shared database from local artifacts."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from pipelines.build import PublicationRecoveryError, _copy_database, _promote
from pipelines.counties import load_counties
from pipelines.db import connect, export_parquet, validate_schema
from pipelines.eaglei import load_eaglei
from pipelines.nri import load_nri
from pipelines.state_context import context_db_path
from pipelines.state_scope import scope


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", action="append", required=True)
    parser.add_argument("--db-root", default="data/duck")
    parser.add_argument("--parquet-dir", default="data/parquet")
    parser.add_argument("--tiger")
    parser.add_argument("--nri")
    parser.add_argument("--eaglei", action="append", metavar="YEAR=PATH")
    parser.add_argument("--eaglei-source-tz", choices=("UTC", "America/Chicago"))
    args = parser.parse_args(argv)
    try:
        selected = scope(args.state)
    except ValueError as error:
        parser.error(str(error))
    if selected.is_texas_only:
        parser.error("Texas P0 uses python -m pipelines.build")
    if not any((args.tiger, args.nri, args.eaglei)):
        parser.error("supply explicit local artifacts; no implicit downloads")
    if bool(args.tiger) != bool(args.nri):
        parser.error("--tiger and --nri are required together")
    if args.eaglei and not args.eaglei_source_tz:
        parser.error("--eaglei-source-tz is required with --eaglei")
    artifacts = []
    for item in args.eaglei or []:
        year, separator, path = item.partition("=")
        if (
            not separator
            or not year.isdigit()
            or not 1900 <= int(year) <= 2100
            or not path
        ):
            parser.error("--eaglei requires YEAR=PATH with a valid four-digit year")
        artifacts.append((int(year), path))
    for path in [args.tiger, args.nri, *(path for _, path in artifacts)]:
        if path and not Path(path).is_file():
            parser.error(f"artifact does not exist: {path}")
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
            if artifacts and not args.tiger:
                for state in selected.states:
                    if not con.execute(
                        "SELECT count(*) FROM counties WHERE substr(county_fips, 1, 2) = ?",
                        [state.fips],
                    ).fetchone()[0]:
                        parser.error(
                            f"--eaglei requires loaded counties for {state.usps}; supply --tiger and --nri"
                        )
            if args.tiger:
                load_counties(con, args.tiger, args.nri, selected)
            if args.nri:
                load_nri(con, args.nri, states=selected)
            for year, path in artifacts:
                load_eaglei(con, path, year, args.eaglei_source_tz, selected)
            validate_schema(con)
            export_parquet(con, stage_parquet)
        finally:
            con.close()
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

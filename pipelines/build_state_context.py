"""Build non-Texas public context in the shared database from local artifacts."""
from __future__ import annotations

import argparse
from pathlib import Path

from pipelines.counties import load_counties
from pipelines.eaglei import load_eaglei
from pipelines.nri import load_nri
from pipelines.state_context import connect_context, context_db_path
from pipelines.state_scope import scope


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", action="append", required=True)
    parser.add_argument("--db-root", default="data/duck")
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
        if not separator or not year.isdigit() or not 1900 <= int(year) <= 2100 or not path:
            parser.error("--eaglei requires YEAR=PATH with a valid four-digit year")
        artifacts.append((int(year), path))
    for path in [args.tiger, args.nri, *(path for _, path in artifacts)]:
        if path and not Path(path).is_file():
            parser.error(f"artifact does not exist: {path}")
    con = connect_context(selected, args.db_root)
    try:
        if artifacts and not args.tiger:
            for state in selected.states:
                if not con.execute("SELECT count(*) FROM counties WHERE substr(county_fips, 1, 2) = ?", [state.fips]).fetchone()[0]:
                    parser.error(f"--eaglei requires loaded counties for {state.usps}; supply --tiger and --nri")
        if args.tiger:
            load_counties(con, args.tiger, args.nri, selected)
        if args.nri:
            load_nri(con, args.nri, states=selected)
        for year, path in artifacts:
            load_eaglei(con, path, year, args.eaglei_source_tz, selected)
    finally:
        con.close()
    print(context_db_path(selected, args.db_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

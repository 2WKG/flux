"""Build a non-Texas public-data context store from explicit local artifacts."""
from __future__ import annotations
import argparse
from pipelines.counties import load_counties
from pipelines.eaglei import load_eaglei
from pipelines.nri import load_nri
from pipelines.state_context import connect_context, context_db_path
from pipelines.state_scope import scope

def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", action="append", required=True)
    parser.add_argument("--db-root", default="data/duck")
    parser.add_argument("--tiger"); parser.add_argument("--nri")
    parser.add_argument("--eaglei", action="append", metavar="YEAR=PATH")
    parser.add_argument("--eaglei-source-tz", choices=("UTC", "America/Chicago"))
    args = parser.parse_args(argv)
    selected = scope(args.state)
    if selected.is_texas_only: raise ValueError("Texas P0 uses python -m pipelines.build")
    if not any((args.tiger, args.nri, args.eaglei)): raise ValueError("supply explicit local artifacts; no implicit downloads")
    if bool(args.tiger) != bool(args.nri): raise ValueError("--tiger and --nri are required together")
    if args.eaglei and not args.eaglei_source_tz: raise ValueError("--eaglei-source-tz is required with --eaglei")
    con = connect_context(selected, args.db_root)
    try:
        if args.tiger: load_counties(con, args.tiger, args.nri, selected)
        if args.nri: load_nri(con, args.nri, states=selected)
        for item in args.eaglei or []:
            year, path = item.split("=", 1); load_eaglei(con, path, int(year), args.eaglei_source_tz, selected)
    finally: con.close()
    print(context_db_path(selected, args.db_root)); return 0
if __name__ == "__main__": raise SystemExit(main())

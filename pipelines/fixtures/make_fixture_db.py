"""CLI entry point for source-backed Minnesota fixture metadata."""

from __future__ import annotations

import argparse
from pathlib import Path

from .builder import main as build_fixture_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=Path("data/duck/grid.duckdb"))
    args = parser.parse_args(argv)
    return build_fixture_db(args.manifest, args.db)


if __name__ == "__main__":
    raise SystemExit(main())

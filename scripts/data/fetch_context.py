#!/usr/bin/env python3
"""Fetch small public context layers that have no stable bulk artifact URL."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipelines.state_scope import parse_states, scope


def dod_url(state: str) -> str:
    """Return the server-side NTAD query for one validated state."""
    return (
    "https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/"
    f"NTAD_Military_Bases/FeatureServer/0/query?where=stateNameCode%3D%27{state.lower()}%27&outFields=*"
    "&returnGeometry=true&outSR=4326&f=geojson"
    )


def save(url: str, path: Path, user_agent: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": user_agent})
    with urlopen(request, timeout=60) as response:
        path.write_bytes(response.read())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default="data/raw")
    state_args = parser.add_mutually_exclusive_group()
    state_args.add_argument(
        "--states", nargs="+", metavar="STATE",
        help="one or more postal abbreviations; commas are accepted (default: TX)",
    )
    state_args.add_argument("--state", action="append", help="USPS, full name, or two-digit FIPS; repeat or comma-separate")
    parser.add_argument("--dod", action="store_true")
    parser.add_argument("--nws-user-agent", help="required to fetch NWS alerts; include a real contact")
    args = parser.parse_args()
    root = Path(args.raw_dir)
    try:
        states = scope(args.state).usps if args.state else parse_states(args.states)
    except ValueError as error:
        parser.error(str(error))
    if args.dod:
        for state in states:
            path = root / "ntad_military_bases" / "fy2024" / f"{state}.geojson"
            save(dod_url(state), path, "flux-data-ingest/1.0")
            print(path)
    if args.nws_user_agent:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H0000Z")
        for state in states:
            path = root / "nws" / "alerts" / f"alerts_{state}_{stamp}.geojson"
            save(f"https://api.weather.gov/alerts/active?area={state}", path, args.nws_user_agent)
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

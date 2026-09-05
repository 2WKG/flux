#!/usr/bin/env python3
"""Fetch small public context layers that have no stable bulk artifact URL."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

DOD_URL = (
    "https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/"
    "NTAD_Military_Bases/FeatureServer/0/query?where=stateNameCode%3D%27tx%27&outFields=*"
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
    parser.add_argument("--dod", action="store_true")
    parser.add_argument("--nws-user-agent", help="required to fetch NWS alerts; include a real contact")
    args = parser.parse_args()
    root = Path(args.raw_dir)
    if args.dod:
        path = root / "ntad_military_bases" / "fy2024" / "texas.geojson"
        save(DOD_URL, path, "flux-data-ingest/1.0")
        print(path)
    if args.nws_user_agent:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H0000Z")
        path = root / "nws" / "alerts" / f"alerts_TX_{stamp}.geojson"
        save("https://api.weather.gov/alerts/active?area=TX", path, args.nws_user_agent)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

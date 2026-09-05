#!/usr/bin/env python3
"""Fetch small/medium P0 artifacts with checksummed, resumable raw landing zones.

Large EAGLE-I files require --include-large. This safety gate avoids accidental
multi-gigabyte downloads, while still making the full P0 pull one command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Artifact:
    source: str
    release: str
    name: str
    url: str
    large: bool = False


ARTIFACTS = (
    Artifact("tiger", "2024", "tl_2024_us_county.zip", "https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip"),
    # The public bulk ZIP is WAF-blocked in some automated environments.  This
    # is FEMA's official v1.20 feature service, narrowed to the 254 Texas
    # county records so we do not land a national dump merely to populate a
    # Texas-first model.
    Artifact("nri", "v1.20", "NRI_Counties_TX.json", "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Counties/FeatureServer/0/query?where=STATEABBRV%3D%27TX%27&outFields=*&returnGeometry=false&f=json"),
    Artifact("pudl", "v2026.2.0", "out_eia__yearly_plants.parquet", "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/v2026.2.0/out_eia__yearly_plants.parquet"),
    Artifact("pudl", "v2026.2.0", "out_eia__yearly_generators.parquet", "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/v2026.2.0/out_eia__yearly_generators.parquet"),
    Artifact("eia930", "2021_h1", "EIA930_BALANCE_2021_Jan_Jun.csv", "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2021_Jan_Jun.csv"),
    Artifact("eia930", "2024_h2", "EIA930_BALANCE_2024_Jul_Dec.csv", "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2024_Jul_Dec.csv"),
    Artifact("storm_events", "2021", "StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz", "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz"),
    Artifact("storm_events", "2024", "StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz", "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz"),
    Artifact("nws_zone_county", "bp16ap26", "bp16ap26.dbx", "https://www.weather.gov/source/gis/Shapefiles/County/bp16ap26.dbx"),
    Artifact("eaglei", "2021", "eaglei_outages_2021.csv", "https://ndownloader.figshare.com/files/42547891", large=True),
    Artifact("eaglei", "2024", "eaglei_outages_2024.csv", "https://ndownloader.figshare.com/files/53581661", large=True),
    Artifact("eaglei", "support", "MCC.csv", "https://ndownloader.figshare.com/files/42547708"),
    Artifact("eaglei", "support", "coverage_history.csv", "https://ndownloader.figshare.com/files/42547714"),
)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def download(artifact: Artifact, root: Path) -> dict[str, object]:
    directory = root / artifact.source / artifact.release
    directory.mkdir(parents=True, exist_ok=True)
    target, partial = directory / artifact.name, directory / f"{artifact.name}.part"
    if target.exists():
        return {**asdict(artifact), "path": str(target), "bytes": target.stat().st_size, "sha256": digest(target), "status": "existing"}
    start = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "flux-data-ingest/1.0"}
    if start:
        headers["Range"] = f"bytes={start}-"
    request = Request(artifact.url, headers=headers)
    with urlopen(request, timeout=60) as response:
        # Some publisher endpoints ignore Range while returning 200. Appending
        # that response produces a syntactically plausible but corrupted CSV.
        # Only append when the server explicitly confirms the requested range.
        content_range = response.headers.get("Content-Range", "")
        append = start > 0 and response.status == 206 and content_range.startswith(f"bytes {start}-")
        with partial.open("ab" if append else "wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
    partial.replace(target)
    return {**asdict(artifact), "path": str(target), "bytes": target.stat().st_size, "sha256": digest(target), "status": "downloaded"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--source", action="append", choices=sorted({item.source for item in ARTIFACTS}))
    parser.add_argument("--include-large", action="store_true")
    args = parser.parse_args()
    selected = [item for item in ARTIFACTS if (not args.source or item.source in args.source)]
    selected = [item for item in selected if args.include_large or not item.large]
    output = Path(args.raw_dir) / "fetch_manifest_p0.json"
    # Preserve prior source entries: a targeted rerun must not erase the
    # evidence record for artifacts fetched earlier in the same raw landing
    # zone.
    existing: dict[str, dict[str, object]] = {}
    if output.exists():
        try:
            existing = {str(item["path"]): item for item in json.loads(output.read_text())}
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    manifest = existing
    for artifact in selected:
        print(f"fetching {artifact.source}/{artifact.release}/{artifact.name}", file=sys.stderr)
        result = download(artifact, Path(args.raw_dir))
        manifest[str(result["path"])] = result
    output.write_text(json.dumps(sorted(manifest.values(), key=lambda item: str(item["path"])), indent=2) + "\n")
    print(f"wrote {output} ({len(manifest)} artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Derive the EAGLE-I source request frame from the canonical event bundles.

This is the committed successor to the throwaway `/tmp/flux-460-request-frame.py`
that produced `docs/data/event-baseline/requests.json`.  That script read three
absolute paths under `/private/tmp` and one loose git revision, so nobody but its
original worktree could regenerate or check its output.  This one reads only the
in-repo bundle corpus, so `requests.json` is reproducible from a checkout:

    python scripts/data/event_baseline_requests.py \
        --events-dir docs/data/event-baseline/events \
        --output docs/data/event-baseline/requests.json

Every request is one (county FIPS, window) selection taken from an accepted or
candidate bundle record.  No request is invented: the frame is exactly the union
of the county-windows the bundles name.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

REQUEST_SCHEMA_VERSION = "flux-460-final-requests/v1"

# EAGLE-I keys rows by state name, not FIPS; this is the documented mapping for
# the state FIPS prefixes the corpus uses.  An unlisted prefix is a hard error,
# never a silent skip.
STATE_BY_FIPS_PREFIX = {
    "01": "Alabama",
    "04": "Arizona",
    "05": "Arkansas",
    "06": "California",
    "08": "Colorado",
    "09": "Connecticut",
    "10": "Delaware",
    "12": "Florida",
    "13": "Georgia",
    "17": "Illinois",
    "18": "Indiana",
    "19": "Iowa",
    "20": "Kansas",
    "21": "Kentucky",
    "22": "Louisiana",
    "24": "Maryland",
    "25": "Massachusetts",
    "26": "Michigan",
    "27": "Minnesota",
    "28": "Mississippi",
    "29": "Missouri",
    "31": "Nebraska",
    "32": "Nevada",
    "33": "New Hampshire",
    "34": "New Jersey",
    "35": "New Mexico",
    "36": "New York",
    "37": "North Carolina",
    "38": "North Dakota",
    "39": "Ohio",
    "40": "Oklahoma",
    "41": "Oregon",
    "42": "Pennsylvania",
    "45": "South Carolina",
    "46": "South Dakota",
    "47": "Tennessee",
    "48": "Texas",
    "49": "Utah",
    "50": "Vermont",
    "51": "Virginia",
    "53": "Washington",
    "54": "West Virginia",
    "55": "Wisconsin",
}


class RequestFrameError(ValueError):
    """Raised when the request frame cannot be derived from the corpus."""


def _slug(stamp: str) -> str:
    return stamp.replace("-", "").replace(":", "").replace("T", "").replace("Z", "")


def bundle_paths(events_dir: Path) -> list[Path]:
    return sorted(path for path in events_dir.rglob("*.json"))


def build_frame(events_dir: Path) -> dict[str, Any]:
    paths = bundle_paths(events_dir)
    if not paths:
        raise RequestFrameError(f"{events_dir}: no event bundles")
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    inputs: list[dict[str, str]] = []
    for path in paths:
        raw = path.read_bytes()
        inputs.append(
            {
                "path": path.as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        bundle = json.loads(raw)
        if "records" not in bundle or "event" not in bundle:
            raise RequestFrameError(f"{path}: not an event-baseline bundle")
        for record in bundle["records"]:
            fips = str(record["county_fips"]).zfill(5)
            prefix = fips[:2]
            if prefix not in STATE_BY_FIPS_PREFIX:
                raise RequestFrameError(
                    f"{path}: county FIPS {fips} has no documented EAGLE-I state name"
                )
            start, end = record["window_start_utc"], record["window_end_utc"]
            item = {
                "event_id": f"{bundle['event']['event_id']}-{fips}-{_slug(start)}",
                "year": int(start[:4]),
                "start": start,
                "end": end,
                "states": [STATE_BY_FIPS_PREFIX[prefix]],
                "fips": [fips],
            }
            key = (fips, start, end)
            if key in seen and seen[key] != item:
                raise RequestFrameError(f"ambiguous duplicate county-window {key}")
            seen[key] = item
    requests = sorted(
        seen.values(), key=lambda item: (item["year"], item["start"], item["event_id"])
    )
    year_counts: dict[str, int] = {}
    for item in requests:
        year_counts[str(item["year"])] = year_counts.get(str(item["year"]), 0) + 1
    return {
        "request_schema_version": REQUEST_SCHEMA_VERSION,
        "source": "in-repo canonical event bundles",
        "requests": requests,
        "year_counts": year_counts,
        "receipt": receipt(events_dir, inputs),
    }


def head_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def receipt(events_dir: Path, inputs: list[dict[str, str]]) -> dict[str, Any]:
    generator = Path(__file__)
    return {
        "capture_method": "generated",
        "generator": generator.name,
        "generator_path": "scripts/data/event_baseline_requests.py",
        "generator_sha256": hashlib.sha256(generator.read_bytes()).hexdigest(),
        "generator_commit": head_commit(),
        "input_events_dir": events_dir.as_posix(),
        "input_bundle_count": len(inputs),
        "input_bundles": inputs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        frame = build_frame(args.events_dir)
    except RequestFrameError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(frame, indent=2, sort_keys=True) + "\n")
    print(
        f"WROTE {args.output} ({len(frame['requests'])} requests from "
        f"{frame['receipt']['input_bundle_count']} bundles)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Probe whether every Texas P0 raw input has a usable declared retrieval.

The Texas P0 builder (``pipelines.build``) refuses to promote unless every
entry in ``datasets/catalog.json:p0_raw_inputs`` is present under the raw
directory in the exact documented layout.  ``datasets/download.py`` writes a
*catalog-shaped* tree instead, and only for catalog datasets that declare a
``downloads`` entry.  This script records, honestly and reproducibly, which P0
inputs can actually be obtained on this machine and which cannot.

It never writes into the raw directory, never mutates a database, and never
invents a retrieval URL that the catalog does not declare.  A P0 input with no
declared download is reported as ``no_declared_retrieval`` -- an unavailable
input with a named next step, not a failure to be papered over.

Network probing is opt-in via ``--network``.  Without it the script reports
only the static mapping, so it stays usable in an offline CI run.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPOSITORY_ROOT / "datasets" / "catalog.json"
USER_AGENT = "flux-texas-p0-acquisition-probe/1 (+https://github.com/2WKG/flux)"

# Which catalog dataset, if any, is the declared publisher route for each P0
# raw input.  A value of ``None`` means the catalog declares no retrieval for
# that input at all; that is the finding, not an invitation to guess a URL.
P0_INPUT_SOURCES: dict[str, str | None] = {
    "activsg2000_current/ACTIVSg2000.aux": "activsg2000",
    "activsg2000_current/case_ACTIVSg2000.m": "activsg2000",
    "tiger/2024/tl_2024_us_county.zip": "census-tiger-counties",
    "NRI v1.20 county data": "fema-nri",
    "pudl/v2026.2.0/out_eia__yearly_plants.parquet": "pudl-eia860-plants",
    "pudl/v2026.2.0/out_eia__yearly_generators.parquet": "pudl-eia860-plants",
    "eia930/2021_h1/EIA930_BALANCE_2021_Jan_Jun.csv": "eia-930",
    "eia930/2024_h2/EIA930_BALANCE_2024_Jul_Dec.csv": "eia-930",
    "nws_zone_county/bp10nv20/bp10nv20.dbx": None,
    "nws_zone_county/bp05mr24/bp05mr24.dbx": None,
    "storm_events/2021/StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz": (
        "noaa-storm-events"
    ),
    "storm_events/2024/StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz": (
        "noaa-storm-events"
    ),
    "eaglei/support/MCC.csv": "eaglei-2021",
    "eaglei/support/coverage_history.csv": "eaglei-2021",
    "eaglei/2021/eaglei_outages_2021.csv": "eaglei-2021",
    "eaglei/2024/eaglei_outages_2024.csv": "eaglei-2024",
    "ntad_military_bases/fy2024/texas.geojson": "dod-bases-tx",
}

# Why a declared catalog dataset still does not yield the exact P0 artifact.
# Each note is a named next step for an operator, never a silent substitution.
LAYOUT_NOTES: dict[str, str] = {
    "activsg2000_current/ACTIVSg2000.aux": (
        "Catalog ships activsg2000-current.zip; the .aux must be extracted into "
        "the documented layout by hand."
    ),
    "activsg2000_current/case_ACTIVSg2000.m": (
        "Catalog ships activsg2000-current.zip; the .m case must be extracted "
        "into the documented layout by hand."
    ),
    "pudl/v2026.2.0/out_eia__yearly_plants.parquet": (
        "Catalog declares the nightly core_eia860__scd_plants.parquet, not the "
        "pinned v2026.2.0 out_eia__yearly_plants.parquet the builder requires."
    ),
    "pudl/v2026.2.0/out_eia__yearly_generators.parquet": (
        "Catalog declares no generators Parquet at any version."
    ),
    "eaglei/support/MCC.csv": (
        "Catalog declares only the annual outage CSV; the MCC support file has "
        "no declared download."
    ),
    "eaglei/support/coverage_history.csv": (
        "Catalog declares only the annual outage CSV; coverage_history.csv has "
        "no declared download."
    ),
    "ntad_military_bases/fy2024/texas.geojson": (
        "Catalog writes ntad_military_bases_tx.geojson; it must be curated into "
        "the fy2024/texas.geojson path the builder reads."
    ),
    "nws_zone_county/bp10nv20/bp10nv20.dbx": (
        "Source-pinned NWS zone/county edition; no catalog dataset covers it."
    ),
    "nws_zone_county/bp05mr24/bp05mr24.dbx": (
        "Source-pinned NWS zone/county edition; no catalog dataset covers it."
    ),
}


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def probe_url(url: str, timeout: float) -> dict[str, Any]:
    """Ask for one byte and report exactly what the publisher answered."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {
                "reachable": True,
                "http_status": response.status,
                "content_type": response.headers.get("Content-Type"),
                "content_length": response.headers.get("Content-Length"),
                "content_range": response.headers.get("Content-Range"),
                "final_url": response.url,
            }
    except urllib.error.HTTPError as error:
        return {
            "reachable": False,
            "http_status": error.code,
            "error": f"HTTPError: {error.reason}",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {
            "reachable": False,
            "http_status": None,
            "error": f"{type(error).__name__}: {error}",
        }


def build_report(
    *, raw_dir: Path, network: bool, timeout: float, catalog_path: Path = CATALOG_PATH
) -> dict[str, Any]:
    catalog = load_catalog(catalog_path)
    datasets = {entry["id"]: entry for entry in catalog["datasets"]}
    probed: dict[str, dict[str, Any]] = {}
    inputs: list[dict[str, Any]] = []

    for item in catalog["p0_raw_inputs"]:
        label = item["label"]
        present = any(raw_dir.joinpath(*parts).is_file() for parts in item["paths"])
        dataset_id = P0_INPUT_SOURCES.get(label)
        record: dict[str, Any] = {
            "label": label,
            "acceptable_paths": ["/".join(parts) for parts in item["paths"]],
            "present_locally": present,
            "catalog_dataset": dataset_id,
        }
        if label in LAYOUT_NOTES:
            record["layout_note"] = LAYOUT_NOTES[label]
        if dataset_id is None:
            record["retrieval"] = "no_declared_retrieval"
            record["next_step"] = (
                "Add a catalog dataset (or a source receipt) declaring this "
                "artifact's publisher URL, license, and checksum before the "
                "Texas P0 build can be reproduced."
            )
            inputs.append(record)
            continue
        dataset = datasets[dataset_id]
        record["catalog_access"] = dataset["access"]
        downloads = dataset.get("downloads", [])
        if not downloads:
            record["retrieval"] = "manual_only"
            record["source_url"] = dataset["source_url"]
            record["next_step"] = (
                f"Retrieve {dataset_id} by hand from {dataset['source_url']} and "
                "record a source receipt; the catalog declares no scripted URL."
            )
            inputs.append(record)
            continue
        record["retrieval"] = "declared_download"
        record["downloads"] = []
        for download in downloads:
            entry = {"filename": download["filename"], "url": download["url"]}
            if network:
                if download["url"] not in probed:
                    probed[download["url"]] = probe_url(download["url"], timeout)
                entry["probe"] = probed[download["url"]]
            record["downloads"].append(entry)
        inputs.append(record)

    unavailable = [
        item["label"]
        for item in inputs
        if not item["present_locally"] and item["retrieval"] != "declared_download"
    ]
    needs_curation = [
        item["label"]
        for item in inputs
        if not item["present_locally"] and "layout_note" in item
    ]
    return {
        "probe_version": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        # POSIX form so a committed receipt is host-independent.
        "raw_dir": raw_dir.as_posix(),
        "catalog": catalog_path.as_posix(),
        "catalog_schema_version": catalog.get("schema_version"),
        "network_probed": network,
        "scope_label": (
            "Texas P0 / ACTIVSg2000 legacy research evidence. ACTIVSg2000 is "
            "synthetic topology and is not the Minnesota demo delivery path."
        ),
        "p0_inputs": inputs,
        "summary": {
            "total_inputs": len(inputs),
            "present_locally": sum(1 for item in inputs if item["present_locally"]),
            "with_declared_download": sum(
                1 for item in inputs if item["retrieval"] == "declared_download"
            ),
            "unavailable_without_manual_retrieval": unavailable,
            "requires_manual_curation_into_builder_layout": needs_curation,
            "reproducible_end_to_end": not unavailable and not needs_curation,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--network",
        action="store_true",
        help="Probe each declared download URL with a one-byte ranged request",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report", type=Path, help="Optional JSON report path")
    args = parser.parse_args(argv)

    report = build_report(
        raw_dir=args.raw_dir, network=args.network, timeout=args.timeout
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["summary"]["reproducible_end_to_end"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

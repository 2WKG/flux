#!/usr/bin/env python3
"""Fetch the Texas P0 raw inputs from their tracked source receipts.

``datasets/catalog.json`` declares scripted downloads for only part of the P0
raw-input contract, and the filenames it writes do not match the layout
``pipelines.build`` reads (see ``scripts/data/texas_p0_acquisition_probe.py``).
The authoritative provenance for the remaining inputs already lives in the
tracked receipts under ``data/sources/``: publisher, source URL, license,
retrieval time, byte count, and SHA-256 per file.

This script is driven by those receipts.  Every URL it requests is either
stated verbatim in a receipt or composed from that receipt's own directory
``source_url`` plus the receipt's own filename; none is invented here.  Every
downloaded file is verified against the receipt's SHA-256 and byte count and is
discarded on mismatch, so a changed upstream artifact fails loudly instead of
silently entering a build.

Texas P0 / ACTIVSg2000 is legacy research evidence.  ACTIVSg2000 is synthetic
topology, not the real ERCOT network, and nothing this script fetches is
Minnesota demo evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCES_DIR = REPOSITORY_ROOT / "data" / "sources"
USER_AGENT = "flux-texas-p0-fetch/1 (+https://github.com/2WKG/flux)"
# ``requests`` rather than ``urllib``: FEMA's NRI ZIP answered every
# ``urllib.request`` call with HTTP 403 on 2026-09-06 regardless of
# User-Agent, while the identical URL served 206/200 to ``requests`` and to
# ``curl``.  The URL is the receipt's; only the client differs.
CHUNK_BYTES = 1 << 20


class FetchError(RuntimeError):
    """A download or verification failed; never silently tolerated."""


@dataclass(frozen=True)
class Item:
    """One raw artifact: where the receipt says it comes from and where it goes."""

    receipt: str
    filename: str
    destination: tuple[str, ...]
    # How the URL is derived from the receipt, so the rule is auditable.
    url_rule: str
    # Optional archive member to extract instead of writing the payload itself.
    extract_member: str | None = None
    notes: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)


# ``source_url`` — receipt's top-level source_url is the exact file URL.
# ``source_url_dir`` — receipt's source_url is a directory; append the filename.
# ``file_url`` — the file entry carries its own ``original_url``.
# ``file_archive_url`` — the file entry carries a publisher-archive capture URL.
# ``source_urls_match`` — receipt has a ``source_urls`` list; pick by basename.
# ``figshare_file_id`` — the file entry carries a figshare file id.
PLAN: tuple[Item, ...] = (
    Item(
        receipt="texas-nri-v1.20",
        filename="NRI_Table_Counties.zip",
        destination=("nri", "v1.20", "NRI_Table_Counties.zip"),
        url_rule="source_url",
    ),
    Item(
        receipt="texas-pudl-eia860-v2026.2.0",
        filename="out_eia__yearly_plants.parquet",
        destination=("pudl", "v2026.2.0", "out_eia__yearly_plants.parquet"),
        url_rule="source_urls_match",
    ),
    Item(
        receipt="texas-pudl-eia860-v2026.2.0",
        filename="out_eia__yearly_generators.parquet",
        destination=("pudl", "v2026.2.0", "out_eia__yearly_generators.parquet"),
        url_rule="source_urls_match",
    ),
    Item(
        receipt="texas-eia930-2021-2024",
        filename="EIA930_BALANCE_2021_Jan_Jun.csv",
        destination=("eia930", "2021_h1", "EIA930_BALANCE_2021_Jan_Jun.csv"),
        url_rule="source_url_dir",
        notes="EIA six-month grid-monitor files are mutable captures; the "
        "receipt's SHA-256 is the pin.",
    ),
    Item(
        receipt="texas-eia930-2021-2024",
        filename="EIA930_BALANCE_2024_Jul_Dec.csv",
        destination=("eia930", "2024_h2", "EIA930_BALANCE_2024_Jul_Dec.csv"),
        url_rule="source_url_dir",
    ),
    Item(
        receipt="texas-nws-zone-county-bp16ap26",
        filename="bp10nv20.dbx",
        destination=("nws_zone_county", "bp10nv20", "bp10nv20.dbx"),
        url_rule="file_url",
        notes="Historical edition pinned to the Uri window; the live NWS path "
        "now serves a newer edition, so the archive capture is the fallback.",
    ),
    Item(
        receipt="texas-nws-zone-county-bp16ap26",
        filename="bp05mr24.dbx",
        destination=("nws_zone_county", "bp05mr24", "bp05mr24.dbx"),
        url_rule="file_url",
    ),
    Item(
        receipt="texas-noaa-storm-events-2021-2024",
        filename="StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz",
        destination=(
            "storm_events",
            "2021",
            "StormEvents_details-ftp_v1.0_d2021_c20260323.csv.gz",
        ),
        url_rule="source_url_dir",
    ),
    Item(
        receipt="texas-noaa-storm-events-2021-2024",
        filename="StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz",
        destination=(
            "storm_events",
            "2024",
            "StormEvents_details-ftp_v1.0_d2024_c20260728.csv.gz",
        ),
        url_rule="source_url_dir",
    ),
    Item(
        receipt="texas-eaglei-2021-2024",
        filename="MCC.csv",
        destination=("eaglei", "support", "MCC.csv"),
        url_rule="figshare_file_id",
    ),
    Item(
        receipt="texas-eaglei-2021-2024",
        filename="coverage_history.csv",
        destination=("eaglei", "support", "coverage_history.csv"),
        url_rule="figshare_file_id",
    ),
    Item(
        receipt="texas-eaglei-2021-2024",
        filename="eaglei_outages_2021.csv",
        destination=("eaglei", "2021", "eaglei_outages_2021.csv"),
        url_rule="figshare_file_id",
        notes="~1.1 GB.",
    ),
    Item(
        receipt="texas-eaglei-2021-2024",
        filename="eaglei_outages_2024.csv",
        destination=("eaglei", "2024", "eaglei_outages_2024.csv"),
        url_rule="figshare_file_id",
        notes="~1.4 GB.",
    ),
    Item(
        receipt="texas-tiger-2024",
        filename="tl_2024_us_county.zip",
        destination=("tiger", "2024", "tl_2024_us_county.zip"),
        url_rule="source_url",
    ),
    Item(
        receipt="texas-ntad-military-bases-fy2024",
        filename="texas.geojson",
        destination=("ntad_military_bases", "fy2024", "texas.geojson"),
        url_rule="source_url",
        notes="ArcGIS query response; bytes can change when the service "
        "re-serializes, which the SHA-256 check surfaces.",
    ),
    Item(
        receipt="activsg2000",
        filename="ACTIVSg2000_current.zip",
        destination=("activsg2000_current", "ACTIVSg2000.aux"),
        url_rule="provider_download_url",
        extract_member="ACTIVSg2000.aux",
        notes="Synthetic Texas case. Extracted from the current-version bundle "
        "so AUX coordinates match the electrical case.",
    ),
    Item(
        receipt="activsg2000",
        filename="ACTIVSg2000_current.zip",
        destination=("activsg2000_current", "case_ACTIVSg2000.m"),
        url_rule="provider_download_url",
        extract_member="case_ACTIVSg2000.m",
    ),
)


def load_receipt(name: str) -> dict[str, Any]:
    path = SOURCES_DIR / f"{name}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FetchError(f"unreadable source receipt {path}: {error}") from error


def resolve(item: Item, receipt: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Return candidate URLs and the receipt's expected file entry."""
    entry = receipt.get("files", {}).get(item.filename)
    if not isinstance(entry, dict) or not entry.get("sha256"):
        raise FetchError(
            f"{item.receipt}: no SHA-256 recorded for {item.filename}; refusing "
            "to download an artifact with no tracked provenance"
        )
    rule, urls = item.url_rule, []
    if rule == "source_url":
        urls = [receipt["source_url"]]
    elif rule == "source_url_dir":
        urls = [receipt["source_url"].rstrip("/") + "/" + item.filename]
    elif rule == "source_urls_match":
        urls = [
            url
            for url in receipt["source_urls"]
            if url.rsplit("/", 1)[-1] == item.filename
        ]
    elif rule == "file_url":
        urls = [
            url
            for key in ("original_url", "archive_url")
            if (url := entry.get(key)) is not None
        ]
    elif rule == "figshare_file_id":
        urls = [f"https://ndownloader.figshare.com/files/{entry['figshare_file_id']}"]
    elif rule == "provider_download_url":
        urls = [receipt["provider"]["download_url"]]
    if not urls:
        raise FetchError(
            f"{item.receipt}: url rule {rule!r} resolved no URL for {item.filename}"
        )
    return urls, entry


def download(url: str, destination: Path, timeout: float) -> str:
    """Stream to a temporary file and return its SHA-256."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    try:
        with requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            stream=True,
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_content(CHUNK_BYTES):
                    digest.update(chunk)
                    handle.write(chunk)
    except (requests.RequestException, OSError):
        partial.unlink(missing_ok=True)
        raise
    partial.replace(destination)
    return digest.hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _verify(path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    observed_sha, observed_bytes = sha256_path(path), path.stat().st_size
    expected_bytes = entry.get("bytes")
    return {
        "observed_sha256": observed_sha,
        "observed_bytes": observed_bytes,
        "expected_sha256": entry["sha256"],
        "expected_bytes": expected_bytes,
        "verified": observed_sha == entry["sha256"]
        and (expected_bytes is None or observed_bytes == expected_bytes),
    }


def _extract(archive: Path, member: str, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle, bundle.open(member) as source:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            shutil.copyfileobj(source, handle)


def fetch_item(
    item: Item, raw: Path, *, force: bool, timeout: float, dry_run: bool
) -> dict[str, Any]:
    destination = raw.joinpath(*item.destination)
    receipt = load_receipt(item.receipt)
    result: dict[str, Any] = {
        "receipt": item.receipt,
        "filename": item.filename,
        # POSIX form, always: these strings are committed into acceptance
        # receipts, so a Windows run must not emit backslash paths that no
        # other host can read or diff.
        "destination": destination.as_posix(),
        "url_rule": item.url_rule,
        "provider": receipt.get("provider"),
        "license_access": receipt.get("license_access"),
        "receipt_retrieved_at": receipt.get("retrieved_at"),
    }
    if item.notes:
        result["notes"] = item.notes
    try:
        urls, entry = resolve(item, receipt)
    except FetchError as error:
        return {**result, "status": "unavailable", "error": str(error)}
    result["candidate_urls"] = urls
    # The archive member's own digest, when the receipt records one.
    member_entry = (
        receipt.get("files", {}).get(item.extract_member)
        if item.extract_member
        else None
    )
    check_entry = member_entry if isinstance(member_entry, dict) else entry

    if destination.is_file() and not force:
        return {
            **result,
            "status": "already_present",
            **_verify(destination, check_entry),
        }
    if dry_run:
        return {**result, "status": "would_download"}

    payload = destination.parent / item.filename if item.extract_member else destination
    attempts = []
    for url in urls:
        try:
            observed = download(url, payload, timeout)
        except (requests.RequestException, FetchError, OSError) as error:
            attempts.append({"url": url, "error": f"{type(error).__name__}: {error}"})
            continue
        if observed != entry["sha256"]:
            attempts.append(
                {
                    "url": url,
                    "error": "sha256 mismatch",
                    "observed_sha256": observed,
                    "expected_sha256": entry["sha256"],
                }
            )
            payload.unlink(missing_ok=True)
            continue
        if item.extract_member:
            _extract(payload, item.extract_member, destination)
        return {
            **result,
            "status": "downloaded",
            "url": url,
            "attempts": attempts,
            **_verify(destination, check_entry),
        }
    return {**result, "status": "failed", "attempts": attempts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Limit to these receipt names (repeatable)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-download present files"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--report", type=Path, help="Optional JSON report path")
    args = parser.parse_args(argv)

    selected = [
        item for item in PLAN if not args.only or item.receipt in set(args.only)
    ]
    results = [
        fetch_item(
            item,
            args.raw_dir,
            force=args.force,
            timeout=args.timeout,
            dry_run=args.dry_run,
        )
        for item in selected
    ]
    unverified = [
        item
        for item in results
        if item["status"] in {"downloaded", "already_present"}
        and not item.get("verified", False)
    ]
    failed = [item for item in results if item["status"] in {"failed", "unavailable"}]
    report = {
        "fetch_version": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        "raw_dir": args.raw_dir.as_posix(),
        "scope_label": (
            "Texas P0 / ACTIVSg2000 legacy research inputs. ACTIVSg2000 is "
            "synthetic topology, not the real ERCOT network, and none of this "
            "is Minnesota demo evidence."
        ),
        "artifacts": results,
        "summary": {
            "requested": len(results),
            "downloaded": sum(1 for i in results if i["status"] == "downloaded"),
            "already_present": sum(
                1 for i in results if i["status"] == "already_present"
            ),
            "failed_or_unavailable": [i["filename"] for i in failed],
            "present_but_unverified": [i["filename"] for i in unverified],
            "all_verified": not failed and not unverified,
        },
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["summary"]["all_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

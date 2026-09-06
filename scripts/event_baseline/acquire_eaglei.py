"""Acquire a bounded, auditable EAGLE-I county-outage slice with HTTP ranges.

The annual EAGLE-I CSVs are large and contain timezone-naive timestamp text.
EAGLE-I's Scientific Data documentation states that ``run_start_time`` is UTC;
the receipt records that source and does no conversion. It writes only the
requested, complete CSV records and a JSON receipt; raw source bytes stay in
the caller-selected cache directory, outside Git.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

FIGSHARE_ARTICLE_URL = "https://api.figshare.com/v2/articles/24237376"
FIGSHARE_DOI = "10.6084/m9.figshare.24237376.v4"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
TIME_BASIS_SOURCE_URL = "https://www.nature.com/articles/s41597-024-03095-5"
SOURCE_TIMEZONE = "UTC (EAGLE-I Scientific Data documentation)"
PROBE_BYTES = 65_536


@dataclass(frozen=True)
class RangeReceipt:
    start: int
    end: int
    content_range: str | None
    etag: str | None
    sha256: str
    bytes_received: int


class EagleiError(RuntimeError):
    """A source record cannot be safely used as a bounded EAGLE-I slice."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_source_time(value: str) -> datetime:
    """Parse the UTC timestamp text emitted by the EAGLE-I annual CSV."""
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def annual_file(article: dict[str, Any], year: int) -> dict[str, Any]:
    target = f"eaglei_outages_{year}.csv"
    matches = [item for item in article.get("files", []) if item.get("name") == target]
    if len(matches) != 1:
        raise EagleiError(f"Figshare article has {len(matches)} files named {target!r}")
    return matches[0]


def _complete_csv_rows(payload: bytes, fieldnames: list[str]) -> list[dict[str, str]]:
    """Discard potentially truncated first/last records from an HTTP range."""
    first = payload.find(b"\n")
    last = payload.rfind(b"\n")
    if first < 0 or last <= first:
        return []
    text = payload[first + 1 : last + 1].decode("utf-8-sig", errors="strict")
    return list(csv.DictReader(io.StringIO(text), fieldnames=fieldnames))


def _range_get(
    session: requests.Session, url: str, start: int, end: int, expected_etag: str | None = None
) -> tuple[bytes, RangeReceipt]:
    headers = {"Range": f"bytes={start}-{end}"}
    if expected_etag:
        headers["If-Match"] = expected_etag
    response = session.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    payload = response.content
    content_range = response.headers.get("Content-Range")
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range or "")
    if response.status_code != 206 or not match:
        raise EagleiError(
            "source did not honor HTTP Range; refusing a full annual download"
        )
    actual_start, actual_end = int(match.group(1)), int(match.group(2))
    if (actual_start, actual_end) != (start, end) or len(payload) != end - start + 1:
        raise EagleiError("source returned a mismatched or truncated HTTP range")
    if expected_etag and response.headers.get("ETag") != expected_etag:
        raise EagleiError("source ETag changed during acquisition")
    receipt = RangeReceipt(
        start=start,
        end=end,
        content_range=content_range,
        etag=response.headers.get("ETag"),
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes_received=len(payload),
    )
    return payload, receipt


def source_columns(
    session: requests.Session, url: str
) -> tuple[list[str], RangeReceipt]:
    payload, receipt = _range_get(session, url, 0, 4095)
    header = payload.split(b"\n", 1)[0].decode("utf-8-sig", errors="strict").strip("\r")
    columns = next(csv.reader([header]))
    required = {"fips_code", "county", "state", "run_start_time"}
    if not required.issubset(columns):
        raise EagleiError(
            f"source header is missing required columns: {sorted(required - set(columns))}"
        )
    outage_fields = {"customers_out", "sum"} & set(columns)
    if len(outage_fields) != 1:
        raise EagleiError(
            "source header must contain exactly one documented outage field: customers_out or sum"
        )
    return columns, receipt


def outage_field(fieldnames: list[str]) -> str:
    """Return the documented annual-file spelling for customer outages."""
    if "customers_out" in fieldnames:
        return "customers_out"
    if "sum" in fieldnames:
        return "sum"
    raise EagleiError("no documented customer-outage field is present")


def probe_at(
    session: requests.Session, url: str, offset: int, size: int, fieldnames: list[str], expected_etag: str
) -> tuple[list[dict[str, str]], RangeReceipt]:
    payload, receipt = _range_get(session, url, offset, offset + size - 1, expected_etag)
    rows = _complete_csv_rows(payload, fieldnames)
    if not rows:
        raise EagleiError(f"no complete CSV rows in range beginning at {offset}")
    times = [parse_source_time(row["run_start_time"]) for row in rows]
    if times != sorted(times):
        raise EagleiError(f"source ordering failed inside range beginning at {offset}")
    return rows, receipt


def locate_time(
    session: requests.Session,
    url: str,
    size: int,
    target: datetime,
    fieldnames: list[str],
    expected_etag: str,
) -> tuple[int, list[RangeReceipt]]:
    """Binary-search a time-ordered file and return a nearby byte offset."""
    lo, hi = 0, size - PROBE_BYTES
    receipts: list[RangeReceipt] = []
    for _ in range(32):
        if hi - lo <= PROBE_BYTES:
            return lo, receipts
        middle = ((lo + hi) // 2) // PROBE_BYTES * PROBE_BYTES
        rows, receipt = probe_at(session, url, middle, PROBE_BYTES, fieldnames, expected_etag)
        receipts.append(receipt)
        first = parse_source_time(rows[0]["run_start_time"])
        last = parse_source_time(rows[-1]["run_start_time"])
        if target < first:
            hi = middle
        elif target > last:
            lo = middle + PROBE_BYTES
        else:
            return middle, receipts
    raise EagleiError("time lookup did not converge")


def acquire(
    *,
    event_id: str | None,
    year: int,
    start: datetime,
    end: datetime,
    states: set[str],
    fips: set[str],
    cache_dir: Path,
) -> dict[str, Any]:
    if start >= end:
        raise ValueError("start must precede end")
    session = requests.Session()
    article_response = session.get(FIGSHARE_ARTICLE_URL, timeout=30)
    article_response.raise_for_status()
    article = article_response.json()
    file = annual_file(article, year)
    source_size = int(file["size"])
    source_url = str(file["download_url"])
    fieldnames, header_receipt = source_columns(session, source_url)
    customers_out_field = outage_field(fieldnames)
    if not header_receipt.etag:
        raise EagleiError("source response omitted ETag; cannot pin a multi-range acquisition")

    start_offset, start_probes = locate_time(
        session, source_url, source_size, start, fieldnames, header_receipt.etag
    )
    end_offset, end_probes = locate_time(
        session, source_url, source_size, end, fieldnames, header_receipt.etag
    )
    raw_start = max(0, start_offset - 2 * PROBE_BYTES)
    raw_end = min(source_size - 1, end_offset + 3 * PROBE_BYTES - 1)
    payload, raw_receipt = _range_get(session, source_url, raw_start, raw_end, header_receipt.etag)
    rows = _complete_csv_rows(payload, fieldnames)
    expected_times = {start + timedelta(minutes=15 * index) for index in range(int((end - start).total_seconds() // 900))}
    raw_times = {parse_source_time(row["run_start_time"]) for row in rows}
    if not raw_times or min(raw_times) > start or max(raw_times) < max(expected_times):
        raise EagleiError("final range does not bracket requested window; acquisition may be truncated")
    selected = [
        row
        for row in rows
        if row["state"] in states
        and (not fips or row["fips_code"] in fips)
        and start <= parse_source_time(row["run_start_time"]) < end
    ]
    observed_by_fips = {
        code: {
            parse_source_time(row["run_start_time"])
            for row in selected
            if row["fips_code"] == code
        }
        for code in (fips or {row["fips_code"] for row in selected})
    }
    coverage = {
        code: {
            "observed_intervals": len(times),
            "expected_intervals_at_15_min": len(expected_times),
            "missing_intervals": len(expected_times - times),
            "availability": "Available" if times else "UncoveredLabel",
            "coverage_state": (
                "complete_15_min_observation"
                if times == expected_times
                else "partial_15_min_observation"
                if times
                else "UncoveredLabel"
            ),
        }
        for code, times in sorted(observed_by_fips.items())
    }
    denominator_summary = {
        code: {
            "observed_rows_with_total_customers": sum(
                1
                for row in selected
                if row["fips_code"] == code
                and row.get("total_customers") not in (None, "")
            ),
            "missing_total_customers_rows": sum(
                1
                for row in selected
                if row["fips_code"] == code and row.get("total_customers") in (None, "")
            ),
            "min": min(
                (
                    int(row["total_customers"])
                    for row in selected
                    if row["fips_code"] == code
                    and row.get("total_customers") not in (None, "")
                ),
                default=None,
            ),
            "max": max(
                (
                    int(row["total_customers"])
                    for row in selected
                    if row["fips_code"] == code
                    and row.get("total_customers") not in (None, "")
                ),
                default=None,
            ),
        }
        for code in sorted(fips)
    }

    cache_dir.mkdir(parents=True, exist_ok=True)
    event_prefix = f"{event_id}_" if event_id else ""
    slug = f"{event_prefix}eaglei_{year}_{start:%Y%m%dT%H%M%S}_{end:%Y%m%dT%H%M%S}"
    csv_path = cache_dir / f"{slug}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected)
    filtered_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    receipt = {
        "source_system_id": f"figshare:{article['id']}:{file['id']}",
        "receipt_id": f"eaglei-{year}-{file['id']}-{start:%Y%m%dT%H%M%S}-{end:%Y%m%dT%H%M%S}",
        "event_id": event_id,
        "provider": "ORNL EAGLE-I via Figshare",
        "release": FIGSHARE_DOI,
        "source_title": article["title"],
        "source_doi": FIGSHARE_DOI,
        "source_url": source_url,
        "source_file": file["name"],
        "source_file_bytes": source_size,
        "license": {"name": article["license"]["name"], "url": LICENSE_URL},
        "retrieved_at_utc": utc_now(),
        "source_time_basis": SOURCE_TIMEZONE,
        "source_time_basis_url": TIME_BASIS_SOURCE_URL,
        "timezone_conversion": "none; EAGLE-I documentation states run_start_time is UTC",
        "requested_utc_half_open": {"start": start.isoformat(), "end": end.isoformat()},
        "state_filter": sorted(states),
        "county_fips_filter": sorted(fips),
        "header_range": header_receipt.__dict__,
        "source_columns": fieldnames,
        "range_probes": [item.__dict__ for item in start_probes + end_probes],
        "raw_range": raw_receipt.__dict__,
        "raw_sha256": raw_receipt.sha256,
        "filtered_sha256": filtered_hash,
        "raw_bytes": raw_receipt.bytes_received,
        "filtered_bytes": csv_path.stat().st_size,
        "etag": raw_receipt.etag,
        "filtered_artifact": str(csv_path),
        "filtered_rows": len(selected),
        "source_row_identity": ["fips_code", "run_start_time"],
        "reported_timestamp_min": min(
            (row["run_start_time"] for row in selected), default=None
        ),
        "reported_timestamp_max": max(
            (row["run_start_time"] for row in selected), default=None
        ),
        "coverage_by_county": coverage,
        "customers_out_summary": {
            code: {
                "min": min(
                    (
                        int(row[customers_out_field])
                        for row in selected
                        if row["fips_code"] == code
                    ),
                    default=None,
                ),
                "max": max(
                    (
                        int(row[customers_out_field])
                        for row in selected
                        if row["fips_code"] == code
                    ),
                    default=None,
                ),
            }
            for code in sorted(fips)
        },
        "total_customers_summary": denominator_summary
        if "total_customers" in fieldnames
        else None,
        "outage_field_source": customers_out_field,
        "outage_field_semantics": "total customers without electricity at the source timestamp",
        "units": {customers_out_field: "customers", "run_start_time": "UTC"},
        "filters": {
            "states": sorted(states),
            "county_fips": sorted(fips),
            "window": "UTC half-open",
        },
        "grid_index_mapping": None,
        "gaps": "Explicit zero values are retained observations. A missing row has unknown meaning (zero or collection gap) and contract classification is UncoveredLabel.",
        "customer_denominator": (
            "native `total_customers` present in selected rows; retain per-row values and missingness"
            if "total_customers" in fieldnames and selected
            else "native `total_customers` is in the annual source schema but no selected observations were emitted"
            if "total_customers" in fieldnames
            else "unavailable in this annual slice; do not substitute population"
        ),
        "absence_rule": "explicit source zeros are observations; missing rows are UncoveredLabel, never imputed zero",
    }
    receipt_path = cache_dir / f"{slug}.receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--event-id",
        help="stable caller event identifier; used only in cache artifact names and receipt",
    )
    parser.add_argument(
        "--start-source-clock",
        required=True,
        help="UTC YYYY-MM-DDTHH:MM:SS; EAGLE-I documents run_start_time as UTC",
    )
    parser.add_argument(
        "--end-source-clock", required=True, help="exclusive UTC YYYY-MM-DDTHH:MM:SS"
    )
    parser.add_argument(
        "--states",
        required=True,
        help="comma-separated EAGLE-I state names, e.g. Minnesota,Wisconsin",
    )
    parser.add_argument(
        "--fips",
        default="",
        help="optional comma-separated county FIPS; preserves an explicit UncoveredLabel receipt when absent",
    )
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    receipt = acquire(
        event_id=args.event_id,
        year=args.year,
        start=parse_source_time(args.start_source_clock.replace("T", " ")),
        end=parse_source_time(args.end_source_clock.replace("T", " ")),
        states={state.strip() for state in args.states.split(",") if state.strip()},
        fips={code.strip().zfill(5) for code in args.fips.split(",") if code.strip()},
        cache_dir=args.cache_dir,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

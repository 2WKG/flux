"""Acquire a bounded, auditable EAGLE-I county-outage slice with HTTP ranges.

The annual EAGLE-I CSVs are large (the 2024 file is ~1.44 GB per this repo's
``data/sources/texas-eaglei-2021-2024.json``) and contain timezone-naive
timestamp text. EAGLE-I's Scientific Data documentation states that
``run_start_time`` is UTC; the receipt records that source and does no
conversion.

Two acquisition modes exist and the receipt names which one ran:

``bounded`` (``--bounded-http-range``)
    Binary-searches the time-ordered annual file over HTTP ranges and never
    transfers more than ``--max-bytes``. Every range response must be a 206
    whose ``Content-Range`` matches the request. It is exploratory only: a
    FIPS-major annual layout does not provide the global sort proof its binary
    search would require.

``exhaustive`` (default, or a pre-populated cache)
    Streams or reuses the complete annual file. This is the only mode that may
    establish source-wide coverage.

It writes only the requested, complete CSV records and a JSON receipt; raw
source bytes stay in the caller-selected cache directory, outside Git.

Consumer: the 2WKG-461 event-baseline bundle (PR #232). Receipts emitted here
are intended to be dropped into ``source_receipts[]`` of an
``event-baseline/v1`` bundle; the ``receipt`` object below is shaped to that
schema's ``$defs/receipt`` definition, which forbids additional properties, so
the ``capture_method``/``verification`` convention from #199/#216 and the
EAGLE-I specifics are carried as siblings of it rather than inside it.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
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
PROVIDER = "ORNL EAGLE-I via Figshare"
PROBE_BYTES = 65_536

# EAGLE-I publishes one county sample every 15 minutes. In-repo evidence:
# datasets/catalog.json describes every eaglei-* entry as "Fifteen-minute county
# customers-out labels", and the run_start_time grid in the annual CSVs is
# :00/:15/:30/:45. A six-hour window therefore documents 24 samples, not six.
SOURCE_INTERVAL_SECONDS = 900
CADENCE_BASIS = (
    "15-minute run_start_time grid; basis: datasets/catalog.json "
    "('Fifteen-minute county customers-out labels') and the observed annual-CSV grid"
)
ABSENCE_RULE = (
    "Explicit source zeros are observations; a missing row has unknown meaning "
    "(zero or collection gap) and is classified UncoveredLabel, never imputed zero."
)
DEFAULT_MAX_BOUNDED_BYTES = 64 * 1024 * 1024


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


class ByteBudget:
    """Hard ceiling on the bytes a bounded acquisition may transfer."""

    def __init__(self, limit: int) -> None:
        self.limit = int(limit)
        self.spent = 0

    def reserve(self, count: int) -> None:
        if count < 0 or self.spent + count > self.limit:
            raise EagleiError(
                f"bounded acquisition would exceed its {self.limit}-byte ceiling "
                f"(already transferred {self.spent}, requested {count}); "
                "pass --allow-full-download to stream the whole annual file"
            )

    def spend(self, count: int) -> None:
        self.reserve(count)
        self.spent += count


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_source_time(value: str) -> datetime:
    """Parse the UTC timestamp text emitted by the EAGLE-I annual CSV."""
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def expected_interval_times(start: datetime, end: datetime) -> set[datetime]:
    """Every sample timestamp the source cadence requires in a half-open window."""
    count = int((end - start).total_seconds() // SOURCE_INTERVAL_SECONDS)
    return {
        start + timedelta(seconds=SOURCE_INTERVAL_SECONDS * index)
        for index in range(count)
    }


def annual_file(article: dict[str, Any], year: int) -> dict[str, Any]:
    target = f"eaglei_outages_{year}.csv"
    matches = [item for item in article.get("files", []) if item.get("name") == target]
    if len(matches) != 1:
        raise EagleiError(f"Figshare article has {len(matches)} files named {target!r}")
    return matches[0]


def resolved_license(article: dict[str, Any]) -> tuple[str, str]:
    """Return the licence name and URL the source actually reported."""
    license_block = article.get("license") or {}
    name = license_block.get("name")
    url = license_block.get("url") or LICENSE_URL
    if not name:
        raise EagleiError("source metadata did not report a licence name")
    return str(name), str(url)


def _license_text(name: str, url: str, source: str) -> str:
    return f"{name} ({url}); resolved from {source}"


def _complete_csv_rows(payload: bytes, fieldnames: list[str]) -> list[dict[str, str]]:
    """Discard potentially truncated first/last records from an HTTP range."""
    first = payload.find(b"\n")
    last = payload.rfind(b"\n")
    if first < 0 or last <= first:
        return []
    text = payload[first + 1 : last + 1].decode("utf-8-sig", errors="strict")
    return list(csv.DictReader(io.StringIO(text), fieldnames=fieldnames))


def _range_get(
    session: requests.Session,
    url: str,
    start: int,
    end: int,
    expected_etag: str | None = None,
    budget: ByteBudget | None = None,
) -> tuple[bytes, RangeReceipt]:
    headers = {"Range": f"bytes={start}-{end}"}
    if expected_etag:
        headers["If-Match"] = expected_etag
    if budget is not None:
        # Refuse before the wire, so an over-budget range is never requested.
        budget.reserve(end - start + 1)
    response = session.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    payload = response.content
    content_range = response.headers.get("Content-Range")
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range or "")
    if response.status_code != 206 or not match:
        raise EagleiError(
            "source did not honor HTTP Range; refusing a full annual download"
        )
    if budget is not None:
        budget.spend(len(payload))
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
    session: requests.Session, url: str, budget: ByteBudget | None = None
) -> tuple[list[str], RangeReceipt]:
    payload, receipt = _range_get(session, url, 0, 4095, budget=budget)
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


def trusted_annual_metadata(
    raw_path: Path, *, year: int, expected_file: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate a completed annual cache before it can establish coverage."""
    meta_path = raw_path.with_name(f"{raw_path.name}.source.json")
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise EagleiError("annual source manifest is missing or invalid") from error

    raw_bytes = raw_path.read_bytes()
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    raw_md5 = hashlib.md5(raw_bytes).hexdigest()
    source_id = metadata.get("source_system_id")
    source_file_id = str(source_id).rsplit(":", 1)[-1]
    expected_name = f"eaglei_outages_{year}.csv"
    allowed_basis = {
        "figshare_file_metadata_md5_and_size",
        "figshare_file_metadata_md5_and_size+etag_pinned_full_stream",
    }
    if (
        metadata.get("acquisition_complete") is not True
        or metadata.get("source_metadata_url") != FIGSHARE_ARTICLE_URL
        or not isinstance(source_id, str)
        or not re.fullmatch(r"figshare:24237376:\d+", source_id)
        or str(metadata.get("source_file_id")) != source_file_id
        or metadata.get("source_file") != expected_name
        or raw_path.name != expected_name
        or metadata.get("source_file_bytes") != len(raw_bytes)
        or metadata.get("raw_bytes") != len(raw_bytes)
        or metadata.get("raw_sha256") != raw_sha256
        or metadata.get("raw_md5") != raw_md5
        or metadata.get("supplied_md5") != raw_md5
        or metadata.get("computed_md5") != raw_md5
        or metadata.get("integrity_basis") not in allowed_basis
    ):
        raise EagleiError("annual source manifest does not bind trusted Figshare bytes")
    if metadata["integrity_basis"].endswith("etag_pinned_full_stream") and (
        metadata.get("etag_pinned") is not True or not metadata.get("etag")
    ):
        raise EagleiError("annual source manifest lacks ETag-pinned transfer evidence")
    if expected_file is not None and (
        source_file_id != str(expected_file["id"])
        or metadata["source_file_bytes"] != int(expected_file["size"])
        or metadata["supplied_md5"] != expected_file.get("supplied_md5")
        or metadata["computed_md5"] != expected_file.get("computed_md5")
    ):
        raise EagleiError(
            "annual source manifest disagrees with Figshare file metadata"
        )
    return metadata


def manifest_license(metadata: dict[str, Any]) -> tuple[str, str, str]:
    """Read back the licence terms recorded when the annual source was fetched."""
    name = metadata.get("license_name")
    url = metadata.get("license_url")
    source = metadata.get("license_source_url")
    if not (name and url and source):
        raise EagleiError(
            "annual source manifest does not record resolved licence terms; "
            "refusing to assert access terms that were never retrieved"
        )
    return str(name), str(url), str(source)


def _coverage_report(
    valid_rows: list[dict[str, str]],
    report_fips: list[str],
    expected: set[datetime],
) -> dict[str, dict[str, Any]]:
    coverage: dict[str, dict[str, Any]] = {}
    for code in report_fips:
        code_rows = [row for row in valid_rows if row["fips_code"] == code]
        times = {parse_source_time(row["run_start_time"]) for row in code_rows}
        coverage[code] = {
            "observed_intervals": len(times),
            "expected_intervals_at_15_min": len(expected),
            "missing_intervals": len(expected - times),
            "availability": "Available" if times else "UncoveredLabel",
            "coverage_state": (
                "complete_15_min_observation"
                if times == expected and len(times) == len(code_rows)
                else "partial_15_min_observation"
                if times
                else "UncoveredLabel"
            ),
        }
    return coverage


def _gap_entries(coverage: dict[str, dict[str, Any]]) -> list[str]:
    entries = [ABSENCE_RULE, CADENCE_BASIS]
    if not coverage:
        entries.append(
            "no county rows matched the request; county coverage is UncoveredLabel"
        )
    for code, item in sorted(coverage.items()):
        if item["coverage_state"] != "complete_15_min_observation":
            entries.append(
                f"{code}: {item['coverage_state']}; missing "
                f"{item['missing_intervals']} of "
                f"{item['expected_intervals_at_15_min']} 15-minute intervals"
            )
    return entries


def _filters_text(
    states: set[str], fips: set[str], start: datetime, end: datetime
) -> str:
    counties = ",".join(sorted(fips)) if fips else "none (all counties in the states)"
    return (
        f"states={','.join(sorted(states))}; county_fips={counties}; "
        f"window=UTC half-open [{start.isoformat()}, {end.isoformat()})"
    )


def _units_text(customers_field: str, fieldnames: list[str]) -> str:
    parts = [f"{customers_field}: customers", "run_start_time: UTC"]
    if "total_customers" in fieldnames:
        parts.append("total_customers: customers")
    return "; ".join(parts)


def _duplicate_rows(valid_rows: list[dict[str, str]]) -> int:
    """Rows sharing a (county, timestamp) identity, independent of any filter set."""
    identities = {
        (row["fips_code"], parse_source_time(row["run_start_time"]))
        for row in valid_rows
    }
    return len(valid_rows) - len(identities)


def _valid_rows(
    selected: list[dict[str, str]], fieldnames: list[str], customers_field: str
) -> tuple[list[dict[str, str]], int]:
    valid_rows: list[dict[str, str]] = []
    invalid_rows = 0
    for row in selected:
        try:
            outage = int(row[customers_field])
            denominator = (
                int(row["total_customers"]) if "total_customers" in fieldnames else None
            )
            if outage < 0 or (denominator is not None and denominator <= 0):
                raise ValueError
        except (TypeError, ValueError):
            invalid_rows += 1
            continue
        valid_rows.append(row)
    return valid_rows, invalid_rows


def _write_receipt(cache_dir: Path, slug: str, payload: dict[str, Any]) -> None:
    (cache_dir / f"{slug}.receipt.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _slug(event_id: str | None, year: int, start: datetime, end: datetime) -> str:
    prefix = f"{event_id}_" if event_id else ""
    return f"{prefix}eaglei_{year}_{start:%Y%m%dT%H%M%S}_{end:%Y%m%dT%H%M%S}"


def _receipt_id(
    file_id: Any, year: int, start: datetime, end: datetime, event_id: str | None
) -> str:
    """An identifier matching event-baseline/v1 ``^[a-z0-9][a-z0-9_-]*$``."""
    parts = ["eaglei", str(year), str(file_id)]
    if event_id:
        parts.append(str(event_id))
    parts.append(f"{start:%Y%m%dt%H%M%S}")
    parts.append(f"{end:%Y%m%dt%H%M%S}")
    candidate = "-".join(parts).lower()
    candidate = re.sub(r"[^a-z0-9_-]+", "-", candidate).strip("-")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", candidate):
        raise EagleiError(f"cannot build a schema-valid receipt_id from {candidate!r}")
    return candidate


def acquire_exhaustive(
    *,
    article: dict[str, Any],
    file: dict[str, Any],
    event_id: str | None,
    year: int,
    start: datetime,
    end: datetime,
    states: set[str],
    fips: set[str],
    cache_dir: Path,
    expected_etag: str | None,
    selected_rows: list[dict[str, str]] | None = None,
    selected_fieldnames: list[str] | None = None,
    license_source: str = FIGSHARE_ARTICLE_URL,
) -> dict[str, Any]:
    """Filter a complete annual source file; only this path may establish gaps."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = cache_dir / "annual-source"
    raw_dir.mkdir(exist_ok=True)
    raw_path = raw_dir / file["name"]
    meta_path = raw_path.with_name(f"{raw_path.name}.source.json")
    source_url = str(file["download_url"])
    license_name, license_url = resolved_license(article)
    streamed = False
    if (
        not raw_path.exists()
        or raw_path.stat().st_size != int(file["size"])
        or not meta_path.exists()
    ):
        streamed = True
        response = requests.get(
            source_url, headers={"If-Match": expected_etag}, stream=True, timeout=120
        )
        response.raise_for_status()
        if response.status_code != 200 or response.headers.get("ETag") != expected_etag:
            raise EagleiError("annual source changed while streaming")
        part_path = raw_path.with_name(f"{raw_path.name}.part")
        written = 0
        with part_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1_048_576):
                if chunk:
                    written += len(chunk)
                    handle.write(chunk)
        if written != int(file["size"]):
            part_path.unlink(missing_ok=True)
            raise EagleiError(
                f"streamed {written} bytes but the Figshare file size is "
                f"{int(file['size'])}; refusing a truncated annual source"
            )
        os.replace(part_path, raw_path)
        meta_path.unlink(missing_ok=True)
    if not meta_path.exists():
        raw_bytes = raw_path.read_bytes()
        metadata = {
            "source_system_id": f"figshare:{article['id']}:{file['id']}",
            "source_file_id": str(file["id"]),
            "source_metadata_url": FIGSHARE_ARTICLE_URL,
            "source_url": source_url,
            "source_file": file["name"],
            "source_file_bytes": int(file["size"]),
            "raw_bytes": len(raw_bytes),
            "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "raw_md5": hashlib.md5(raw_bytes).hexdigest(),
            "supplied_md5": file.get("supplied_md5"),
            "computed_md5": file.get("computed_md5"),
            "etag": expected_etag,
            "license_name": license_name,
            "license_url": license_url,
            "license_source_url": license_source,
            "retrieved_at_utc": utc_now(),
            "http_status": 200,
            "acquisition_method": "exhaustive_annual_stream",
            "etag_pinned": True,
            "integrity_basis": "figshare_file_metadata_md5_and_size+etag_pinned_full_stream",
            "acquisition_complete": True,
        }
        meta_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    metadata = trusted_annual_metadata(raw_path, year=year, expected_file=file)
    observed_etag = metadata.get("etag")
    if expected_etag is not None and observed_etag != expected_etag:
        raise EagleiError(
            "cached annual source was fetched under ETag "
            f"{observed_etag!r} but {expected_etag!r} was requested; "
            "refusing to attest an ETag the cached bytes were not fetched under"
        )
    raw_hash = metadata["raw_sha256"]
    if selected_rows is None:
        with raw_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            selected = [
                row
                for row in reader
                if row["state"] in states
                and (not fips or row["fips_code"] in fips)
                and start <= parse_source_time(row["run_start_time"]) < end
            ]
    else:
        fieldnames = selected_fieldnames or []
        selected = selected_rows
    customers_field = outage_field(fieldnames)
    valid_rows, invalid_rows = _valid_rows(selected, fieldnames, customers_field)
    expected = expected_interval_times(start, end)
    # With no --fips filter the receipt still has to say what it covered, so fall
    # back to the FIPS actually observed rather than emitting an empty mapping.
    report_fips = sorted(fips or {row["fips_code"] for row in valid_rows})
    coverage = _coverage_report(valid_rows, report_fips, expected)
    slug = _slug(event_id, year, start, end)
    selected_path = cache_dir / f"{slug}.csv"
    with selected_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected)
    filtered_hash = hashlib.sha256(selected_path.read_bytes()).hexdigest()
    detail = {
        "event_id": event_id,
        "source_system_id": f"figshare:{article['id']}:{file['id']}",
        "source_file": file["name"],
        "source_file_bytes": int(file["size"]),
        "license_name": license_name,
        "license_url": license_url,
        "license_source_url": license_source,
        "acquisition_method": "exhaustive_annual_stream",
        "acquisition_complete": True,
        "raw_artifact": str(raw_path),
        "raw_metadata_artifact": str(meta_path),
        "raw_sha256": raw_hash,
        "raw_bytes": metadata["raw_bytes"],
        "etag": observed_etag,
        "filtered_artifact": str(selected_path),
        "filtered_rows": len(selected),
        "valid_selected_rows": len(valid_rows),
        "invalid_selected_rows": invalid_rows,
        "duplicate_selected_rows": _duplicate_rows(valid_rows),
        "source_columns": fieldnames,
        "outage_field_source": customers_field,
        "source_row_identity": ["fips_code", "run_start_time"],
        "source_time_basis": SOURCE_TIMEZONE,
        "source_time_basis_url": TIME_BASIS_SOURCE_URL,
        "sample_cadence_seconds": SOURCE_INTERVAL_SECONDS,
        "sample_cadence_basis": CADENCE_BASIS,
        "requested_utc_half_open": {"start": start.isoformat(), "end": end.isoformat()},
        "state_filter": sorted(states),
        "county_fips_filter": sorted(fips),
        "reported_county_fips": report_fips,
        "coverage_by_county": coverage,
        "coverage_summary": "Available" if coverage else "UncoveredLabel",
        "total_customers_summary": (
            {
                code: {
                    "present_rows": sum(
                        1 for row in valid_rows if row["fips_code"] == code
                    ),
                    "missing_rows": sum(
                        1 for row in selected if row["fips_code"] == code
                    )
                    - sum(1 for row in valid_rows if row["fips_code"] == code),
                    "min": min(
                        (
                            int(row["total_customers"])
                            for row in valid_rows
                            if row["fips_code"] == code
                        ),
                        default=None,
                    ),
                    "max": max(
                        (
                            int(row["total_customers"])
                            for row in valid_rows
                            if row["fips_code"] == code
                        ),
                        default=None,
                    ),
                }
                for code in report_fips
            }
            if "total_customers" in fieldnames
            else None
        ),
        "customer_denominator": (
            "native source total_customers only; no population substitution"
            if "total_customers" in fieldnames
            else "unavailable; no population substitution"
        ),
        "absence_rule": ABSENCE_RULE,
    }
    capture_method = "exhaustive_annual_stream"
    contract_verification = {
        "sha256_computed_from_response_body": True,
        "row_count_checked": True,
        "notes": "Complete annual bytes were rehashed against the trusted manifest before filtering.",
    }
    acquisition = {
        "acquisition_complete": True,
        "acquisition_method": capture_method,
        "source_system_id": detail["source_system_id"],
        "source_file": file["name"],
        "source_file_id": file["id"],
        "source_file_bytes": int(file["size"]),
        "integrity_basis": metadata["integrity_basis"],
        "raw_artifact_uri": str(raw_path),
        "raw_artifact_sha256": raw_hash,
        "source_sidecar_uri": str(meta_path),
        "source_sidecar_sha256": hashlib.sha256(meta_path.read_bytes()).hexdigest(),
        "filtered_artifact_uri": str(selected_path),
        "filtered_artifact_sha256": filtered_hash,
    }
    payload = {
        "receipt": {
            "receipt_id": _receipt_id(file["id"], year, start, end, event_id),
            "provider": PROVIDER,
            "url": source_url,
            "release": FIGSHARE_DOI,
            "retrieved_at_utc": utc_now(),
            "license_or_access": _license_text(
                license_name, license_url, license_source
            ),
            "raw_sha256": raw_hash,
            "filtered_sha256": filtered_hash,
            "bytes": metadata["raw_bytes"],
            "etag": observed_etag,
            "units": _units_text(customers_field, fieldnames),
            "timezone_conversion": "none; EAGLE-I documentation states run_start_time is UTC",
            "filters": _filters_text(states, fips, start, end),
            "grid_index_mapping": (
                "none; EAGLE-I rows are keyed by county FIPS, not a model grid index"
            ),
            "gaps": _gap_entries(coverage),
            "acquisition": acquisition,
            "capture_method": capture_method,
            "verification": contract_verification,
            "files": {
                "annual_source": {
                    "url": source_url,
                    "bytes": metadata["raw_bytes"],
                    "sha256": raw_hash,
                },
                "filtered_selection": {
                    "url": str(selected_path),
                    "bytes": selected_path.stat().st_size,
                    "sha256": filtered_hash,
                },
            },
            "uncertainty": (
                "Complete annual source was filtered for the requested half-open "
                "window; missing source rows remain UncoveredLabel rather than zero."
            ),
        },
        "capture_method": capture_method,
        "verification": {
            "streamed_this_run": streamed,
            "streamed_bytes_matched_source_size": streamed or None,
            "cached_bytes_rehashed_against_manifest": True,
            "manifest_etag_matched_requested_etag": expected_etag is not None,
            "etag_reported_is_the_etag_the_bytes_were_fetched_under": True,
            "content_range_matched_request": None,
            "sha256_computed_from_stored_bytes": True,
            "bytes_transferred_over_the_wire": (int(file["size"]) if streamed else 0),
        },
        "eaglei": detail,
    }
    _write_receipt(cache_dir, slug, payload)
    return payload


def _row_matches(
    row: dict[str, str], request: dict[str, Any], timestamp: datetime
) -> bool:
    """Apply the state and half-open-window portion of a batch request."""
    return (
        row["state"] in request["states"]
        and request["start"] <= timestamp < request["end"]
    )


def batch_scan_requests(requests_path: Path, cache_dir: Path) -> list[dict[str, Any]]:
    """Scan each cached annual CSV once and dispatch rows to requested windows."""
    payload = json.loads(requests_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if payload.get("request_schema_version") != "flux-460-final-requests/v1":
            raise EagleiError("requests JSON has an unsupported schema version")
        requests_data = payload.get("requests")
    else:
        requests_data = payload
    if not isinstance(requests_data, list):
        raise EagleiError("requests JSON must be a list")
    grouped: dict[int, list[dict[str, Any]]] = {}
    for request in requests_data:
        request["start"] = parse_source_time(
            request["start"].replace("T", " ").removesuffix("Z")
        )
        request["end"] = parse_source_time(
            request["end"].replace("T", " ").removesuffix("Z")
        )
        request["fips"] = {str(code).zfill(5) for code in request["fips"]}
        request["states"] = set(request["states"])
        request["rows"] = []
        grouped.setdefault(int(request["year"]), []).append(request)
    results = []
    for year, group in grouped.items():
        raw_path = cache_dir / "annual-source" / f"eaglei_outages_{year}.csv"
        if not raw_path.exists():
            raise EagleiError(f"missing completed annual source: {raw_path}")
        meta = trusted_annual_metadata(raw_path, year=year)
        # Licence terms come from what the fetch recorded, never from a constant.
        license_name, license_url, license_source = manifest_license(meta)
        source_system_id = str(meta["source_system_id"])
        article_id, file_id = source_system_id.split(":")[1:3]
        requests_by_fips: dict[str, list[dict[str, Any]]] = {}
        unrestricted_requests: list[dict[str, Any]] = []
        for request in group:
            if request["fips"]:
                for code in request["fips"]:
                    requests_by_fips.setdefault(code, []).append(request)
            else:
                unrestricted_requests.append(request)
        with raw_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            batch_fieldnames = reader.fieldnames or []
            for row in reader:
                ts = parse_source_time(row["run_start_time"])
                candidates = requests_by_fips.get(row["fips_code"], [])
                for request in [*candidates, *unrestricted_requests]:
                    if _row_matches(row, request, ts):
                        request["rows"].append(row)
        for request in group:
            file = {
                "id": file_id,
                "name": raw_path.name,
                "size": raw_path.stat().st_size,
                "supplied_md5": meta["supplied_md5"],
                "computed_md5": meta["computed_md5"],
                "download_url": meta.get("source_url", "cached://annual-source"),
            }
            article = {
                "id": article_id,
                "license": {"name": license_name, "url": license_url},
            }
            results.append(
                acquire_exhaustive(
                    article=article,
                    file=file,
                    event_id=request["event_id"],
                    year=year,
                    start=request["start"],
                    end=request["end"],
                    states=request["states"],
                    fips=request["fips"],
                    cache_dir=cache_dir,
                    expected_etag=meta.get("etag"),
                    selected_rows=request["rows"],
                    selected_fieldnames=batch_fieldnames,
                    license_source=license_source,
                )
            )
    return results


def probe_at(
    session: requests.Session,
    url: str,
    offset: int,
    size: int,
    fieldnames: list[str],
    expected_etag: str,
    budget: ByteBudget | None = None,
) -> tuple[list[dict[str, str]], RangeReceipt]:
    payload, receipt = _range_get(
        session, url, offset, offset + size - 1, expected_etag, budget=budget
    )
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
    budget: ByteBudget | None = None,
) -> tuple[int, list[RangeReceipt]]:
    """Binary-search a time-ordered file and return a nearby byte offset."""
    lo, hi = 0, size - PROBE_BYTES
    receipts: list[RangeReceipt] = []
    for _ in range(32):
        if hi - lo <= PROBE_BYTES:
            return lo, receipts
        middle = ((lo + hi) // 2) // PROBE_BYTES * PROBE_BYTES
        rows, receipt = probe_at(
            session, url, middle, PROBE_BYTES, fieldnames, expected_etag, budget=budget
        )
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
    allow_full_download: bool = True,
    max_bytes: int = DEFAULT_MAX_BOUNDED_BYTES,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Acquire a slice from a verified complete annual source by default."""
    if start >= end:
        raise ValueError("start must precede end")
    session = session if session is not None else requests.Session()
    article_response = session.get(FIGSHARE_ARTICLE_URL, timeout=30)
    article_response.raise_for_status()
    article = article_response.json()
    file = annual_file(article, year)
    source_size = int(file["size"])
    source_url = str(file["download_url"])
    license_name, license_url = resolved_license(article)
    budget = None if allow_full_download else ByteBudget(max_bytes)
    fieldnames, header_receipt = source_columns(session, source_url, budget=budget)
    customers_out_field = outage_field(fieldnames)
    if not header_receipt.etag:
        raise EagleiError(
            "source response omitted ETag; cannot pin a multi-range acquisition"
        )
    content_total = int((header_receipt.content_range or "").rsplit("/", 1)[-1])
    if content_total != source_size:
        raise EagleiError(
            "HTTP Content-Range total differs from Figshare catalog byte size"
        )
    if allow_full_download:
        return acquire_exhaustive(
            article=article,
            file=file,
            event_id=event_id,
            year=year,
            start=start,
            end=end,
            states=states,
            fips=fips,
            cache_dir=cache_dir,
            expected_etag=header_receipt.etag,
        )

    assert budget is not None
    start_offset, start_probes = locate_time(
        session,
        source_url,
        source_size,
        start,
        fieldnames,
        header_receipt.etag,
        budget=budget,
    )
    end_offset, end_probes = locate_time(
        session,
        source_url,
        source_size,
        end,
        fieldnames,
        header_receipt.etag,
        budget=budget,
    )
    raw_start = max(0, start_offset - 2 * PROBE_BYTES)
    raw_end = min(source_size - 1, end_offset + 3 * PROBE_BYTES - 1)
    payload, raw_receipt = _range_get(
        session, source_url, raw_start, raw_end, header_receipt.etag, budget=budget
    )
    rows = _complete_csv_rows(payload, fieldnames)
    expected_times = expected_interval_times(start, end)
    raw_times = {parse_source_time(row["run_start_time"]) for row in rows}
    if not raw_times or min(raw_times) > start or max(raw_times) < max(expected_times):
        raise EagleiError(
            "final range does not bracket requested window; acquisition may be truncated"
        )
    selected = [
        row
        for row in rows
        if row["state"] in states
        and (not fips or row["fips_code"] in fips)
        and start <= parse_source_time(row["run_start_time"]) < end
    ]
    valid_rows, invalid_rows = _valid_rows(selected, fieldnames, customers_out_field)
    report_fips = sorted(fips or {row["fips_code"] for row in valid_rows})
    observed_coverage = _coverage_report(valid_rows, report_fips, expected_times)
    # The bounded path cannot prove that its byte slice represents all source
    # rows for a window.  Keep the rows it did observe as diagnostics, but do
    # not turn a slice-local absence into an UncoveredLabel or a coverage claim.
    coverage = {
        code: {
            "availability": "Unknown",
            "coverage_state": "not_assessed_from_bounded_range",
            "observed_intervals_in_retrieved_rows": item["observed_intervals"],
            "expected_intervals_at_15_min": item["expected_intervals_at_15_min"],
        }
        for code, item in observed_coverage.items()
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
        for code in report_fips
    }

    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(event_id, year, start, end)
    csv_path = cache_dir / f"{slug}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected)
    filtered_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    detail = {
        "event_id": event_id,
        "source_system_id": f"figshare:{article['id']}:{file['id']}",
        "source_title": article.get("title"),
        "source_doi": FIGSHARE_DOI,
        "source_file": file["name"],
        "source_file_bytes": source_size,
        "license_name": license_name,
        "license_url": license_url,
        "license_source_url": FIGSHARE_ARTICLE_URL,
        "acquisition_method": "bounded_http_range_binary_search",
        "acquisition_complete": False,
        "byte_ceiling": budget.limit,
        "bytes_transferred": budget.spent,
        "source_time_basis": SOURCE_TIMEZONE,
        "source_time_basis_url": TIME_BASIS_SOURCE_URL,
        "sample_cadence_seconds": SOURCE_INTERVAL_SECONDS,
        "sample_cadence_basis": CADENCE_BASIS,
        "requested_utc_half_open": {"start": start.isoformat(), "end": end.isoformat()},
        "state_filter": sorted(states),
        "county_fips_filter": sorted(fips),
        "reported_county_fips": report_fips,
        "header_range": header_receipt.__dict__,
        "source_columns": fieldnames,
        "range_probes": [item.__dict__ for item in start_probes + end_probes],
        "raw_range": raw_receipt.__dict__,
        "raw_sha256": raw_receipt.sha256,
        "raw_bytes": raw_receipt.bytes_received,
        "etag": raw_receipt.etag,
        "filtered_artifact": str(csv_path),
        "filtered_bytes": csv_path.stat().st_size,
        "filtered_rows": len(selected),
        "valid_selected_rows": len(valid_rows),
        "invalid_selected_rows": invalid_rows,
        "duplicate_selected_rows": _duplicate_rows(valid_rows),
        "source_row_identity": ["fips_code", "run_start_time"],
        "reported_timestamp_min": min(
            (row["run_start_time"] for row in selected), default=None
        ),
        "reported_timestamp_max": max(
            (row["run_start_time"] for row in selected), default=None
        ),
        "coverage_by_county": coverage,
        "coverage_summary": "Unknown",
        "customers_out_summary": {
            code: {
                "min": min(
                    (
                        int(row[customers_out_field])
                        for row in valid_rows
                        if row["fips_code"] == code
                    ),
                    default=None,
                ),
                "max": max(
                    (
                        int(row[customers_out_field])
                        for row in valid_rows
                        if row["fips_code"] == code
                    ),
                    default=None,
                ),
            }
            for code in report_fips
        },
        "total_customers_summary": (
            denominator_summary if "total_customers" in fieldnames else None
        ),
        "outage_field_source": customers_out_field,
        "outage_field_semantics": (
            "total customers without electricity at the source timestamp"
        ),
        "customer_denominator": (
            "native `total_customers` present in selected rows; retain per-row values and missingness"
            if "total_customers" in fieldnames and selected
            else "native `total_customers` is in the annual source schema but no selected observations were emitted"
            if "total_customers" in fieldnames
            else "unavailable in this annual slice; do not substitute population"
        ),
        "absence_rule": (
            "A bounded byte slice cannot characterize missing rows; no source "
            "absence or coverage classification is emitted."
        ),
    }
    result = {
        "receipt": {
            "receipt_id": _receipt_id(file["id"], year, start, end, event_id),
            "provider": PROVIDER,
            "url": source_url,
            "release": FIGSHARE_DOI,
            "retrieved_at_utc": utc_now(),
            "license_or_access": _license_text(
                license_name, license_url, FIGSHARE_ARTICLE_URL
            ),
            "raw_sha256": raw_receipt.sha256,
            "filtered_sha256": filtered_hash,
            "bytes": raw_receipt.bytes_received,
            "etag": raw_receipt.etag,
            "units": _units_text(customers_out_field, fieldnames),
            "timezone_conversion": "none; EAGLE-I documentation states run_start_time is UTC",
            "filters": _filters_text(states, fips, start, end),
            "grid_index_mapping": (
                "none; EAGLE-I rows are keyed by county FIPS, not a model grid index"
            ),
            "gaps": [
                (
                    "bounded range acquisition: only the bracketed byte range was read, "
                    "so source coverage and absence are not assessed"
                ),
            ],
            "acquisition": None,
            "capture_method": "bounded_http_range_binary_search",
            "verification": {
                "sha256_computed_from_response_body": True,
                "content_range_matched_request": True,
                "row_count_checked": True,
                "notes": "Every response was ETag-pinned and range-validated; this is exploratory only.",
            },
            "files": {
                "bounded_raw_range": {
                    "url": source_url,
                    "bytes": raw_receipt.bytes_received,
                    "sha256": raw_receipt.sha256,
                    "range": raw_receipt.content_range,
                },
                "filtered_selection": {
                    "url": str(csv_path),
                    "bytes": csv_path.stat().st_size,
                    "sha256": filtered_hash,
                },
            },
            "uncertainty": (
                "A bounded byte-range probe cannot establish event coverage or "
                "source absence, especially for FIPS-major annual layouts."
            ),
        },
        "capture_method": "bounded_http_range_binary_search",
        "verification": {
            "content_range_matched_request": True,
            "sha256_computed_from_response_body": True,
            "etag_pinned_across_every_range": True,
            "range_probe_count": len(start_probes) + len(end_probes),
            "bytes_transferred_over_the_wire": budget.spent,
            "byte_ceiling": budget.limit,
            "requested_window_bracketed_by_retrieved_rows": True,
            "full_annual_file_streamed": False,
        },
        "eaglei": detail,
    }
    _write_receipt(cache_dir, slug, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int)
    parser.add_argument(
        "--requests-json",
        type=Path,
        help="batch request list; scans each cached annual source once",
    )
    parser.add_argument(
        "--event-id",
        help="stable caller event identifier; used only in cache artifact names and receipt",
    )
    parser.add_argument(
        "--start-source-clock",
        required=False,
        help="UTC YYYY-MM-DDTHH:MM:SS; EAGLE-I documents run_start_time as UTC",
    )
    parser.add_argument("--end-source-clock", help="exclusive UTC YYYY-MM-DDTHH:MM:SS")
    parser.add_argument(
        "--states",
        required=False,
        help="comma-separated EAGLE-I state names, e.g. Minnesota,Wisconsin",
    )
    parser.add_argument(
        "--fips",
        default="",
        help="optional comma-separated county FIPS; when absent the receipt reports "
        "the counties actually observed and marks empty selections UncoveredLabel",
    )
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument(
        "--bounded-http-range",
        action="store_true",
        help="exploratory bounded range read; never establishes source coverage",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BOUNDED_BYTES,
        help="byte ceiling for --bounded-http-range (ignored by exhaustive default)",
    )
    args = parser.parse_args()
    if args.requests_json:
        print(
            json.dumps(
                batch_scan_requests(args.requests_json, args.cache_dir),
                indent=2,
                sort_keys=True,
            )
        )
        return
    if not all(
        (args.year, args.start_source_clock, args.end_source_clock, args.states)
    ):
        parser.error(
            "--year, --start-source-clock, --end-source-clock, and --states are required without --requests-json"
        )
    receipt = acquire(
        event_id=args.event_id,
        year=args.year,
        start=parse_source_time(args.start_source_clock.replace("T", " ")),
        end=parse_source_time(args.end_source_clock.replace("T", " ")),
        states={state.strip() for state in args.states.split(",") if state.strip()},
        fips={code.strip().zfill(5) for code in args.fips.split(",") if code.strip()},
        cache_dir=args.cache_dir,
        allow_full_download=not args.bounded_http_range,
        max_bytes=args.max_bytes,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

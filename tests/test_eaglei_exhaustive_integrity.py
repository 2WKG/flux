"""Regression checks for exhaustive, provenance-preserving EAGLE-I acquisition."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import scripts.event_baseline.acquire_eaglei as eaglei

HEADER = (
    "fips_code,county,state,customers_out,run_start_time,total_customers\n"
)
START = datetime(2024, 6, 19, tzinfo=UTC)
END = datetime(2024, 6, 19, 1, tzinfo=UTC)


def _article() -> dict[str, object]:
    return {"id": 24237376, "license": {"name": "CC BY 4.0"}}


def _file(payload: bytes) -> dict[str, object]:
    return {
        "id": 53581661,
        "name": "eaglei_outages_2024.csv",
        "size": len(payload),
        "supplied_md5": hashlib.md5(payload).hexdigest(),
        "computed_md5": hashlib.md5(payload).hexdigest(),
        "download_url": "https://example.invalid/eaglei_outages_2024.csv",
    }


def _write_completed_source(
    cache_dir: Path, payload: bytes, *, etag: str = '"source-v1"'
) -> Path:
    raw_dir = cache_dir / "annual-source"
    raw_dir.mkdir()
    raw = raw_dir / "eaglei_outages_2024.csv"
    raw.write_bytes(payload)
    (raw_dir / f"{raw.name}.source.json").write_text(
        json.dumps(
            {
                "source_system_id": "figshare:24237376:53581661",
                "source_file_id": "53581661",
                "source_metadata_url": eaglei.FIGSHARE_ARTICLE_URL,
                "source_url": "https://example.invalid/eaglei_outages_2024.csv",
                "source_file": raw.name,
                "source_file_bytes": len(payload),
                "raw_bytes": len(payload),
                "raw_sha256": hashlib.sha256(payload).hexdigest(),
                "raw_md5": hashlib.md5(payload).hexdigest(),
                "supplied_md5": hashlib.md5(payload).hexdigest(),
                "computed_md5": hashlib.md5(payload).hexdigest(),
                "etag": etag,
                "etag_pinned": True,
                "retrieved_at_utc": "2026-09-06T00:00:00Z",
                "http_status": 200,
                "acquisition_method": "exhaustive_annual_stream",
                "acquisition_complete": True,
                "integrity_basis": "figshare_file_metadata_md5_and_size+etag_pinned_full_stream",
            }
        ),
        encoding="utf-8",
    )
    return raw


def _rows(path: str) -> list[dict[str, str]]:
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle))


def _acquire(cache_dir: Path, payload: bytes) -> dict[str, object]:
    return eaglei.acquire_exhaustive(
        article=_article(),
        file=_file(payload),
        event_id="unsorted",
        year=2024,
        start=START,
        end=END,
        states={"Minnesota"},
        fips={"27137"},
        cache_dir=cache_dir,
        expected_etag='"source-v1"',
    )


def test_unsorted_fips_major_source_produces_complete_filtered_receipt(tmp_path: Path) -> None:
    """Rows far apart in a FIPS-major source still belong to the same event slice."""
    payload = (
        HEADER
        + "06001,Alameda,California,8,2024-12-31 23:45:00,999\n"
        + "27137,St Louis,Minnesota,3,2024-06-19 00:00:00,123\n"
        + "06001,Alameda,California,9,2024-01-01 00:00:00,999\n"
        + "27137,St Louis,Minnesota,4,2024-06-19 00:15:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:30:00,123\n"
        + "27137,St Louis,Minnesota,6,2024-06-19 00:45:00,123\n"
    ).encode()
    _write_completed_source(tmp_path, payload)

    receipt = _acquire(tmp_path, payload)

    assert receipt["acquisition_complete"] is True
    assert receipt["raw_bytes"] == receipt["source_file_bytes"] == len(payload)
    assert receipt["raw_sha256"] == hashlib.sha256(payload).hexdigest()
    assert receipt["coverage_by_county"]["27137"]["coverage_state"] == "complete_15_min_observation"
    assert [row["customers_out"] for row in _rows(receipt["filtered_artifact"])] == [
        "3",
        "4",
        "5",
        "6",
    ]


@pytest.mark.parametrize(
    ("outage", "denominator"),
    [("", "123"), ("-1", "123"), ("not-a-number", "123"), ("5", ""), ("5", "0"), ("5", "not-a-number")],
)
def test_invalid_native_numeric_values_never_make_a_complete_observation(
    tmp_path: Path, outage: str, denominator: str
) -> None:
    payload = (
        HEADER
        + f"27137,St Louis,Minnesota,{outage},2024-06-19 00:00:00,{denominator}\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:30:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:45:00,123\n"
    ).encode()
    _write_completed_source(tmp_path, payload)

    receipt = _acquire(tmp_path, payload)

    coverage = receipt["coverage_by_county"]["27137"]
    assert coverage["coverage_state"] == "partial_15_min_observation"
    assert coverage["observed_intervals"] == 3
    assert receipt["invalid_selected_rows"] == 1


def test_duplicate_timestamp_cannot_be_inflated_to_complete_coverage(tmp_path: Path) -> None:
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,6,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:30:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:45:00,123\n"
    ).encode()
    _write_completed_source(tmp_path, payload)

    receipt = _acquire(tmp_path, payload)

    coverage = receipt["coverage_by_county"]["27137"]
    assert coverage["coverage_state"] != "complete_15_min_observation"
    assert receipt["duplicate_selected_rows"] == 1


def test_receipt_preserves_native_denominator_values_and_per_county_summary(
    tmp_path: Path,
) -> None:
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,124\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:30:00,125\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:45:00,126\n"
    ).encode()
    _write_completed_source(tmp_path, payload)

    receipt = _acquire(tmp_path, payload)

    assert [row["total_customers"] for row in _rows(receipt["filtered_artifact"])] == [
        "123",
        "124",
        "125",
        "126",
    ]
    summary = receipt["total_customers_summary"]["27137"]
    assert summary == {
        "present_rows": 4,
        "missing_rows": 0,
        "min": 123,
        "max": 126,
    }
    assert "no population substitution" in receipt["customer_denominator"]


def test_same_size_raw_cache_without_matching_metadata_is_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desired = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:30:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:45:00,123\n"
    ).encode()
    stale = desired.replace(b",5,", b",9,")
    assert len(stale) == len(desired)
    raw_dir = tmp_path / "annual-source"
    raw_dir.mkdir()
    (raw_dir / "eaglei_outages_2024.csv").write_bytes(stale)
    (raw_dir / "eaglei_outages_2024.csv.source.json").write_text(
        json.dumps({"raw_sha256": hashlib.sha256(stale).hexdigest(), "etag": '"old"'}),
        encoding="utf-8",
    )

    class Response:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers = {"ETag": '"source-v1"'}

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            yield desired

    calls: list[object] = []
    monkeypatch.setattr(eaglei.requests, "get", lambda *args, **kwargs: calls.append((args, kwargs)) or Response())

    try:
        receipt = _acquire(tmp_path, desired)
    except eaglei.EagleiError as error:
        assert (
            "sidecar" in str(error)
            or "cache" in str(error)
            or "manifest" in str(error)
        )
        assert not calls, "untrusted bytes must not be silently reused"
    else:
        assert calls, "a stale same-size cache must be refreshed before use"
        assert Path(receipt["raw_artifact"]).read_bytes() == desired
        assert receipt["raw_sha256"] == hashlib.sha256(desired).hexdigest()


def test_partial_or_unproven_annual_source_is_rejected_by_batch(tmp_path: Path) -> None:
    raw_dir = tmp_path / "annual-source"
    raw_dir.mkdir()
    (raw_dir / "eaglei_outages_2024.csv.part").write_bytes(HEADER.encode())
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps(
            [
                {
                    "event_id": "event",
                    "year": 2024,
                    "start": "2024-06-19T00:00:00Z",
                    "end": "2024-06-19T01:00:00Z",
                    "states": ["Minnesota"],
                    "fips": ["27137"],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(eaglei.EagleiError, match="completed annual source"):
        eaglei.batch_scan_requests(requests_path, tmp_path)


def test_batch_emits_full_receipts_and_selected_csv_equivalent_to_single_scan(
    tmp_path: Path,
) -> None:
    payload = (
        HEADER
        + "06001,Alameda,California,8,2024-12-31 23:45:00,999\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:30:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:45:00,123\n"
    ).encode()
    _write_completed_source(tmp_path, payload)
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps(
            [
                {
                    "event_id": "batch-event",
                    "year": 2024,
                    "start": "2024-06-19T00:00:00Z",
                    "end": "2024-06-19T01:00:00Z",
                    "states": ["Minnesota"],
                    "fips": ["27137"],
                }
            ]
        ),
        encoding="utf-8",
    )

    receipt = eaglei.batch_scan_requests(requests_path, tmp_path)[0]

    assert receipt["event_id"] == "batch-event"
    assert receipt["acquisition_complete"] is True
    assert receipt["raw_sha256"] == hashlib.sha256(payload).hexdigest()
    assert receipt["coverage_by_county"]["27137"]["coverage_state"] == "complete_15_min_observation"
    assert Path(receipt["filtered_artifact"]).exists()
    assert [row["total_customers"] for row in _rows(receipt["filtered_artifact"])] == [
        "123",
        "123",
        "123",
        "123",
    ]


def test_batch_verifies_trusted_sidecar_before_opening_a_csv_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:30:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:45:00,123\n"
    ).encode()
    raw = _write_completed_source(tmp_path, payload)
    sidecar = raw.with_name(f"{raw.name}.source.json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata["raw_sha256"] = "0" * 64
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps(
            [
                {
                    "event_id": "untrusted",
                    "year": 2024,
                    "start": "2024-06-19T00:00:00Z",
                    "end": "2024-06-19T01:00:00Z",
                    "states": ["Minnesota"],
                    "fips": ["27137"],
                }
            ]
        ),
        encoding="utf-8",
    )
    original_reader = eaglei.csv.DictReader

    def forbidden_reader(*args: object, **kwargs: object) -> object:
        raise AssertionError("an untrusted annual source reached CSV parsing")

    monkeypatch.setattr(eaglei.csv, "DictReader", forbidden_reader)

    with pytest.raises(eaglei.EagleiError, match="sidecar|cache|metadata|manifest"):
        eaglei.batch_scan_requests(requests_path, tmp_path)

    monkeypatch.setattr(eaglei.csv, "DictReader", original_reader)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("acquisition_complete", False),
        ("source_system_id", "figshare:other-article:53581661"),
        ("source_file", "different.csv"),
        ("source_file_bytes", 0),
        ("integrity_basis", "none"),
        ("raw_md5", "0" * 32),
        ("supplied_md5", "0" * 32),
        ("computed_md5", "0" * 32),
    ],
)
def test_batch_rejects_an_incomplete_or_unbound_manifest_before_csv_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid_value: object,
) -> None:
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
    ).encode()
    raw = _write_completed_source(tmp_path, payload)
    sidecar = raw.with_name(f"{raw.name}.source.json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata[field] = invalid_value
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps(
            [
                {
                    "event_id": "untrusted",
                    "year": 2024,
                    "start": "2024-06-19T00:00:00Z",
                    "end": "2024-06-19T00:30:00Z",
                    "states": ["Minnesota"],
                    "fips": ["27137"],
                }
            ]
        ),
        encoding="utf-8",
    )

    def forbidden_reader(*args: object, **kwargs: object) -> object:
        raise AssertionError("an untrusted annual source reached CSV parsing")

    monkeypatch.setattr(eaglei.csv, "DictReader", forbidden_reader)

    with pytest.raises(eaglei.EagleiError, match="sidecar|cache|metadata|manifest"):
        eaglei.batch_scan_requests(requests_path, tmp_path)


def test_two_same_year_batch_requests_parse_the_annual_csv_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:30:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:45:00,123\n"
    ).encode()
    raw = _write_completed_source(tmp_path, payload)
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps(
            [
                {
                    "event_id": "first",
                    "year": 2024,
                    "start": "2024-06-19T00:00:00Z",
                    "end": "2024-06-19T00:30:00Z",
                    "states": ["Minnesota"],
                    "fips": ["27137"],
                },
                {
                    "event_id": "second",
                    "year": 2024,
                    "start": "2024-06-19T00:30:00Z",
                    "end": "2024-06-19T01:00:00Z",
                    "states": ["Minnesota"],
                    "fips": ["27137"],
                },
            ]
        ),
        encoding="utf-8",
    )
    original_reader = eaglei.csv.DictReader
    parse_count = 0

    def counting_reader(*args: object, **kwargs: object) -> object:
        nonlocal parse_count
        handle = args[0]
        if Path(handle.name) == raw:
            parse_count += 1
        return original_reader(*args, **kwargs)

    monkeypatch.setattr(eaglei.csv, "DictReader", counting_reader)

    receipts = eaglei.batch_scan_requests(requests_path, tmp_path)

    assert parse_count == 1
    assert [receipt["event_id"] for receipt in receipts] == ["first", "second"]
    assert all(receipt["acquisition_complete"] for receipt in receipts)

"""Regression checks for exhaustive, provenance-preserving EAGLE-I acquisition."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest

import scripts.event_baseline.acquire_eaglei as eaglei

HEADER = "fips_code,county,state,customers_out,run_start_time,total_customers\n"
START = datetime(2024, 6, 19, tzinfo=UTC)
END = datetime(2024, 6, 19, 1, tzinfo=UTC)


def _article() -> dict[str, object]:
    return {
        "id": 24237376,
        "license": {"name": "CC BY 4.0", "url": eaglei.LICENSE_URL},
    }


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
    cache_dir: Path,
    payload: bytes,
    *,
    etag: str = '"source-v1"',
    license_fields: bool = True,
) -> Path:
    raw_dir = cache_dir / "annual-source"
    raw_dir.mkdir()
    raw = raw_dir / "eaglei_outages_2024.csv"
    raw.write_bytes(payload)
    metadata: dict[str, object] = {
        "source_system_id": "figshare:24237376:53581661",
        "source_file_id": 53581661,
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
    if license_fields:
        metadata["license_name"] = "CC BY 4.0"
        metadata["license_url"] = eaglei.LICENSE_URL
        metadata["license_source_url"] = eaglei.FIGSHARE_ARTICLE_URL
    (raw_dir / f"{raw.name}.source.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    return raw


def _rows(path: str) -> list[dict[str, str]]:
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle))


def _acquire(
    cache_dir: Path,
    payload: bytes,
    *,
    fips: set[str] | None = None,
    expected_etag: str | None = '"source-v1"',
) -> dict[str, object]:
    return eaglei.acquire_exhaustive(
        article=_article(),
        file=_file(payload),
        event_id="unsorted",
        year=2024,
        start=START,
        end=END,
        states={"Minnesota"},
        fips={"27137"} if fips is None else fips,
        cache_dir=cache_dir,
        expected_etag=expected_etag,
    )


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("a cached-source path must not reach the network")

    monkeypatch.setattr(eaglei.requests, "get", forbidden)


def test_unsorted_fips_major_source_produces_complete_filtered_receipt(
    tmp_path: Path,
) -> None:
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

    result = _acquire(tmp_path, payload)
    detail = result["eaglei"]

    assert detail["acquisition_complete"] is True
    assert detail["raw_bytes"] == detail["source_file_bytes"] == len(payload)
    assert result["receipt"]["raw_sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["receipt"]["bytes"] == len(payload)
    assert (
        detail["coverage_by_county"]["27137"]["coverage_state"]
        == "complete_15_min_observation"
    )
    assert [row["customers_out"] for row in _rows(detail["filtered_artifact"])] == [
        "3",
        "4",
        "5",
        "6",
    ]


@pytest.mark.parametrize(
    ("outage", "denominator"),
    [
        ("", "123"),
        ("-1", "123"),
        ("not-a-number", "123"),
        ("5", ""),
        ("5", "0"),
        ("5", "not-a-number"),
    ],
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

    detail = _acquire(tmp_path, payload)["eaglei"]

    coverage = detail["coverage_by_county"]["27137"]
    assert coverage["coverage_state"] == "partial_15_min_observation"
    assert coverage["observed_intervals"] == 3
    assert detail["invalid_selected_rows"] == 1


def test_duplicate_timestamp_cannot_be_inflated_to_complete_coverage(
    tmp_path: Path,
) -> None:
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,6,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:30:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:45:00,123\n"
    ).encode()
    _write_completed_source(tmp_path, payload)

    detail = _acquire(tmp_path, payload)["eaglei"]

    coverage = detail["coverage_by_county"]["27137"]
    assert coverage["coverage_state"] != "complete_15_min_observation"
    assert detail["duplicate_selected_rows"] == 1


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

    detail = _acquire(tmp_path, payload)["eaglei"]

    assert [row["total_customers"] for row in _rows(detail["filtered_artifact"])] == [
        "123",
        "124",
        "125",
        "126",
    ]
    summary = detail["total_customers_summary"]["27137"]
    assert summary == {
        "present_rows": 4,
        "missing_rows": 0,
        "min": 123,
        "max": 126,
    }
    assert "no population substitution" in detail["customer_denominator"]


# --- audit falsifiability: the ETag the receipt attests must be the ETag the
# --- cached bytes were actually fetched under (review finding #2 on PR #231).


def test_cache_hit_refuses_to_attest_an_etag_the_bytes_were_not_fetched_under(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
    ).encode()
    _write_completed_source(tmp_path, payload, etag='"STALE-v1"')
    _no_network(monkeypatch)

    with pytest.raises(eaglei.EagleiError, match="ETag"):
        _acquire(tmp_path, payload, expected_etag='"CURRENT-v9"')


def test_receipt_reports_the_sidecar_etag_not_the_callers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
    ).encode()
    _write_completed_source(tmp_path, payload, etag='"sidecar-only"')
    _no_network(monkeypatch)

    result = _acquire(tmp_path, payload, expected_etag=None)

    assert result["receipt"]["etag"] == '"sidecar-only"'
    assert result["eaglei"]["etag"] == '"sidecar-only"'


# --- integrity: the sidecar must bind the bytes on disk, and a truncated
# --- stream must never become a "complete" annual source.


def test_cached_bytes_changed_after_the_sidecar_was_written_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
    ).encode()
    raw = _write_completed_source(tmp_path, payload)
    poisoned = payload.replace(b",5,", b",9,")
    assert len(poisoned) == len(payload) and poisoned != payload
    raw.write_bytes(poisoned)
    _no_network(monkeypatch)

    with pytest.raises(eaglei.EagleiError, match="manifest"):
        _acquire(tmp_path, payload)


@pytest.mark.parametrize(
    ("field", "poison"),
    [("raw_sha256", "0" * 64), ("raw_bytes", 0)],
)
def test_sidecar_hash_and_byte_binding_are_load_bearing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, poison: object
) -> None:
    """Poison only the sidecar so no other manifest clause can catch it."""
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
    ).encode()
    raw = _write_completed_source(tmp_path, payload)
    sidecar = raw.with_name(f"{raw.name}.source.json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata[field] = poison
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    _no_network(monkeypatch)

    with pytest.raises(eaglei.EagleiError, match="manifest"):
        _acquire(tmp_path, payload)


def test_a_stream_under_a_different_etag_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
    ).encode()

    class Response:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {"ETag": '"moved-on-v2"'}

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            yield payload

    monkeypatch.setattr(eaglei.requests, "get", lambda *a, **k: Response())

    with pytest.raises(eaglei.EagleiError, match="changed while streaming"):
        _acquire(tmp_path, payload)
    assert not (tmp_path / "annual-source" / "eaglei_outages_2024.csv").exists()


def test_a_short_stream_is_refused_instead_of_becoming_a_complete_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
    ).encode()
    truncated = payload[: len(payload) // 2]

    class Response:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {"ETag": '"source-v1"'}

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            yield truncated

    monkeypatch.setattr(eaglei.requests, "get", lambda *a, **k: Response())

    with pytest.raises(eaglei.EagleiError, match="Figshare file size"):
        _acquire(tmp_path, payload)
    assert not (tmp_path / "annual-source" / "eaglei_outages_2024.csv").exists()


# --- recovery walk: an omitted --fips must not silently erase coverage or
# --- report every selected row as a duplicate (review finding #4/#5).


def test_receipt_without_a_fips_filter_reports_the_observed_counties(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = (
        HEADER
        + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n"
        + "27137,St Louis,Minnesota,5,2024-06-19 00:15:00,123\n"
        + "27053,Hennepin,Minnesota,7,2024-06-19 00:30:00,900\n"
    ).encode()
    _write_completed_source(tmp_path, payload)
    _no_network(monkeypatch)

    result = _acquire(tmp_path, payload, fips=set())
    detail = result["eaglei"]

    assert sorted(detail["coverage_by_county"]) == ["27053", "27137"]
    assert detail["coverage_by_county"]["27137"]["observed_intervals"] == 2
    assert detail["coverage_by_county"]["27053"]["availability"] == "Available"
    assert detail["duplicate_selected_rows"] == 0
    assert detail["coverage_summary"] == "Available"


def test_empty_selection_without_a_fips_filter_is_recorded_as_uncovered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = (HEADER + "06001,Alameda,California,8,2024-06-19 00:00:00,999\n").encode()
    _write_completed_source(tmp_path, payload)
    _no_network(monkeypatch)

    result = _acquire(tmp_path, payload, fips=set())

    assert result["eaglei"]["coverage_summary"] == "UncoveredLabel"
    assert any("UncoveredLabel" in gap for gap in result["receipt"]["gaps"])


# --- cache trust and batch behaviour


def test_same_size_raw_cache_without_matching_metadata_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A same-size cache whose sidecar does not bind it must not be reused."""
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
    calls: list[object] = []
    monkeypatch.setattr(
        eaglei.requests,
        "get",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(eaglei.EagleiError, match="manifest"):
        _acquire(tmp_path, desired)
    assert not calls, "untrusted bytes must not be silently reused or refetched"


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
            {
                "request_schema_version": "flux-460-final-requests/v1",
                "source": "test",
                "requests": [
                    {
                        "event_id": "batch-event",
                        "year": 2024,
                        "start": "2024-06-19T00:00:00Z",
                        "end": "2024-06-19T01:00:00Z",
                        "states": ["Minnesota"],
                        "fips": ["27137"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = eaglei.batch_scan_requests(requests_path, tmp_path)[0]
    detail = result["eaglei"]

    assert detail["event_id"] == "batch-event"
    assert detail["acquisition_complete"] is True
    assert result["receipt"]["raw_sha256"] == hashlib.sha256(payload).hexdigest()
    assert (
        detail["coverage_by_county"]["27137"]["coverage_state"]
        == "complete_15_min_observation"
    )
    assert Path(detail["filtered_artifact"]).exists()
    assert [row["total_customers"] for row in _rows(detail["filtered_artifact"])] == [
        "123",
        "123",
        "123",
        "123",
    ]


def test_batch_reports_the_licence_the_manifest_recorded(tmp_path: Path) -> None:
    payload = (HEADER + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n").encode()
    raw = _write_completed_source(tmp_path, payload)
    sidecar = raw.with_name(f"{raw.name}.source.json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata["license_name"] = "ORNL EAGLE-I terms of use"
    metadata["license_url"] = "https://example.invalid/terms"
    metadata["license_source_url"] = "https://example.invalid/article"
    sidecar.write_text(json.dumps(metadata), encoding="utf-8")
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps(
            [
                {
                    "event_id": "licensed",
                    "year": 2024,
                    "start": "2024-06-19T00:00:00Z",
                    "end": "2024-06-19T00:15:00Z",
                    "states": ["Minnesota"],
                    "fips": ["27137"],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = eaglei.batch_scan_requests(requests_path, tmp_path)[0]

    license_text = result["receipt"]["license_or_access"]
    assert "ORNL EAGLE-I terms of use" in license_text
    assert "https://example.invalid/terms" in license_text
    assert "https://example.invalid/article" in license_text
    assert "CC BY 4.0" not in license_text


def test_batch_refuses_to_assert_licence_terms_the_fetch_never_recorded(
    tmp_path: Path,
) -> None:
    payload = (HEADER + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n").encode()
    _write_completed_source(tmp_path, payload, license_fields=False)
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps(
            [
                {
                    "event_id": "unlicensed",
                    "year": 2024,
                    "start": "2024-06-19T00:00:00Z",
                    "end": "2024-06-19T00:15:00Z",
                    "states": ["Minnesota"],
                    "fips": ["27137"],
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(eaglei.EagleiError, match="licence terms"):
        eaglei.batch_scan_requests(requests_path, tmp_path)


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

    results = eaglei.batch_scan_requests(requests_path, tmp_path)

    assert parse_count == 1
    assert [item["eaglei"]["event_id"] for item in results] == ["first", "second"]
    assert all(item["eaglei"]["acquisition_complete"] for item in results)


def test_batch_indexes_county_requests_without_changing_overlapping_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a row's county requests are considered; empty FIPS remains unrestricted."""
    payload = (
        HEADER
        + "11111,Alpha,Minnesota,1,2024-06-19 00:00:00,100\n"
        + "22222,Beta,Minnesota,2,2024-06-19 00:15:00,200\n"
        + "11111,Alpha,Minnesota,3,2024-06-19 00:30:00,100\n"
        + "99999,Elsewhere,California,4,2024-06-19 00:00:00,300\n"
    ).encode()
    _write_completed_source(tmp_path, payload)
    requests_path = tmp_path / "requests.json"
    requests_path.write_text(
        json.dumps(
            [
                {
                    "event_id": "alpha-first-half",
                    "year": 2024,
                    "start": "2024-06-19T00:00:00Z",
                    "end": "2024-06-19T00:30:00Z",
                    "states": ["Minnesota"],
                    "fips": ["11111"],
                },
                {
                    "event_id": "alpha-full-hour",
                    "year": 2024,
                    "start": "2024-06-19T00:00:00Z",
                    "end": "2024-06-19T01:00:00Z",
                    "states": ["Minnesota"],
                    "fips": ["11111"],
                },
                {
                    "event_id": "beta-full-hour",
                    "year": 2024,
                    "start": "2024-06-19T00:00:00Z",
                    "end": "2024-06-19T01:00:00Z",
                    "states": ["Minnesota"],
                    "fips": ["22222"],
                },
                {
                    "event_id": "all-minnesota",
                    "year": 2024,
                    "start": "2024-06-19T00:00:00Z",
                    "end": "2024-06-19T01:00:00Z",
                    "states": ["Minnesota"],
                    "fips": [],
                },
            ]
        ),
        encoding="utf-8",
    )
    original_matches = eaglei._row_matches
    calls: list[tuple[str, str]] = []

    def counting_matches(
        row: dict[str, str], request: dict[str, object], timestamp: datetime
    ) -> bool:
        calls.append((row["fips_code"], str(request["event_id"])))
        return original_matches(row, request, timestamp)

    monkeypatch.setattr(eaglei, "_row_matches", counting_matches)

    receipts = eaglei.batch_scan_requests(requests_path, tmp_path)

    rows_by_event = {
        item["eaglei"]["event_id"]: [
            row["customers_out"] for row in _rows(item["eaglei"]["filtered_artifact"])
        ]
        for item in receipts
    }
    assert rows_by_event == {
        "alpha-first-half": ["1"],
        "alpha-full-hour": ["1", "3"],
        "beta-full-hour": ["2"],
        "all-minnesota": ["1", "2", "3"],
    }
    assert not any(
        row_fips == "99999" and event_id != "all-minnesota"
        for row_fips, event_id in calls
    )
    assert not any(
        row_fips == "22222" and event_id.startswith("alpha")
        for row_fips, event_id in calls
    )

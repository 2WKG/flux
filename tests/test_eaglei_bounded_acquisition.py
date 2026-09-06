"""The default EAGLE-I acquisition must stay bounded and schema-shaped.

`acquire()` used to return `acquire_exhaustive(...)` before any of the range
machinery ran, so a "bounded" request streamed the whole ~1.44 GB annual CSV.
These tests drive `acquire()` end to end against a fake time-ordered source and
assert the byte ceiling, the 206 enforcement, and the receipt shape.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import jsonschema
import pytest

import scripts.event_baseline.acquire_eaglei as eaglei
from tests.test_eaglei_exhaustive_integrity import (
    HEADER,
    _article,
    _file,
    _write_completed_source,
)

DOWNLOAD_URL = "https://example.invalid/eaglei_outages_2024.csv"
SOURCE_ETAG = '"annual-v1"'
BASE = datetime(2024, 1, 1, tzinfo=UTC)
SAMPLES = 40_000
WINDOW_INDEX = 20_000

# docs/data/event-baseline/event_baseline.schema.json `$defs.receipt`, copied
# verbatim from PR #232 (branch
# joshuawangia/2wkg-461-define-the-event-catalog-coverage-rules-and-six-hour-labels)
# so this branch can be validated against it before #232 merges. Once the file
# exists in the tree it is preferred over this copy.
SCHEMA_PATH = Path("docs/data/event-baseline/event_baseline.schema.json")
VENDORED_RECEIPT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$defs": {
        "utc": {"type": "string", "pattern": "Z$"},
        "identifier": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]*$"},
    },
    "type": "object",
    "required": [
        "receipt_id",
        "provider",
        "url",
        "release",
        "retrieved_at_utc",
        "license_or_access",
        "raw_sha256",
        "filtered_sha256",
        "bytes",
        "etag",
        "units",
        "timezone_conversion",
        "filters",
        "grid_index_mapping",
        "gaps",
    ],
    "properties": {
        "receipt_id": {"$ref": "#/$defs/identifier"},
        "provider": {"type": "string"},
        "url": {"type": "string", "format": "uri"},
        "release": {"type": ["string", "null"]},
        "retrieved_at_utc": {"$ref": "#/$defs/utc"},
        "license_or_access": {"type": "string"},
        "raw_sha256": {"type": ["string", "null"], "pattern": "^[a-f0-9]{64}$"},
        "filtered_sha256": {"type": ["string", "null"], "pattern": "^[a-f0-9]{64}$"},
        "bytes": {"type": ["integer", "null"], "minimum": 0},
        "etag": {"type": ["string", "null"]},
        "units": {"type": "string"},
        "timezone_conversion": {"type": "string"},
        "filters": {"type": "string"},
        "grid_index_mapping": {"type": "string"},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def receipt_schema() -> dict[str, Any]:
    if SCHEMA_PATH.exists():
        document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        schema = dict(document["$defs"]["receipt"])
        schema["$defs"] = document["$defs"]
        return schema
    return VENDORED_RECEIPT_SCHEMA


def annual_body() -> bytes:
    """A time-ordered synthetic annual CSV large enough to binary-search."""
    lines = [HEADER]
    for index in range(SAMPLES):
        stamp = (BASE + timedelta(seconds=900 * index)).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"27137,St Louis,Minnesota,{index % 50},{stamp},123\n")
        lines.append(f"06001,Alameda,California,{index % 7},{stamp},999\n")
    return "".join(lines).encode()


@pytest.fixture(scope="module")
def body() -> bytes:
    payload = annual_body()
    assert len(payload) > 8 * eaglei.PROBE_BYTES, "source must need a real search"
    return payload


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        content: bytes,
        headers: dict[str, str],
        payload: object = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class FakeSource:
    """Serves HTTP ranges out of an in-memory annual CSV and counts bytes."""

    def __init__(self, body: bytes, *, ignore_range: bool = False) -> None:
        self.body = body
        self.ignore_range = ignore_range
        self.bytes_served = 0
        self.range_requests: list[tuple[int, int]] = []
        self.article = {
            "id": 24237376,
            "title": "EAGLE-I outages",
            "license": {"name": "CC BY 4.0", "url": eaglei.LICENSE_URL},
            "files": [
                {
                    "id": 53581661,
                    "name": "eaglei_outages_2024.csv",
                    "size": len(body),
                    "supplied_md5": hashlib.md5(body).hexdigest(),
                    "computed_md5": hashlib.md5(body).hexdigest(),
                    "download_url": DOWNLOAD_URL,
                }
            ],
        }

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> FakeResponse:
        if url == eaglei.FIGSHARE_ARTICLE_URL:
            return FakeResponse(200, b"", {}, payload=self.article)
        match = re.fullmatch(r"bytes=(\d+)-(\d+)", (headers or {}).get("Range", ""))
        if match is None:
            raise AssertionError("the bounded path must always send a Range header")
        start, end = int(match.group(1)), int(match.group(2))
        if self.ignore_range:
            self.bytes_served += len(self.body)
            return FakeResponse(200, self.body, {"ETag": SOURCE_ETAG})
        chunk = self.body[start : end + 1]
        self.bytes_served += len(chunk)
        self.range_requests.append((start, end))
        return FakeResponse(
            206,
            chunk,
            {
                "Content-Range": f"bytes {start}-{end}/{len(self.body)}",
                "ETag": SOURCE_ETAG,
            },
        )


def window() -> tuple[datetime, datetime]:
    start = BASE + timedelta(seconds=900 * WINDOW_INDEX)
    return start, start + timedelta(hours=1)


def run_bounded(
    source: FakeSource,
    cache_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_bytes: int = 2_000_000,
) -> dict[str, Any]:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("the bounded path must never stream the whole file")

    monkeypatch.setattr(eaglei.requests, "get", forbidden)
    start, end = window()
    return eaglei.acquire(
        event_id="bounded",
        year=2024,
        start=start,
        end=end,
        states={"Minnesota"},
        fips={"27137"},
        cache_dir=cache_dir,
        allow_full_download=False,
        max_bytes=max_bytes,
        session=source,
    )


def test_bounded_acquisition_never_transfers_more_than_its_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    source = FakeSource(body)

    result = run_bounded(source, tmp_path, monkeypatch, max_bytes=2_000_000)

    assert source.bytes_served <= 2_000_000
    assert source.bytes_served < len(body) // 2, (
        f"served {source.bytes_served} of {len(body)} source bytes"
    )
    assert result["eaglei"]["bytes_transferred"] == source.bytes_served
    assert result["eaglei"]["acquisition_method"] == "bounded_http_range_binary_search"
    assert result["capture_method"] == "bounded_http_range_binary_search"
    # The binary search really ran: probes were issued and recorded.
    assert result["eaglei"]["range_probes"], "no range probes were recorded"
    assert len(source.range_requests) == len(result["eaglei"]["range_probes"]) + 2


def test_bounded_acquisition_returns_the_requested_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    source = FakeSource(body)
    start, _ = window()

    detail = run_bounded(source, tmp_path, monkeypatch)["eaglei"]

    assert detail["filtered_rows"] == 4
    assert detail["reported_timestamp_min"] == start.strftime("%Y-%m-%d %H:%M:%S")
    assert (
        detail["coverage_by_county"]["27137"]["coverage_state"]
        == "not_assessed_from_bounded_range"
    )
    assert detail["coverage_by_county"]["27137"]["availability"] == "Unknown"
    assert (
        detail["coverage_by_county"]["27137"]["observed_intervals_in_retrieved_rows"]
        == 4
    )
    assert detail["coverage_by_county"]["27137"]["expected_intervals_at_15_min"] == 4


def test_a_ceiling_smaller_than_the_search_refuses_instead_of_overrunning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    source = FakeSource(body)

    with pytest.raises(eaglei.EagleiError, match="byte ceiling"):
        run_bounded(source, tmp_path, monkeypatch, max_bytes=100_000)

    assert source.bytes_served <= 100_000


def test_a_source_that_ignores_range_is_refused_not_downloaded_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    source = FakeSource(body, ignore_range=True)

    with pytest.raises(eaglei.EagleiError, match="did not honor HTTP Range"):
        run_bounded(source, tmp_path, monkeypatch)


def test_default_acquisition_streams_the_complete_source_and_names_it_in_the_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    source = FakeSource(body)
    streamed: list[int] = []

    class StreamResponse:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {"ETag": SOURCE_ETAG}

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            streamed.append(len(body))
            yield body

    monkeypatch.setattr(eaglei.requests, "get", lambda *a, **k: StreamResponse())
    start, end = window()

    result = eaglei.acquire(
        event_id="full",
        year=2024,
        start=start,
        end=end,
        states={"Minnesota"},
        fips={"27137"},
        cache_dir=tmp_path,
        session=source,
    )

    assert streamed == [len(body)]
    assert result["capture_method"] == "exhaustive_annual_stream"
    assert result["receipt"]["bytes"] == len(body)


def test_default_exhaustive_acquisition_handles_fips_major_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default must not binary-search a locally sorted, globally reset CSV."""
    lines = [HEADER]
    for fips, county, state in (
        ("06001", "Alameda", "California"),
        ("27137", "St Louis", "Minnesota"),
    ):
        for index in range(100):
            stamp = (BASE + timedelta(minutes=15 * index)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            lines.append(f"{fips},{county},{state},{index},{stamp},123\n")
    body = "".join(lines).encode()
    source = FakeSource(body)
    streamed: list[int] = []

    class StreamResponse:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {"ETag": SOURCE_ETAG}

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            streamed.append(len(body))
            yield body

    monkeypatch.setattr(eaglei.requests, "get", lambda *a, **k: StreamResponse())
    start = BASE + timedelta(minutes=15 * 50)
    result = eaglei.acquire(
        event_id="fips-major-default",
        year=2024,
        start=start,
        end=start + timedelta(hours=1),
        states={"Minnesota"},
        fips={"27137"},
        cache_dir=tmp_path,
        session=source,
    )

    assert streamed == [len(body)]
    assert result["capture_method"] == "exhaustive_annual_stream"
    assert result["eaglei"]["filtered_rows"] == 4
    assert (
        result["eaglei"]["coverage_by_county"]["27137"]["coverage_state"]
        == "complete_15_min_observation"
    )


def test_bounded_fips_major_false_zero_never_claims_source_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit range probe may miss FIPS-major rows but must remain unknown."""
    lines = [HEADER]
    for fips, county, state in (
        ("06001", "Alameda", "California"),
        ("27137", "St Louis", "Minnesota"),
    ):
        for index in range(SAMPLES):
            stamp = (BASE + timedelta(minutes=15 * index)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            lines.append(f"{fips},{county},{state},{index % 10},{stamp},123\n")
    source = FakeSource("".join(lines).encode())
    start = BASE + timedelta(minutes=15 * WINDOW_INDEX)
    result = eaglei.acquire(
        event_id="fips-major-bounded",
        year=2024,
        start=start,
        end=start + timedelta(hours=1),
        states={"Minnesota"},
        fips={"27137"},
        cache_dir=tmp_path,
        allow_full_download=False,
        max_bytes=2_000_000,
        session=source,
    )

    detail = result["eaglei"]
    assert detail["filtered_rows"] == 0  # reproduces the unsafe probe's false zero
    assert detail["acquisition_complete"] is False
    assert detail["coverage_summary"] == "Unknown"
    assert detail["coverage_by_county"]["27137"] == {
        "availability": "Unknown",
        "coverage_state": "not_assessed_from_bounded_range",
        "observed_intervals_in_retrieved_rows": 0,
        "expected_intervals_at_15_min": 4,
    }
    assert "UncoveredLabel" not in result["receipt"]["gaps"]


def test_bounded_receipt_validates_against_the_event_baseline_receipt_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    result = run_bounded(FakeSource(body), tmp_path, monkeypatch)

    jsonschema.validate(result["receipt"], receipt_schema())
    assert result["receipt"]["receipt_id"].islower()
    assert isinstance(result["receipt"]["gaps"], list)
    assert result["verification"]["full_annual_file_streamed"] is False
    assert result["receipt"]["acquisition"] is None


def test_exhaustive_receipt_validates_against_the_event_baseline_receipt_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = (HEADER + "27137,St Louis,Minnesota,5,2024-06-19 00:00:00,123\n").encode()
    _write_completed_source(tmp_path, payload)
    monkeypatch.setattr(
        eaglei.requests,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network")),
    )

    result = eaglei.acquire_exhaustive(
        article=_article(),
        file=_file(payload),
        event_id="schema",
        year=2024,
        start=datetime(2024, 6, 19, tzinfo=UTC),
        end=datetime(2024, 6, 19, 1, tzinfo=UTC),
        states={"Minnesota"},
        fips={"27137"},
        cache_dir=tmp_path,
        expected_etag='"source-v1"',
    )

    jsonschema.validate(result["receipt"], receipt_schema())
    assert result["receipt"]["license_or_access"].startswith("CC BY 4.0")
    assert result["capture_method"] == "exhaustive_annual_stream"
    assert set(result["verification"])  # #199/#216 convention is carried alongside
    assert result["receipt"]["acquisition"]["acquisition_complete"] is True


def test_the_receipt_object_carries_no_fields_the_schema_forbids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    """`additionalProperties: false` is the reason #199's fields are siblings."""
    result = run_bounded(FakeSource(body), tmp_path, monkeypatch)

    schema = receipt_schema()
    assert set(result["receipt"]) <= set(schema["properties"])
    assert set(schema["required"]).issubset(result["receipt"])
    assert result["receipt"]["capture_method"]
    assert result["capture_method"]
    assert result["verification"]

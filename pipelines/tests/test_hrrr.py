from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from pipelines import hrrr
from pipelines.db import connect, replace_frame


def _manifest(path, end="2021-02-11T01Z"):
    path.write_text(
        json.dumps(
            {
                "fixed_contract_windows": {"uri_2021": f"2021-02-11T00Z..{end}"},
                "reproducible_manifest_rule": "f00 fields and f01 initialized one hour earlier for APCP and FRZR",
            }
        )
    )


def _county(con):
    replace_frame(
        con,
        "counties",
        pd.DataFrame(
            [
                {
                    "county_fips": "48001",
                    "name": "Test",
                    "state": "TX",
                    "pop": 1,
                    "geom_wkb": Polygon(
                        [(-101, 29), (-95, 29), (-95, 34), (-101, 34)]
                    ).wkb,
                }
            ]
        ),
        source_name="test",
        source_ref="test",
        fixture_batch_id="test",
    )


def test_manifest_window_is_half_open(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    monkeypatch.setattr(hrrr, "MANIFEST_PATH", manifest)
    start, end = hrrr._windows()["uri_2021"]
    assert start == datetime(2021, 2, 11, tzinfo=UTC)
    assert (end - start).total_seconds() == 3600


def test_bounded_prepare_writes_in_order_and_stops_on_failure():
    written = []
    assert (
        hrrr.bounded_ordered_prepare(
            range(4),
            lambda hour: hour,
            lambda hour: written.append(hour) or 1,
            workers=2,
        )
        == 4
    )
    assert written == [0, 1, 2, 3]
    called = []

    def prepare(hour):
        called.append(hour)
        if hour == 1:
            raise RuntimeError("bad hour")
        return hour

    with pytest.raises(RuntimeError, match="bad hour"):
        hrrr.bounded_ordered_prepare(range(20), prepare, lambda _hour: 1, workers=1)
    assert called == [0, 1]


def test_range_fetch_uses_idx_bounds_only(monkeypatch, tmp_path):
    calls = []

    class Response:
        def __init__(
            self, text="", content=b"abc", status_code=200, content_range=None
        ):
            self.text, self.content, self.status_code, self.headers = (
                text,
                content,
                status_code,
                {"ETag": '"etag"', "Content-Range": content_range},
            )

        def raise_for_status(self):
            pass

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return (
            Response(
                "1:10:d=x:TMP:2 m above ground:anl:\n2:13:d=x:OTHER:surface:anl:\n"
            )
            if url.endswith(".idx")
            else Response(status_code=206, content_range="bytes 10-12/100")
        )

    monkeypatch.setattr(hrrr.requests, "get", get)
    path, receipt = hrrr._fetch_message(
        "https://example.test/file", "TMP:2 m above ground:anl", tmp_path
    )
    assert path.read_bytes() == b"abc"
    assert calls[1][1]["headers"] == {"Range": "bytes=10-12"}
    assert receipt["range"] == [10, 12]


def test_range_fetch_rejects_wrong_partial_headers(monkeypatch, tmp_path):
    class Response:
        def __init__(self, text="", content=b"abc", status_code=200, headers=None):
            self.text, self.content, self.status_code, self.headers = (
                text,
                content,
                status_code,
                headers or {},
            )

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        hrrr.requests,
        "get",
        lambda url, **_kwargs: (
            Response(
                "1:10:d=x:TMP:2 m above ground:anl:\n2:13:d=x:OTHER:surface:anl:\n"
            )
            if url.endswith(".idx")
            else Response(status_code=206, headers={"Content-Range": "bytes 11-12/100"})
        ),
    )
    with pytest.raises(RuntimeError, match="does not match"):
        hrrr._fetch_message(
            "https://example.test/file", "TMP:2 m above ground:anl", tmp_path
        )


def test_county_index_and_aggregation_are_deterministic(tmp_path):
    con = connect(tmp_path / "grid.duckdb")
    _county(con)
    try:
        latitude = np.array([[30.0, 30.0], [40.0, 30.0]])
        longitude = np.array([[-100.0, -96.0], [-100.0, -96.0]])
        index = hrrr._county_index_from_grid(con, latitude, longitude, hrrr.scope("TX"))
        assert index.flat_index.tolist() == [0, 1, 3]
        assert (
            hrrr._mean_by_county(index, np.array([[2.0, 4.0], [9.0, 9.0]])).loc["48001"]
            == 5.0
        )
    finally:
        con.close()


def test_validation_rejects_corrupt_metadata_and_stale_cache(tmp_path):
    con = connect(tmp_path / "grid.duckdb")
    _county(con)
    latitude = np.array([[30.0]])
    longitude = np.array([[-100.0]])
    index = pd.DataFrame(
        {
            "flat_index": [0],
            "county_fips": ["48001"],
            "grid_signature": [hrrr._grid_signature(latitude, longitude)],
            "grid_shape": ["[1, 1]"],
            "state_scope": ["tx"],
            "county_fingerprint": [hrrr._county_identity(con, hrrr.scope("TX"))[1]],
        }
    )
    message = hrrr.GribMessage(
        np.array([[280.0]]),
        latitude,
        longitude,
        {
            "GRIB_shortName": "2t",
            "GRIB_stepType": "instant",
            "units": "K",
            "GRIB_units": "K",
        },
        datetime(2021, 2, 11, tzinfo=UTC),
        datetime(2021, 2, 11, tzinfo=UTC),
        0,
    )
    try:
        hrrr._validate_message(
            message,
            field="TMP:2 m above ground:anl",
            init=datetime(2021, 2, 11, tzinfo=UTC),
            lead=0,
            index=index,
        )
        bad = hrrr.GribMessage(
            message.value,
            latitude,
            longitude,
            message.attrs | {"units": "C"},
            message.init,
            message.valid,
            message.step_hours,
        )
        with pytest.raises(RuntimeError, match="units"):
            hrrr._validate_message(
                bad,
                field="TMP:2 m above ground:anl",
                init=message.init,
                lead=0,
                index=index,
            )
        assert hrrr._cache_matches(con, index, hrrr.scope("TX"))
        assert not hrrr._cache_matches(
            con, index.drop(columns="county_fingerprint"), hrrr.scope("TX")
        )
    finally:
        con.close()


def test_historical_loader_preserves_crosswalk_provenance(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    monkeypatch.setattr(hrrr, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(hrrr, "RAW_DIR", tmp_path / "raw")
    con = connect(tmp_path / "grid.duckdb")
    _county(con)
    index = pd.DataFrame(
        {"flat_index": [0], "county_fips": ["48001"], "grid_signature": ["grid"]}
    )
    monkeypatch.setattr(hrrr, "build_county_index", lambda *_args, **_kwargs: index)
    monkeypatch.setattr(
        hrrr,
        "_fetch_message",
        lambda url, field, raw: (
            tmp_path / field.replace(":", "_"),
            {
                "url": url,
                "field": field,
                "range": [1, 2],
                "etag": "e",
                "sha256": "a",
                "bytes": 2,
            },
        ),
    )
    fields = {
        "UGRD": 3.0,
        "VGRD": 4.0,
        "GUST": 8.0,
        "TMP": 280.0,
        "APCP": 2.0,
        "FRZR": 0.5,
    }

    def decode(path):
        name = str(path)
        value = next(value for key, value in fields.items() if key in name)
        grid = np.array([[value]])
        return hrrr.GribMessage(
            grid, grid, grid, {}, datetime.now(UTC), datetime.now(UTC), 0
        )

    monkeypatch.setattr(hrrr, "_decode", decode)
    monkeypatch.setattr(hrrr, "_validate_message", lambda *_args, **_kwargs: None)
    try:
        assert hrrr.load_hrrr_window(con, "uri_2021") == 1
        row = con.execute(
            "SELECT wind_ms, gust_ms, temp_c, ice_mm, precip_mm, source_ref FROM weather_hourly"
        ).fetchone()
        assert row[:5] == (5.0, 8.0, 6.850000000000023, 0.5, 2.0)
        receipt = json.loads(Path(row[5]).read_text())
        source_run = receipt["weather_source_run"]
        assert source_run["analysis_init"] == "2021-02-11T00:00:00+00:00"
        assert source_run["accumulation_init"] == "2021-02-10T23:00:00+00:00"
        assert len(receipt["files"]) == 6
        # The receipt follows the checked-in source-receipt shape used by the
        # rest of data/sources: named files with sha256, capture method, and an
        # explicit verification block. It is not a second, private convention.
        assert receipt["capture_method"].startswith("HTTP range request")
        assert receipt["provider"] == hrrr.PROVIDER
        assert receipt["source_url"] == hrrr.SOURCE_URL
        assert receipt["license_access"] == hrrr.LICENSE_ACCESS
        assert receipt["retrieved_at"] == receipt["weather_source_run"]["retrieved_at"]
        assert set(receipt["verification"]) == {
            "content_range_matched_request",
            "sha256_computed_from_response_body",
            "decoded_field_identity_checked",
            "grid_signature",
            "county_index_version",
            "index_path",
        }
        assert all(
            set(item) >= {"url", "field", "range", "sha256", "bytes"}
            for item in receipt["files"].values()
        )
        assert sorted(item["field"] for item in receipt["files"].values()) == sorted(
            [*hrrr.ANALYSIS_FIELDS.values(), *hrrr.ACCUMULATION_FIELDS.values()]
        )
        assert (
            con.execute("SELECT count(*) FROM weather_source_runs").fetchone()[0] == 1
        )
    finally:
        con.close()


def test_loader_rolls_back_weather_when_source_run_write_fails(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    monkeypatch.setattr(hrrr, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(hrrr, "RAW_DIR", tmp_path / "raw")
    con = connect(tmp_path / "grid.duckdb")
    _county(con)
    index = pd.DataFrame(
        {"flat_index": [0], "county_fips": ["48001"], "grid_signature": ["grid"]}
    )
    monkeypatch.setattr(hrrr, "build_county_index", lambda *_args, **_kwargs: index)
    monkeypatch.setattr(
        hrrr,
        "_fetch_message",
        lambda _url, field, _raw: (
            tmp_path / field.replace(":", "_"),
            {
                "url": "https://example.test",
                "field": field,
                "range": [1, 2],
                "etag": "e",
                "sha256": "a",
                "bytes": 2,
            },
        ),
    )
    message = hrrr.GribMessage(
        np.array([[1.0]]),
        np.array([[1.0]]),
        np.array([[1.0]]),
        {},
        datetime.now(UTC),
        datetime.now(UTC),
        0,
    )
    monkeypatch.setattr(hrrr, "_decode", lambda _path: message)
    monkeypatch.setattr(hrrr, "_validate_message", lambda *_args, **_kwargs: None)
    try:
        assert hrrr.load_hrrr_window(con, "uri_2021") == 1
        source_ref = con.execute("SELECT source_ref FROM weather_hourly").fetchone()[0]
        prior_receipt = Path(source_ref).read_bytes()
        prior_weather = con.execute(
            "SELECT wind_ms, source_ref FROM weather_hourly"
        ).fetchone()
        monkeypatch.setattr(
            hrrr,
            "_persist_source_run",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("write failed")),
        )
        with pytest.raises(RuntimeError, match="write failed"):
            hrrr.load_hrrr_window(con, "uri_2021")
        assert (
            con.execute("SELECT wind_ms, source_ref FROM weather_hourly").fetchone()
            == prior_weather
        )
        assert Path(source_ref).read_bytes() == prior_receipt
    finally:
        con.close()


def test_loader_parallel_path_orders_writes_and_reuses_verified_cache(
    monkeypatch, tmp_path
):
    """The public loader, rather than its scheduler alone, owns these guarantees."""
    manifest = tmp_path / "manifest.json"
    _manifest(manifest, "2021-02-11T03Z")
    monkeypatch.setattr(hrrr, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(hrrr, "utc_now", lambda: datetime(2021, 2, 12, tzinfo=UTC))
    index = pd.DataFrame(
        {"flat_index": [0], "county_fips": ["48001"], "grid_signature": ["grid"]}
    )
    calls = []

    def install_loader_fakes(raw_dir):
        monkeypatch.setattr(hrrr, "RAW_DIR", raw_dir)
        monkeypatch.setattr(hrrr, "build_county_index", lambda *_args, **_kwargs: index)

        def fetch(url, field, raw):
            calls.append((url, field))
            valid_hour = int(url.split(".t")[1][:2])
            # Make the earliest writer input finish last, proving that writes are
            # chronological rather than completion ordered.
            if valid_hour == 0:
                time.sleep(0.03)
            content = f"{url}|{field}".encode()
            digest = hashlib.sha256(content).hexdigest()
            path = raw / digest[:2] / f"{digest}.grib2"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return path, {
                "url": url,
                "field": field,
                "range": [1, 2],
                "etag": "e",
                "sha256": digest,
                "bytes": len(content),
            }

        values = {
            "UGRD": 3.0,
            "VGRD": 4.0,
            "GUST": 8.0,
            "TMP": 280.0,
            "APCP": 2.0,
            "FRZR": 0.5,
        }
        monkeypatch.setattr(hrrr, "_fetch_message", fetch)
        monkeypatch.setattr(
            hrrr,
            "_decode",
            lambda path: hrrr.GribMessage(
                np.array(
                    [
                        [
                            next(
                                value
                                for key, value in values.items()
                                if key in path.read_text()
                            )
                        ]
                    ]
                ),
                np.array([[1.0]]),
                np.array([[1.0]]),
                {},
                datetime.now(UTC),
                datetime.now(UTC),
                0,
            ),
        )
        monkeypatch.setattr(hrrr, "_validate_message", lambda *_args, **_kwargs: None)

    raw_dir = tmp_path / "raw"
    install_loader_fakes(raw_dir)
    con = connect(tmp_path / "grid.duckdb")
    _county(con)
    written = []
    original_write = hrrr._write_prepared_hrrr_hour
    monkeypatch.setattr(
        hrrr,
        "_write_prepared_hrrr_hour",
        lambda connection, prepared, selected: (
            written.append(prepared.valid)
            or original_write(connection, prepared, selected)
        ),
    )
    try:
        assert hrrr.load_hrrr_window(con, "uri_2021", workers=2) == 3
        assert written == sorted(written)
        serial_rows = con.execute(
            "SELECT county_fips, ts, wind_ms, gust_ms, temp_c, ice_mm, precip_mm, source_ref "
            "FROM weather_hourly ORDER BY ts"
        ).fetchall()
        serial_runs = con.execute(
            "SELECT valid_ts, analysis_init, accumulation_init, analysis_fields_json, accumulation_fields_json "
            "FROM weather_source_runs ORDER BY valid_ts"
        ).fetchall()
        assert len(calls) == 18
        calls.clear()
        # Existing content-addressed subsets and receipts bypass all HTTP fetches.
        assert hrrr.load_hrrr_window(con, "uri_2021", workers=1) == 3
        assert calls == []
        assert (
            con.execute(
                "SELECT county_fips, ts, wind_ms, gust_ms, temp_c, ice_mm, precip_mm, source_ref "
                "FROM weather_hourly ORDER BY ts"
            ).fetchall()
            == serial_rows
        )
        assert (
            con.execute(
                "SELECT valid_ts, analysis_init, accumulation_init, analysis_fields_json, accumulation_fields_json "
                "FROM weather_source_runs ORDER BY valid_ts"
            ).fetchall()
            == serial_runs
        )
        # A cached subset whose bytes no longer hash to the receipt's digest is
        # not reusable evidence: it must be refetched, not trusted on the
        # receipt's word.
        receipt = json.loads(
            Path(
                con.execute(
                    "SELECT source_ref FROM weather_hourly ORDER BY ts"
                ).fetchone()[0]
            ).read_text()
        )
        digests = sorted(item["sha256"] for item in receipt["files"].values())
        corrupted = raw_dir / digests[0][:2] / f"{digests[0]}.grib2"
        intact = corrupted.read_bytes()
        corrupted.write_bytes(intact + b"tampered")
        calls.clear()
        assert hrrr.load_hrrr_window(con, "uri_2021", workers=1) == 3
        assert calls, "a corrupted cached subset was reused without re-verification"
        assert corrupted.read_bytes() == intact
        assert (
            con.execute(
                "SELECT county_fips, ts, wind_ms, gust_ms, temp_c, ice_mm, precip_mm, source_ref "
                "FROM weather_hourly ORDER BY ts"
            ).fetchall()
            == serial_rows
        )
    finally:
        con.close()


def test_loader_cancels_queued_hours_after_prepare_failure(monkeypatch, tmp_path):
    manifest = tmp_path / "manifest.json"
    _manifest(manifest, "2021-02-11T04Z")
    monkeypatch.setattr(hrrr, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(hrrr, "RAW_DIR", tmp_path / "raw")
    con = connect(tmp_path / "grid.duckdb")
    _county(con)
    index = pd.DataFrame(
        {"flat_index": [0], "county_fips": ["48001"], "grid_signature": ["grid"]}
    )
    monkeypatch.setattr(hrrr, "build_county_index", lambda *_args, **_kwargs: index)
    attempted = []

    def fetch(url, field, raw):
        attempted.append((url, field))
        if ".t01z." in url:
            raise RuntimeError("bad hour")
        path = tmp_path / field.replace(":", "_")
        return path, {
            "url": url,
            "field": field,
            "range": [1, 2],
            "etag": "e",
            "sha256": "a",
            "bytes": 2,
        }

    monkeypatch.setattr(hrrr, "_fetch_message", fetch)
    monkeypatch.setattr(
        hrrr,
        "_decode",
        lambda _path: hrrr.GribMessage(
            np.array([[1.0]]),
            np.array([[1.0]]),
            np.array([[1.0]]),
            {},
            datetime.now(UTC),
            datetime.now(UTC),
            0,
        ),
    )
    monkeypatch.setattr(hrrr, "_validate_message", lambda *_args, **_kwargs: None)
    try:
        with pytest.raises(RuntimeError, match="bad hour"):
            hrrr.load_hrrr_window(con, "uri_2021", workers=2)
        assert all(
            ".t02z." not in url and ".t03z." not in url for url, _field in attempted
        )
        # A concurrently completed first hour may commit before the failure is
        # observed, but no later hour is submitted or partially paired.
        weather_rows = con.execute("SELECT count(*) FROM weather_hourly").fetchone()[0]
        source_runs = con.execute(
            "SELECT count(*) FROM weather_source_runs"
        ).fetchone()[0]
        assert weather_rows in (0, 1)
        assert source_runs == weather_rows
    finally:
        con.close()


FIXTURES = Path(__file__).parent / "fixtures" / "hrrr"
F00_IDX = "hrrr.20210211.t00z.wrfsfcf00.grib2.idx"
F01_IDX = "hrrr.20210210.t23z.wrfsfcf01.grib2.idx"


def _serve_captured_idx(monkeypatch, name):
    """Serve one captured, unedited HRRR .idx sidecar. No network is used."""
    text = (FIXTURES / name).read_text()

    class Response:
        def __init__(self):
            self.text = text

        def raise_for_status(self):
            pass

    monkeypatch.setattr(hrrr.requests, "get", lambda url, **_kwargs: Response())


def test_idx_keys_carry_the_forecast_field_that_disambiguates_messages(monkeypatch):
    """A captured f01 index holds two WEASD:surface messages that differ only in fcst."""
    _serve_captured_idx(monkeypatch, F01_IDX)
    url = "https://example.test/hrrr.t23z.wrfsfcf01.grib2"
    keys = [key for _number, _start, key in hrrr._index(f"{url}")]
    assert keys.count("WEASD:surface:1 hour fcst") == 1
    assert keys.count("WEASD:surface:0-1 hour acc fcst") == 1
    # Two messages, same VAR:level, different bytes. Dropping the fcst field
    # would make these one ambiguous key and hand back whichever came first.
    assert hrrr._message_bounds(url, "WEASD:surface:1 hour fcst") == (
        43126057,
        43947262,
    )
    assert hrrr._message_bounds(url, "WEASD:surface:0-1 hour acc fcst") == (
        59944175,
        60286930,
    )
    assert hrrr._message_bounds(url, hrrr.ACCUMULATION_FIELDS["precip_mm"]) == (
        59561600,
        59944174,
    )
    assert hrrr._message_bounds(url, hrrr.ACCUMULATION_FIELDS["ice_mm"]) == (
        60356094,
        60494912,
    )
    # The analysis keys belong to the f00 file, not this one.
    for field in hrrr.ANALYSIS_FIELDS.values():
        with pytest.raises(RuntimeError, match="absent"):
            hrrr._message_bounds(url, field)


def test_captured_f00_index_resolves_analysis_fields_and_excludes_hourly_accumulation(
    monkeypatch,
):
    _serve_captured_idx(monkeypatch, F00_IDX)
    url = "https://example.test/hrrr.t00z.wrfsfcf00.grib2"
    assert hrrr._message_bounds(url, hrrr.ANALYSIS_FIELDS["temp_k"]) == (
        36662761,
        37885937,
    )
    assert hrrr._message_bounds(url, hrrr.ANALYSIS_FIELDS["wind_u"]) == (
        43174631,
        45556245,
    )
    # f00 carries APCP/FRZR as an all-zero 0-0 day accumulation. The declared
    # accumulation keys must not resolve here, or every hour would read zeros.
    for field in hrrr.ACCUMULATION_FIELDS.values():
        with pytest.raises(RuntimeError, match="absent"):
            hrrr._message_bounds(url, field)


def test_message_bounds_refuses_an_ambiguous_index_key(monkeypatch):
    monkeypatch.setattr(
        hrrr,
        "_index",
        lambda _url: [
            (1, 0, "APCP:surface:0-1 hour acc fcst"),
            (2, 10, "APCP:surface:0-1 hour acc fcst"),
            (3, 20, "OTHER:surface:anl"),
        ],
    )
    with pytest.raises(RuntimeError, match="matches 2 messages"):
        hrrr._message_bounds(
            "https://example.test/file", "APCP:surface:0-1 hour acc fcst"
        )


def test_range_fetch_rejects_a_non_partial_response(monkeypatch, tmp_path):
    """A 200 with a whole-object body is not a range subset, whatever it contains."""

    class Response:
        def __init__(self, text="", content=b"abc", status_code=200):
            self.text, self.content, self.status_code = text, content, status_code
            self.headers = {"ETag": '"etag"', "Content-Range": "bytes 10-12/100"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        hrrr.requests,
        "get",
        lambda url, **_kwargs: (
            Response(
                "1:10:d=x:TMP:2 m above ground:anl:\n2:13:d=x:OTHER:surface:anl:\n"
            )
            if url.endswith(".idx")
            else Response(status_code=200)
        ),
    )
    with pytest.raises(RuntimeError, match="not partial content"):
        hrrr._fetch_message(
            "https://example.test/file", "TMP:2 m above ground:anl", tmp_path
        )
    assert list(tmp_path.rglob("*.grib2")) == []


# The .idx key -> cfgrib identity contract, written out here rather than read
# back from the module, so a change to the module's table fails this test.
_CFGRIB_IDENTITY = {
    "UGRD:10 m above ground:anl": ("10u", "instant", "m s**-1"),
    "VGRD:10 m above ground:anl": ("10v", "instant", "m s**-1"),
    "GUST:surface:anl": ("gust", "instant", "m s**-1"),
    "TMP:2 m above ground:anl": ("2t", "instant", "K"),
    "APCP:surface:0-1 hour acc fcst": ("tp", "accum", "kg m**-2"),
    "FRZR:surface:0-1 hour acc fcst": ("frzr", "accum", "kg m**-2"),
}
_FIELD_VALUES = {
    "UGRD:10 m above ground:anl": 3.0,
    "VGRD:10 m above ground:anl": 4.0,
    "GUST:surface:anl": 8.0,
    "TMP:2 m above ground:anl": 280.0,
    "APCP:surface:0-1 hour acc fcst": 2.0,
    "FRZR:surface:0-1 hour acc fcst": 0.5,
}
_LATITUDE = np.array([[30.0]])
_LONGITUDE = np.array([[-100.0]])


def _validating_index():
    return pd.DataFrame(
        {
            "flat_index": [0],
            "county_fips": ["48001"],
            "grid_signature": [hrrr._grid_signature(_LATITUDE, _LONGITUDE)],
            "grid_shape": ["[1, 1]"],
        }
    )


def _install_validating_fakes(monkeypatch, tmp_path, corrupt=None):
    """Wire the loader to fake bytes but leave _validate_message untouched.

    ``corrupt`` is ``(field, mutation)``: the mutation is applied to the decoded
    message for that field only, so the loader's own validation is what decides.
    """
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    monkeypatch.setattr(hrrr, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(hrrr, "RAW_DIR", tmp_path / "raw")
    index = _validating_index()
    monkeypatch.setattr(hrrr, "build_county_index", lambda *_a, **_k: index)
    paths = {}

    def fetch(url, field, raw):
        path = raw / f"{abs(hash(field))}.grib2"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake")
        paths[path] = field
        return path, {
            "url": url,
            "field": field,
            "range": [1, 2],
            "etag": "e",
            "sha256": hashlib.sha256(field.encode()).hexdigest(),
            "bytes": 4,
        }

    def decode(path):
        field = paths[path]
        short_name, step_type, units = _CFGRIB_IDENTITY[field]
        lead = 0 if field in hrrr.ANALYSIS_FIELDS.values() else 1
        init = datetime(2021, 2, 11, tzinfo=UTC) - timedelta(hours=lead)
        message = hrrr.GribMessage(
            np.array([[_FIELD_VALUES[field]]]),
            _LATITUDE,
            _LONGITUDE,
            {
                "GRIB_shortName": short_name,
                "GRIB_stepType": step_type,
                "units": units,
                "GRIB_units": units,
            },
            init,
            init + timedelta(hours=lead),
            lead,
        )
        if corrupt is not None and corrupt[0] == field:
            message = corrupt[1](message)
        return message

    monkeypatch.setattr(hrrr, "_fetch_message", fetch)
    monkeypatch.setattr(hrrr, "_decode", decode)
    return index


def test_loader_runs_real_validation_over_every_decoded_message(monkeypatch, tmp_path):
    """No monkeypatched _validate_message: the loader's own guard runs here."""
    _install_validating_fakes(monkeypatch, tmp_path)
    con = connect(tmp_path / "grid.duckdb")
    _county(con)
    try:
        assert hrrr.load_hrrr_window(con, "uri_2021") == 1
        assert con.execute("SELECT temp_c FROM weather_hourly").fetchone()[
            0
        ] == pytest.approx(6.85)
    finally:
        con.close()


@pytest.mark.parametrize(
    ("field", "mutation", "expected"),
    [
        (
            "TMP:2 m above ground:anl",
            lambda message: hrrr.GribMessage(
                message.value,
                message.latitude,
                message.longitude,
                message.attrs | {"units": "C", "GRIB_units": "C"},
                message.init,
                message.valid,
                message.step_hours,
            ),
            "units do not match",
        ),
        (
            "GUST:surface:anl",
            lambda message: hrrr.GribMessage(
                message.value,
                message.latitude,
                message.longitude,
                message.attrs | {"GRIB_shortName": "10u"},
                message.init,
                message.valid,
                message.step_hours,
            ),
            "field identity does not match",
        ),
        (
            "UGRD:10 m above ground:anl",
            lambda message: hrrr.GribMessage(
                message.value,
                np.array([[31.0]]),
                message.longitude,
                message.attrs,
                message.init,
                message.valid,
                message.step_hours,
            ),
            "grid does not match",
        ),
        (
            "APCP:surface:0-1 hour acc fcst",
            lambda message: hrrr.GribMessage(
                message.value,
                message.latitude,
                message.longitude,
                message.attrs | {"units": "m", "GRIB_units": "m"},
                message.init,
                message.valid,
                message.step_hours,
            ),
            "units do not match",
        ),
        (
            "FRZR:surface:0-1 hour acc fcst",
            lambda message: hrrr.GribMessage(
                message.value,
                message.latitude,
                message.longitude,
                message.attrs,
                message.init - timedelta(hours=1),
                message.valid,
                message.step_hours,
            ),
            "time/lead does not match",
        ),
    ],
)
def test_loader_refuses_a_decoded_message_that_fails_validation(
    monkeypatch, tmp_path, field, mutation, expected
):
    """Covers both call sites: analysis (lead 0) and accumulation (lead 1)."""
    _install_validating_fakes(monkeypatch, tmp_path, corrupt=(field, mutation))
    con = connect(tmp_path / "grid.duckdb")
    _county(con)
    try:
        with pytest.raises(RuntimeError, match=expected):
            hrrr.load_hrrr_window(con, "uri_2021")
        assert con.execute("SELECT count(*) FROM weather_hourly").fetchone()[0] == 0
        assert (
            con.execute("SELECT count(*) FROM weather_source_runs").fetchone()[0] == 0
        )
    finally:
        con.close()


def test_prepare_refuses_an_hour_the_county_index_does_not_cover(monkeypatch, tmp_path):
    index = _install_validating_fakes(monkeypatch, tmp_path)
    valid = datetime(2021, 2, 11, tzinfo=UTC)
    prepared = hrrr._prepare_hrrr_hour(
        scenario_id="uri_2021",
        valid=valid,
        index=index,
        wanted_counties={"48001"},
    )
    assert prepared.frame.county_fips.tolist() == ["48001"]
    # The index knows one county; asking for two must fail loudly rather than
    # write a short frame that silently drops a requested county.
    with pytest.raises(RuntimeError, match="does not cover every requested county"):
        hrrr._prepare_hrrr_hour(
            scenario_id="uri_2021",
            valid=valid,
            index=index,
            wanted_counties={"48001", "48002"},
        )


def test_prepared_payloads_cannot_pile_up_ahead_of_the_writer():
    """The memory half of "bounded": a slow first hour must not queue the rest."""
    workers = 2
    hours = range(12)
    release = threading.Event()
    lock = threading.Lock()
    state = {"outstanding": 0, "peak": 0}
    timer = threading.Timer(0.5, release.set)
    timer.start()

    def prepare(hour):
        if hour == 0:
            assert release.wait(10)
        with lock:
            state["outstanding"] += 1
            state["peak"] = max(state["peak"], state["outstanding"])
            piled_up = state["outstanding"] > workers
        if piled_up:
            # Unblock hour 0 so a broken bound fails fast instead of hanging.
            release.set()
        return hour

    def write(hour):
        with lock:
            state["outstanding"] -= 1
        return 1

    try:
        assert hrrr.bounded_ordered_prepare(
            hours, prepare, write, workers=workers
        ) == len(hours)
    finally:
        timer.cancel()
    assert state["outstanding"] == 0
    assert state["peak"] <= workers, (
        f"{state['peak']} prepared hours were held at once with workers={workers}"
    )


def test_build_county_index_fetches_one_grid_message_then_reuses_its_cache(
    monkeypatch, tmp_path
):
    con = connect(tmp_path / "grid.duckdb")
    _county(con)
    latitude = np.array([[30.0, 30.0], [40.0, 30.0]])
    longitude = np.array([[-100.0, -96.0], [-100.0, -96.0]])
    fetched = []

    def fetch(url, field, raw):
        fetched.append((url, field, raw))
        return tmp_path / "grid.grib2", {"sha256": "a"}

    monkeypatch.setattr(hrrr, "_fetch_message", fetch)
    monkeypatch.setattr(
        hrrr,
        "_decode",
        lambda _path: hrrr.GribMessage(
            np.zeros((2, 2)),
            latitude,
            longitude,
            {},
            datetime(2021, 2, 15, tzinfo=UTC),
            datetime(2021, 2, 15, tzinfo=UTC),
            0,
        ),
    )
    cache = tmp_path / "cache" / "hrrr_county_index.parquet"
    try:
        index = hrrr.build_county_index(con, cache=str(cache), states=("TX",))
        assert fetched == [
            (
                (
                    "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.20210215/"
                    "conus/hrrr.t00z.wrfsfcf00.grib2"
                ),
                hrrr.ANALYSIS_FIELDS["temp_k"],
                hrrr.RAW_DIR,
            )
        ]
        assert index.flat_index.tolist() == [0, 1, 3]
        assert index.county_fips.unique().tolist() == ["48001"]
        assert index.grid_signature.iloc[0] == hrrr._grid_signature(latitude, longitude)
        assert index.grid_shape.iloc[0] == "[2, 2]"
        assert cache.is_file()
        fetched.clear()
        reused = hrrr.build_county_index(con, cache=str(cache), states=("TX",))
        assert fetched == []
        assert reused.flat_index.tolist() == [0, 1, 3]
        # A cache built against different county geometry is not reused.
        assert not hrrr._cache_matches(
            con, reused.assign(county_fingerprint="drifted"), hrrr.scope("TX")
        )
    finally:
        con.close()


def test_cli_loads_one_declared_window_through_the_public_loader(monkeypatch, capsys):
    calls = []

    class FakeConnection:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(hrrr, "connect", lambda path: calls.append(path) or connection)
    monkeypatch.setattr(
        hrrr,
        "load_hrrr_window",
        lambda con, scenario, states, workers: (
            calls.append((con, scenario, states.usps, workers)) or 240
        ),
    )
    assert (
        hrrr.main(["--scenario", "uri_2021", "--db", "x.duckdb", "--workers", "4"]) == 0
    )
    assert calls == ["x.duckdb", (connection, "uri_2021", ("TX",), 4)]
    assert connection.closed
    assert capsys.readouterr().out.strip() == "weather_hourly: 240"

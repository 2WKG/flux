from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
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
                "fixed_contract_windows": {
                    "uri_2021": f"2021-02-11T00Z..{end}"
                },
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
            Response("1:10:d=x:TMP:2 m above ground:x\n2:13:d=x:OTHER:surface:x\n")
            if url.endswith(".idx")
            else Response(status_code=206, content_range="bytes 10-12/100")
        )

    monkeypatch.setattr(hrrr.requests, "get", get)
    path, receipt = hrrr._fetch_message(
        "https://example.test/file", "TMP:2 m above ground", tmp_path
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
            Response("1:10:d=x:TMP:2 m above ground:x\n2:13:d=x:OTHER:surface:x\n")
            if url.endswith(".idx")
            else Response(status_code=206, headers={"Content-Range": "bytes 11-12/100"})
        ),
    )
    with pytest.raises(RuntimeError, match="does not match"):
        hrrr._fetch_message(
            "https://example.test/file", "TMP:2 m above ground", tmp_path
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
            field="TMP:2 m above ground",
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
                field="TMP:2 m above ground",
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
        assert len(receipt["sources"]) == 6
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


def test_loader_parallel_path_orders_writes_and_reuses_verified_cache(monkeypatch, tmp_path):
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

        values = {"UGRD": 3.0, "VGRD": 4.0, "GUST": 8.0, "TMP": 280.0, "APCP": 2.0, "FRZR": 0.5}
        monkeypatch.setattr(hrrr, "_fetch_message", fetch)
        monkeypatch.setattr(
            hrrr,
            "_decode",
            lambda path: hrrr.GribMessage(
                np.array([[next(value for key, value in values.items() if key in path.read_text())]]),
                np.array([[1.0]]), np.array([[1.0]]), {}, datetime.now(UTC), datetime.now(UTC), 0,
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
            written.append(prepared.valid) or original_write(connection, prepared, selected)
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
        assert con.execute(
            "SELECT county_fips, ts, wind_ms, gust_ms, temp_c, ice_mm, precip_mm, source_ref "
            "FROM weather_hourly ORDER BY ts"
        ).fetchall() == serial_rows
        assert con.execute(
            "SELECT valid_ts, analysis_init, accumulation_init, analysis_fields_json, accumulation_fields_json "
            "FROM weather_source_runs ORDER BY valid_ts"
        ).fetchall() == serial_runs
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
        return path, {"url": url, "field": field, "range": [1, 2], "etag": "e", "sha256": "a", "bytes": 2}

    monkeypatch.setattr(hrrr, "_fetch_message", fetch)
    monkeypatch.setattr(
        hrrr, "_decode", lambda _path: hrrr.GribMessage(np.array([[1.0]]), np.array([[1.0]]), np.array([[1.0]]), {}, datetime.now(UTC), datetime.now(UTC), 0)
    )
    monkeypatch.setattr(hrrr, "_validate_message", lambda *_args, **_kwargs: None)
    try:
        with pytest.raises(RuntimeError, match="bad hour"):
            hrrr.load_hrrr_window(con, "uri_2021", workers=2)
        assert all(".t02z." not in url and ".t03z." not in url for url, _field in attempted)
        # A concurrently completed first hour may commit before the failure is
        # observed, but no later hour is submitted or partially paired.
        weather_rows = con.execute("SELECT count(*) FROM weather_hourly").fetchone()[0]
        source_runs = con.execute("SELECT count(*) FROM weather_source_runs").fetchone()[0]
        assert weather_rows in (0, 1)
        assert source_runs == weather_rows
    finally:
        con.close()

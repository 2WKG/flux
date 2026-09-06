"""Persistence contract for paired HRRR source-run receipts."""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import pytest

from pipelines.db import CONTRACT_TABLES, ensure_schema


def _row(*, source_file: str = "hrrr.t12z.wrfsfcf00.grib2") -> tuple[object, ...]:
    return (
        "uri_2021",
        datetime(2021, 2, 15, 12, tzinfo=UTC),
        "noaa-hrrr-bdp-pds",
        "hrrr-2021-02-15",
        source_file,
        "hrrr",
        "hrrr-conus-3km-lambert-1059x1799",
        datetime(2021, 2, 15, 12, tzinfo=UTC),
        0,
        datetime(2021, 2, 15, 11, tzinfo=UTC),
        1,
        "https://example.test/f00",
        "https://example.test/f01",
        None,
        None,
        '["UGRD:10 m","VGRD:10 m","GUST:surface","TMP:2 m"]',
        '["APCP:surface","FRZR:surface"]',
        '[{"start":0,"end":100}]',
        '[{"start":101,"end":200}]',
        "hrrr-county-index-v1",
        "data/raw/hrrr/receipts/uri_2021-20210215T1200Z.json",
        datetime(2026, 9, 6, 12, tzinfo=UTC),
        None,
        datetime(2026, 9, 6, 12, tzinfo=UTC),
    )


def test_weather_source_runs_preserves_paired_receipts_and_is_not_exported() -> None:
    con = duckdb.connect(":memory:")
    try:
        ensure_schema(con)
        assert tuple(
            row[1]
            for row in con.execute(
                "PRAGMA table_info('weather_source_runs')"
            ).fetchall()
        ) == (
            "scenario_id",
            "valid_ts",
            "source",
            "source_release",
            "source_file",
            "model",
            "grid_signature",
            "analysis_init",
            "analysis_lead_h",
            "accumulation_init",
            "accumulation_lead_h",
            "analysis_url",
            "accumulation_url",
            "analysis_etag",
            "accumulation_etag",
            "analysis_fields_json",
            "accumulation_fields_json",
            "analysis_ranges_json",
            "accumulation_ranges_json",
            "county_index_version",
            "receipt_path",
            "retrieved_at",
            "fallback_kind",
            "loaded_at",
        )
        con.execute(
            "INSERT INTO weather_source_runs VALUES ("
            + ", ".join("?" for _ in _row())
            + ")",
            _row(),
        )
        stored = con.execute(
            """SELECT model, analysis_lead_h, accumulation_lead_h, analysis_url,
                      accumulation_url, analysis_etag, accumulation_etag,
                      analysis_fields_json, accumulation_fields_json,
                      analysis_ranges_json, accumulation_ranges_json,
                      county_index_version, receipt_path, fallback_kind
                 FROM weather_source_runs"""
        ).fetchone()
    finally:
        con.close()

    assert stored == (
        "hrrr",
        0,
        1,
        "https://example.test/f00",
        "https://example.test/f01",
        None,
        None,
        '["UGRD:10 m","VGRD:10 m","GUST:surface","TMP:2 m"]',
        '["APCP:surface","FRZR:surface"]',
        '[{"start":0,"end":100}]',
        '[{"start":101,"end":200}]',
        "hrrr-county-index-v1",
        "data/raw/hrrr/receipts/uri_2021-20210215T1200Z.json",
        None,
    )
    assert "weather_source_runs" not in CONTRACT_TABLES


def test_weather_source_runs_has_one_replaceable_receipt_per_scenario_hour() -> None:
    con = duckdb.connect(":memory:")
    try:
        ensure_schema(con)
        placeholders = ", ".join("?" for _ in _row())
        con.execute(f"INSERT INTO weather_source_runs VALUES ({placeholders})", _row())
        with pytest.raises(duckdb.ConstraintException):
            con.execute(
                f"INSERT INTO weather_source_runs VALUES ({placeholders})", _row()
            )
        con.execute(
            f"INSERT OR REPLACE INTO weather_source_runs VALUES ({placeholders})",
            _row(source_file="hrrr.t12z.wrfsfcf00.retrieved.grib2"),
        )
        assert con.execute(
            "SELECT source_file, count(*) FROM weather_source_runs GROUP BY source_file"
        ).fetchone() == ("hrrr.t12z.wrfsfcf00.retrieved.grib2", 1)
    finally:
        con.close()

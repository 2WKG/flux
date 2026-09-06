"""Reproducible manifest: byte-identical across builds, honest about gaps, wired in."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from pipelines import build as build_module
from pipelines.db import CONTRACT_TABLES, SCHEMA_VERSION, connect, ensure_schema
from pipelines.manifest import (
    DIGEST_METHOD,
    SYNTHETIC_TABLES,
    ManifestError,
    build_manifest,
    store_manifest,
    write_manifest,
)

PROVENANCE = ("test", "fixture", None, None, "test")

COUNTIES = [
    ("27001", "Aitkin", "MN", 1, b"a"),
    ("27003", "Anoka", "MN", 2, b"b"),
    ("27005", "Becker", "MN", 3, b"c"),
]
HAZARDS = [("27001", 1.5), ("27003", 2.5), ("27005", 3.5)]
# Composite primary key (county_fips, ts): the first column alone is NOT a total order.
OUTAGES = [
    ("27001", "2024-01-01 00:00:00", 7),
    ("27001", "2024-01-01 01:00:00", 8),
    ("27003", "2024-01-01 00:00:00", 9),
    ("27003", "2024-01-01 01:00:00", 10),
]
STORMS = [
    (1, "27001", "2021-07-01 12:00:00", "2021-07-01 13:00:00", "Hail", 1.0),
    (1, "27003", "2021-07-01 12:00:00", "2021-07-01 13:00:00", "Hail", 1.0),
    (2, "27005", "2021-07-02 12:00:00", "2021-07-02 13:00:00", "High Wind", 50.0),
]


def _seed(
    con,
    *,
    reverse: bool = False,
    hazards: list[tuple[str, float]] | None = None,
) -> None:
    order = (lambda rows: list(reversed(rows))) if reverse else list
    for county_fips, name, state, pop, geom in order(COUNTIES):
        con.execute(
            "INSERT INTO counties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [county_fips, name, state, pop, geom, *PROVENANCE],
        )
    for county_fips, score in order(hazards if hazards is not None else HAZARDS):
        con.execute(
            "INSERT INTO hazard_static VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, ?)",
            [county_fips, score, *PROVENANCE],
        )
    for county_fips, ts, out in order(OUTAGES):
        con.execute(
            "INSERT INTO eaglei_outages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [county_fips, ts, out, *PROVENANCE],
        )
    for event_id, county_fips, begin, end, kind, magnitude in order(STORMS):
        con.execute(
            "INSERT INTO storm_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [event_id, county_fips, begin, end, kind, magnitude, *PROVENANCE],
        )


def _fresh(tmp_path: Path, name: str, **seed_kwargs):
    con = duckdb.connect(str(tmp_path / f"{name}.duckdb"))
    ensure_schema(con)
    _seed(con, **seed_kwargs)
    return con


def test_identical_rows_in_different_insertion_order_give_byte_identical_manifests(
    tmp_path,
):
    forward, backward = _fresh(tmp_path, "a"), _fresh(tmp_path, "b", reverse=True)
    try:
        assert forward.execute("SELECT * FROM eaglei_outages").fetchall() != (
            backward.execute("SELECT * FROM eaglei_outages").fetchall()
        ), "fixture must physically differ in row order"
        first = write_manifest(
            build_manifest(forward, state_scope="mn"), tmp_path / "a.json"
        )
        second = write_manifest(
            build_manifest(backward, state_scope="mn"), tmp_path / "b.json"
        )
    finally:
        forward.close()
        backward.close()
    assert first.read_bytes() == second.read_bytes()
    manifest = json.loads(first.read_text())
    assert "build_timestamp" not in manifest
    assert manifest["tables"]["eaglei_outages"]["row_count"] == len(OUTAGES)


def test_manifest_digest_reflects_row_content(tmp_path):
    baseline = _fresh(tmp_path, "a")
    changed = _fresh(
        tmp_path, "b", hazards=[("27001", 1.5), ("27003", 2.5), ("27005", 9.9)]
    )
    empty = duckdb.connect(str(tmp_path / "empty.duckdb"))
    ensure_schema(empty)
    try:
        base = build_manifest(baseline, state_scope="mn")["tables"]
        other = build_manifest(changed, state_scope="mn")["tables"]
        blank = build_manifest(empty, state_scope="mn")["tables"]
    finally:
        baseline.close()
        changed.close()
        empty.close()
    assert (
        base["hazard_static"]["content_sha256"]
        != other["hazard_static"]["content_sha256"]
    )
    assert base["counties"]["content_sha256"] == other["counties"]["content_sha256"]
    assert (
        base["eaglei_outages"]["content_sha256"]
        != blank["eaglei_outages"]["content_sha256"]
    )
    assert base["eaglei_outages"]["row_count"] == len(OUTAGES)
    assert blank["eaglei_outages"]["row_count"] == 0


def test_manifest_publishes_the_full_composite_primary_key(tmp_path):
    con = _fresh(tmp_path, "a")
    try:
        tables = build_manifest(con, state_scope="mn")["tables"]
    finally:
        con.close()
    assert tables["eaglei_outages"]["primary_key"] == ["county_fips", "ts"]
    assert tables["storm_events"]["primary_key"] == ["event_id", "county_fips"]
    assert tables["site_scores"]["primary_key"] == ["site_id", "scenario_id", "unit_mw"]
    assert tables["counties"]["primary_key"] == ["county_fips"]


def test_missing_contract_table_is_an_error_not_an_omission(tmp_path):
    con = _fresh(tmp_path, "a")
    try:
        con.execute("DROP TABLE cascade_runs")
        with pytest.raises(ManifestError, match="cascade_runs"):
            build_manifest(con, state_scope="mn")
    finally:
        con.close()


def test_manifest_records_schema_version_scope_and_digest_method(tmp_path):
    con = _fresh(tmp_path, "a")
    try:
        manifest = build_manifest(con, state_scope="mn")
    finally:
        con.close()
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["state_scope"] == "mn"
    assert manifest["digest_method"] == DIGEST_METHOD
    assert "Parquet" in DIGEST_METHOD
    assert set(manifest["tables"]) == set(CONTRACT_TABLES)
    for table, entry in manifest["tables"].items():
        assert len(entry["content_sha256"]) == 64
        expected = "synthetic" if table in SYNTHETIC_TABLES else "real"
        assert entry["classification"] == expected, table


def test_store_manifest_round_trips_through_schema_meta(tmp_path):
    con = _fresh(tmp_path, "a")
    try:
        manifest = build_manifest(con, state_scope="mn")
        store_manifest(con, manifest)
        stored = con.execute(
            "SELECT value FROM schema_meta WHERE key = 'manifest'"
        ).fetchone()
    finally:
        con.close()
    assert stored is not None
    assert json.loads(stored[0]) == manifest


# --- Wire: build() stages, describes, checks and promotes the manifest ---


def _stage_minnesota_release(
    _raw_dir: str, db_path: str, _tz, parquet_dir: str, _states=None
) -> dict:
    """Stand-in for the loaders: a Minnesota release that passes the MN checks."""
    con = connect(db_path)
    try:
        _seed(con)
        con.execute(
            "INSERT INTO ba_load_hourly VALUES ('MISO', '2024-01-01 00:00:00', 1.0, ?, ?, ?, ?, ?)",
            list(PROVENANCE),
        )
        con.execute(
            "INSERT INTO critical_loads VALUES (1, 'dod', 'Camp Ripley', -94.3, 46.1, NULL, '27001', ?, ?, ?, ?, ?)",
            list(PROVENANCE),
        )
        con.execute(
            "INSERT INTO site_candidates VALUES (1, 'Sherco', 'coal_retiring', -93.9, 45.4, '27003', NULL, 100.0, 'sherco', ?, ?, ?, ?, ?)",
            list(PROVENANCE),
        )
        for year in (2021, 2024):
            con.execute(
                "INSERT INTO eaglei_ingest_quality_by_state VALUES (?, '27', 'f', 'UTC', 1, 1, 0, 0, 0, 1, NULL)",
                [year],
            )
    finally:
        con.close()
    Path(parquet_dir, "counties.parquet").write_bytes(b"fixture")
    return {"minnesota": 1}


def test_build_publishes_manifest_for_the_checked_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "duck" / "grid.duckdb"
    monkeypatch.setattr(build_module, "_missing_p0_inputs", lambda *_args: [])
    monkeypatch.setattr(build_module, "_build_mutating", _stage_minnesota_release)

    # Real run_checks: a Texas scope would reject this Minnesota release.
    counts = build_module.build(str(tmp_path / "raw"), str(db_path), "UTC", "MN")

    assert counts == {"minnesota": 1}
    manifest_path = tmp_path / "data" / "parquet" / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["state_scope"] == "mn"
    assert set(manifest["tables"]) == set(CONTRACT_TABLES)
    assert manifest["tables"]["counties"]["row_count"] == len(COUNTIES)
    assert manifest["tables"]["eaglei_outages"]["row_count"] == len(OUTAGES)
    con = connect(db_path, read_only=True)
    try:
        stored = con.execute(
            "SELECT value FROM schema_meta WHERE key = 'manifest'"
        ).fetchone()
    finally:
        con.close()
    assert stored is not None and json.loads(stored[0]) == manifest


def test_build_rejects_a_release_that_fails_its_scoped_checks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "duck" / "grid.duckdb"
    monkeypatch.setattr(build_module, "_missing_p0_inputs", lambda *_args: [])
    monkeypatch.setattr(build_module, "_build_mutating", _stage_minnesota_release)

    with pytest.raises(RuntimeError, match="scope-counties-tx"):
        build_module.build(str(tmp_path / "raw"), str(db_path), "UTC", "TX,MN")
    assert not (tmp_path / "data" / "parquet" / "manifest.json").exists()
    assert not db_path.exists()

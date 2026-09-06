"""State-scoped quality checks: every requested state must be present and complete."""

from __future__ import annotations

import duckdb
import pytest

from pipelines.checks import run_checks
from pipelines.db import ensure_schema

PROVENANCE = ("test", "fixture", None, None, "test")


def _seed_state(
    con, fips: str, usps: str, *, counties: int = 2, nri_missing: int = 0
) -> None:
    """Load one complete state: counties, NRI, a storm, and both EAGLE-I releases."""
    for index in range(counties):
        county = f"{fips}{2 * index + 1:03d}"
        con.execute(
            "INSERT INTO counties VALUES (?, ?, ?, 1, 'g', ?, ?, ?, ?, ?)",
            [county, f"county-{county}", usps, *PROVENANCE],
        )
        score = None if index < nri_missing else 1.0 + index
        con.execute(
            "INSERT INTO hazard_static VALUES (?, ?, NULL, NULL, ?, ?, ?, ?, ?)",
            [county, score, *PROVENANCE],
        )
    con.execute(
        "INSERT INTO storm_events VALUES (?, ?, '2021-07-01 12:00:00', '2021-07-01 13:00:00', 'Hail', 1.0, ?, ?, ?, ?, ?)",
        [int(fips), f"{fips}001", *PROVENANCE],
    )
    for year in (2021, 2024):
        con.execute(
            "INSERT INTO eaglei_ingest_quality_by_state VALUES (?, ?, 'f', 'UTC', 1, 1, 0, 0, 0, 1, NULL)",
            [year, fips],
        )
        if usps == "TX":
            con.execute(
                "INSERT OR REPLACE INTO eaglei_ingest_quality VALUES (?, 'f', 'UTC', 1, 1, 0, 0, 0, 1, NULL)",
                [year],
            )


def _seed_shared(con, county: str) -> None:
    con.execute(
        "INSERT INTO ba_load_hourly VALUES ('BA', '2024-01-01 00:00:00', 1.0, ?, ?, ?, ?, ?)",
        list(PROVENANCE),
    )
    con.execute(
        "INSERT INTO critical_loads VALUES (1, 'dod', 'base', -95.0, 40.0, NULL, ?, ?, ?, ?, ?, ?)",
        [county, *PROVENANCE],
    )
    con.execute(
        "INSERT INTO site_candidates VALUES (1, 'site', 'dod', -95.0, 40.0, ?, NULL, 10.0, 's', ?, ?, ?, ?, ?)",
        [county, *PROVENANCE],
    )


def _database(tmp_path, name: str, **states: dict) -> str:
    path = tmp_path / f"{name}.duckdb"
    con = duckdb.connect(str(path))
    try:
        ensure_schema(con)
        first = None
        for usps, options in states.items():
            fips = {"TX": "48", "MN": "27"}[usps]
            _seed_state(con, fips, usps, **options)
            first = first or f"{fips}001"
        if first:
            _seed_shared(con, first)
    finally:
        con.close()
    return str(path)


def _results(db: str, states) -> dict[str, bool]:
    return {check.name: check.passed for check in run_checks(db, states)}


def _failed(db: str, states) -> set[str]:
    return {name for name, passed in _results(db, states).items() if not passed}


def test_minnesota_scope_passes_on_a_complete_minnesota_release(tmp_path):
    db = _database(tmp_path, "mn", MN={})
    results = _results(db, "MN")
    assert results == {
        "synthetic-topology-absent": True,
        "scope-counties-mn": True,
        "scope-nri-mn": True,
        "scope-storms-mn": True,
        "scope-eaglei-mn": True,
        "loaded-p0-domains": True,
    }


def test_texas_only_database_fails_every_minnesota_scope_check(tmp_path):
    db = _database(tmp_path, "tx", TX={})
    failed = _failed(db, "MN")
    assert {
        "scope-counties-mn",
        "scope-nri-mn",
        "scope-storms-mn",
        "scope-eaglei-mn",
    } <= failed
    # The Texas rows are not counted towards Minnesota.
    detail = {check.name: check.detail for check in run_checks(db, "MN")}
    assert detail["scope-counties-mn"].startswith("counties=0")
    assert detail["scope-nri-mn"].startswith("county rows=0")


def test_mixed_scope_on_a_texas_only_database_fails_the_minnesota_half(tmp_path):
    db = _database(tmp_path, "tx", TX={})
    results = _results(db, "TX,MN")
    assert {
        "scope-counties-tx",
        "scope-nri-tx",
        "scope-counties-mn",
        "scope-nri-mn",
    } <= set(results)
    assert not results["scope-counties-mn"]
    assert not results["scope-nri-mn"]
    assert not results["scope-storms-mn"]
    assert not results["scope-eaglei-mn"]
    # A mixed scope containing Texas still applies the synthetic-topology gate.
    assert "synthetic-case-counts" in results and not results["synthetic-case-counts"]


def test_default_scope_keeps_the_texas_check_names_and_scopes_them(tmp_path):
    db = _database(tmp_path, "both", TX={}, MN={})
    names = [check.name for check in run_checks(db)]
    assert names == [
        "synthetic-case-counts",
        "synthetic-coordinates",
        "texas-counties",
        "fema-nri-texas",
        "eaglei-target-quality",
        "loaded-p0-domains",
    ]
    detail = {check.name: check.detail for check in run_checks(db)}
    # Two Texas counties, not four: the Minnesota rows are excluded from the Texas count.
    assert detail["texas-counties"].startswith("counties=2,")
    assert detail["fema-nri-texas"].startswith("county rows=2,")


def test_scope_nri_rejects_a_single_missing_composite_score(tmp_path):
    db = _database(tmp_path, "mn", MN={"counties": 3, "nri_missing": 1})
    assert "scope-nri-mn" in _failed(db, "MN")


def test_scope_nri_rejects_a_state_with_no_hazard_rows(tmp_path):
    db = _database(tmp_path, "mn", MN={})
    con = duckdb.connect(db)
    try:
        con.execute("DELETE FROM hazard_static")
    finally:
        con.close()
    assert "scope-nri-mn" in _failed(db, "MN")
    assert "scope-counties-mn" not in _failed(db, "MN")


def test_synthetic_topology_is_rejected_outside_texas(tmp_path):
    db = _database(tmp_path, "mn", MN={})
    con = duckdb.connect(db)
    try:
        con.execute(
            "INSERT INTO buses VALUES (1, 'b', 138.0, -95.0, 45.0, '27001', 'BA', 'tamu_aux', NULL, NULL, ?, ?, ?, ?, ?)",
            list(PROVENANCE),
        )
    finally:
        con.close()
    assert _failed(db, "MN") == {"synthetic-topology-absent"}


@pytest.mark.parametrize("states", ["TX,MN", ["TX", "MN"], "Minnesota,Texas"])
def test_scope_forms_are_parsed_once_and_sorted(tmp_path, states):
    db = _database(tmp_path, "both", TX={}, MN={})
    names = [check.name for check in run_checks(db, states)]
    assert names.index("scope-counties-mn") < names.index("scope-counties-tx")

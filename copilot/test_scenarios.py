"""Behavioral tests for DuckDB-backed scenario catalog and detail routes.

The fixture mirrors the canonical ``scenarios`` DDL from
``pipelines/db.py`` on master (column list, CHECK constraints, provenance
columns) so the route is coupled to the real contract rather than a
hand-written shape.  ``cascade_runs`` / ``outage_predictions`` carry the
contract columns the route depends on (foreign keys to tables this fixture
does not build are omitted).
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings

PROVENANCE_COLUMNS = """
    source_name TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_version TEXT,
    source_retrieved_at TIMESTAMP,
    fixture_batch_id TEXT NOT NULL
"""

SCENARIOS_DDL = f"""
    CREATE TABLE scenarios (
        scenario_id TEXT PRIMARY KEY, name TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('historical', 'forecast', 'synthetic')),
        ts_start TIMESTAMP NOT NULL, ts_end TIMESTAMP NOT NULL CHECK (ts_end >= ts_start),
        {PROVENANCE_COLUMNS})
"""

CASCADE_RUNS_DDL = f"""
    CREATE TABLE cascade_runs (
        run_id TEXT NOT NULL, scenario_id TEXT NOT NULL,
        hour INTEGER NOT NULL CHECK (hour >= 0), tripped_element_ids_json JSON NOT NULL,
        lost_load_mw DOUBLE NOT NULL CHECK (lost_load_mw >= 0), counties_dark_json JSON NOT NULL,
        critical_loads_lost_json JSON NOT NULL, counterfactual_site_id BIGINT,
        {PROVENANCE_COLUMNS}, PRIMARY KEY (run_id, hour))
"""

OUTAGE_PREDICTIONS_DDL = f"""
    CREATE TABLE outage_predictions (
        scenario_id TEXT NOT NULL, county_fips TEXT NOT NULL, ts TIMESTAMP NOT NULL,
        p_out DOUBLE NOT NULL CHECK (p_out BETWEEN 0 AND 1),
        customers_at_risk BIGINT NOT NULL CHECK (customers_at_risk >= 0),
        driver TEXT NOT NULL CHECK (driver IN ('ice', 'wind', 'heat', 'wildfire', 'flood', 'other')),
        {PROVENANCE_COLUMNS}, PRIMARY KEY (scenario_id, county_fips, ts))
"""

_FIXTURE_PROVENANCE = (
    "fixture:flux-demo",
    "pipelines/fixtures/inputs/scenarios.json",
    "1.0.0",
    "2026-01-01T00:00:00",
    "fixture:flux-demo@1.0.0",
)
_ACTIVSG_PROVENANCE = (
    "pipelines.activsg",
    "data/raw/activsg2000/scenarios_ACTIVSg2000.m",
    "2018",
    "2026-09-05T12:00:00",
    "activsg2000@2018",
)
_RECORDED_PROVENANCE = (
    "noaa-storm-events",
    "https://www.ncei.noaa.gov/stormevents/",
    None,
    "2026-09-01T00:00:00",
    "storm-events@2026-09",
)


def _fixture_database(path: Path, *, rows: bool = True) -> None:
    connection = duckdb.connect(str(path))
    connection.execute(SCENARIOS_DDL)
    connection.execute(CASCADE_RUNS_DDL)
    connection.execute(OUTAGE_PREDICTIONS_DDL)
    if rows:
        connection.executemany(
            "INSERT INTO scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "fixture_b",
                    "Recorded storm",
                    "historical",
                    "2026-01-02T00:00:00",
                    "2026-01-02T03:00:00",
                    *_RECORDED_PROVENANCE,
                ),
                (
                    "fixture_a",
                    "First fixture",
                    "synthetic",
                    "2026-01-01T00:00:00",
                    "2026-01-01T06:00:00",
                    *_FIXTURE_PROVENANCE,
                ),
                (
                    "fixture_c",
                    "ACTIVSg contingency",
                    "synthetic",
                    "2026-01-03T00:00:00",
                    "2026-01-03T00:30:00",
                    *_ACTIVSG_PROVENANCE,
                ),
            ],
        )
        connection.execute(
            "INSERT INTO cascade_runs VALUES "
            "('run-1', 'fixture_a', 0, '[]', 0.0, '[]', '[]', NULL, ?, ?, ?, ?, ?)",
            list(_FIXTURE_PROVENANCE),
        )
        connection.execute(
            "INSERT INTO outage_predictions VALUES "
            "('fixture_a', '48201', '2026-01-01T00:00:00', 0.1, 10, 'ice', ?, ?, ?, ?, ?)",
            list(_FIXTURE_PROVENANCE),
        )
    connection.close()


def _client(database: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=database)))


_FIXTURE_A_ROW = {
    "scenario_id": "fixture_a",
    "name": "First fixture",
    "kind": "synthetic",
    "ts_start": "2026-01-01T00:00:00Z",
    "ts_end": "2026-01-01T06:00:00Z",
    "hours": 6,
    "has_cascade": True,
    "has_predictions": True,
    "provenance": {
        "source_name": "fixture:flux-demo",
        "source_ref": "pipelines/fixtures/inputs/scenarios.json",
        "source_version": "1.0.0",
        "source_retrieved_at": "2026-01-01T00:00:00Z",
        "fixture_batch_id": "fixture:flux-demo@1.0.0",
        "source_kind": "fixture",
        "topology": None,
    },
}


def test_catalog_is_the_bare_array_pinned_by_the_overview(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get(
        "/scenarios", headers={"X-Request-ID": "scenarios-1"}
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert [item["scenario_id"] for item in body] == [
        "fixture_a",
        "fixture_b",
        "fixture_c",
    ]
    assert body[0] == _FIXTURE_A_ROW
    assert set(body[1]) == {
        "scenario_id",
        "name",
        "kind",
        "ts_start",
        "ts_end",
        "hours",
        "has_cascade",
        "has_predictions",
        "provenance",
    }
    assert response.headers["X-Request-ID"] == "scenarios-1"


def test_artifact_flags_are_read_from_persisted_tables_not_defaulted(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    body = _client(database).get("/scenarios").json()
    flags = {
        row["scenario_id"]: (row["has_cascade"], row["has_predictions"]) for row in body
    }

    assert flags == {
        "fixture_a": (True, True),
        "fixture_b": (False, False),
        "fixture_c": (False, False),
    }


def test_detail_returns_the_unwrapped_row(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get("/scenarios/fixture_a")

    assert response.status_code == 200
    assert response.json() == _FIXTURE_A_ROW


def test_sub_hour_window_truncates_hours_to_zero_rather_than_rounding_up(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    body = _client(database).get("/scenarios/fixture_c").json()

    assert body["hours"] == 0


def test_provenance_labels_come_from_persisted_columns_never_from_kind(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)
    client = _client(database)

    recorded = client.get("/scenarios/fixture_b").json()
    activsg = client.get("/scenarios/fixture_c").json()

    # A historical scenario is NOT relabelled "observed"; the persisted source is surfaced.
    assert recorded["kind"] == "historical"
    assert recorded["provenance"] == {
        "source_name": "noaa-storm-events",
        "source_ref": "https://www.ncei.noaa.gov/stormevents/",
        "source_version": None,
        "source_retrieved_at": "2026-09-01T00:00:00Z",
        "fixture_batch_id": "storm-events@2026-09",
        "source_kind": None,
        "topology": None,
    }
    assert "observed" not in recorded["provenance"].values()
    # An ACTIVSg2000-derived row carries the synthetic-topology label.
    assert activsg["provenance"]["source_kind"] == "simulated"
    assert activsg["provenance"]["topology"] == "synthetic (ACTIVSg2000)"


def test_detail_reports_not_found_for_an_absent_scenario_row(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get("/scenarios/unknown")

    assert response.status_code == 404
    assert response.json()["status"] == "error"
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["details"] == {"scenario_id": "unknown"}


def test_empty_scenarios_table_is_unavailable_not_an_empty_success(
    tmp_path: Path,
) -> None:
    database = tmp_path / "empty.duckdb"
    _fixture_database(database, rows=False)

    response = _client(database).get("/scenarios")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["data"] is None
    assert body["error"]["code"] == "unavailable"
    assert body["error"]["details"] == {"artifact": "scenarios", "reason": "no_rows"}


def test_missing_database_file_is_the_shared_unavailable_envelope(
    tmp_path: Path,
) -> None:
    response = _client(tmp_path / "missing.duckdb").get("/scenarios")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["data"] is None
    assert body["error"] == {
        "code": "unavailable",
        "message": "The database artifact is unavailable.",
        "retryable": True,
        "retry_after_s": 30,
        "details": {"artifact": "database", "reason": "missing"},
    }


def test_detail_missing_database_file_is_the_shared_unavailable_envelope(
    tmp_path: Path,
) -> None:
    """The detail route has its own unavailable state, not only the catalog's."""
    response = _client(tmp_path / "missing.duckdb").get(
        "/scenarios/mn_winter_2023_snow"
    )

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["data"] is None
    assert body["error"] == {
        "code": "unavailable",
        "message": "The database artifact is unavailable.",
        "retryable": True,
        "retry_after_s": 30,
        "details": {"artifact": "database", "reason": "missing"},
    }


@pytest.mark.parametrize(
    ("dropped_table", "expected_artifact"),
    [
        ("scenarios", "scenarios"),
        ("cascade_runs", "cascade_runs"),
        ("outage_predictions", "outage_predictions"),
    ],
)
def test_each_missing_contract_table_is_named_rather_than_defaulted(
    tmp_path: Path, dropped_table: str, expected_artifact: str
) -> None:
    database = tmp_path / "partial.duckdb"
    _fixture_database(database)
    connection = duckdb.connect(str(database))
    connection.execute(f"DROP TABLE {dropped_table}")
    connection.close()

    response = _client(database).get("/scenarios")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": expected_artifact,
        "reason": "missing",
    }


def test_schema_drift_is_a_named_schema_mismatch_not_a_generic_failure(
    tmp_path: Path,
) -> None:
    database = tmp_path / "drift.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute(
        "CREATE TABLE scenarios (scenario_id TEXT, name TEXT, kind TEXT, "
        "ts_start TIMESTAMP, ts_end TIMESTAMP)"
    )
    connection.execute(CASCADE_RUNS_DDL)
    connection.execute(OUTAGE_PREDICTIONS_DDL)
    connection.execute(
        "INSERT INTO scenarios VALUES ('x', 'Five columns', 'synthetic', "
        "'2026-01-01T00:00:00', '2026-01-01T01:00:00')"
    )
    connection.close()

    response = _client(database).get("/scenarios")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "scenarios",
        "reason": "schema_mismatch",
    }


def test_provenance_type_drift_is_unavailable_not_silently_coerced(
    tmp_path: Path,
) -> None:
    database = tmp_path / "provenance-type-drift.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute(
        "CREATE TABLE scenarios (scenario_id TEXT, name TEXT, kind TEXT, "
        "ts_start TIMESTAMP, ts_end TIMESTAMP, source_name TEXT, source_ref TEXT, "
        "source_version TEXT, source_retrieved_at TEXT, fixture_batch_id TEXT)"
    )
    connection.execute(CASCADE_RUNS_DDL)
    connection.execute(OUTAGE_PREDICTIONS_DDL)
    connection.execute(
        "INSERT INTO scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            "drifted-provenance",
            "Timestamp stored as text",
            "synthetic",
            "2026-01-01T00:00:00",
            "2026-01-01T01:00:00",
            _FIXTURE_PROVENANCE[0],
            _FIXTURE_PROVENANCE[1],
            _FIXTURE_PROVENANCE[2],
            _FIXTURE_PROVENANCE[3],
            _FIXTURE_PROVENANCE[4],
        ],
    )
    connection.close()

    response = _client(database).get("/scenarios/drifted-provenance")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "scenarios",
        "reason": "schema_mismatch",
        "scenario_id": "drifted-provenance",
    }


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(
            (
                "bad_kind",
                "Kind outside enum",
                "weird",
                "2026-01-01T00:00:00",
                "2026-01-01T01:00:00",
                *_FIXTURE_PROVENANCE,
            ),
            id="kind-outside-enum",
        ),
        pytest.param(
            (
                "inverted",
                "End before start",
                "synthetic",
                "2026-01-02T00:00:00",
                "2026-01-01T00:00:00",
                *_FIXTURE_PROVENANCE,
            ),
            id="ts_end-before-ts_start",
        ),
        pytest.param(
            (
                "no_source",
                "Null provenance",
                "synthetic",
                "2026-01-01T00:00:00",
                "2026-01-01T01:00:00",
                None,
                "ref",
                None,
                None,
                "batch",
            ),
            id="null-source_name",
        ),
        pytest.param(
            (
                "no_start",
                "Null timestamp",
                "synthetic",
                None,
                "2026-01-01T01:00:00",
                *_FIXTURE_PROVENANCE,
            ),
            id="null-ts_start",
        ),
    ],
)
def test_rows_violating_the_contract_are_schema_mismatch_not_500(
    tmp_path: Path, row: tuple[object, ...]
) -> None:
    # A table built without the contract's CHECK/NOT NULL constraints can hold
    # rows the canonical DDL would reject; the route must name that, not 500.
    database = tmp_path / "malformed.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute(
        "CREATE TABLE scenarios (scenario_id TEXT, name TEXT, kind TEXT, "
        "ts_start TIMESTAMP, ts_end TIMESTAMP, source_name TEXT, source_ref TEXT, "
        "source_version TEXT, source_retrieved_at TIMESTAMP, fixture_batch_id TEXT)"
    )
    connection.execute(CASCADE_RUNS_DDL)
    connection.execute(OUTAGE_PREDICTIONS_DDL)
    connection.execute(
        "INSERT INTO scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", list(row)
    )
    connection.close()

    for path in ("/scenarios", f"/scenarios/{row[0]}"):
        response = _client(database).get(path)
        assert response.status_code == 503, path
        assert response.json()["error"]["details"] == {
            "artifact": "scenarios",
            "reason": "schema_mismatch",
            "scenario_id": row[0],
        }


def test_scenario_lookup_is_parameterised(tmp_path: Path) -> None:
    database = tmp_path / "fixture.duckdb"
    _fixture_database(database)

    response = _client(database).get("/scenarios/fixture_a'%20OR%20'1'='1")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"

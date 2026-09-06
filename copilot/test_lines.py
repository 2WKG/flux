"""HTTP checks for the persisted, paged line-upgrade read."""

from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings


def _client(path: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=path)))


def _database(path: Path) -> None:
    with duckdb.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE lines (line_id BIGINT, from_bus BIGINT, to_bus BIGINT, base_kv DOUBLE)"
        )
        con.execute(
            "CREATE TABLE line_upgrade_scores (line_id BIGINT, scenario_id TEXT, ranking_version TEXT, computed_at TIMESTAMP, source_name TEXT, source_ref TEXT, source_kind TEXT, mw_per_musd DOUBLE, congestion_usd_yr DOUBLE, dlr_uplift_mw DOUBLE, reconductor_uplift_mw DOUBLE, dlr_cost_usd DOUBLE, reconductor_cost_usd DOUBLE, ferc_screen_pass BOOLEAN, spark_eligible BOOLEAN, simulation_run_id TEXT)"
        )
        con.execute(
            "CREATE TABLE line_upgrade_detail (line_id BIGINT, scenario_id TEXT, region TEXT, best_tech TEXT, congestion_method TEXT)"
        )
        for line_id, score, cost in (
            (10, 20.0, 2_000_000.0),
            (11, 20.0, 1_000_000.0),
            (12, 10.0, 1_000_000.0),
        ):
            con.execute("INSERT INTO lines VALUES (?, 1, 2, 230)", [line_id])
            con.execute(
                "INSERT INTO line_upgrade_scores VALUES (?, 'mn_fixture', 'v1', '2026-01-01', 'fixture', 'line-test', 'fixture', ?, 1, 10, 9, ?, 3, true, false, NULL)",
                [line_id, score, cost],
            )
            con.execute(
                "INSERT INTO line_upgrade_detail VALUES (?, 'mn_fixture', 'MN', 'dlr', 'exact')",
                [line_id],
            )


def test_top_lines_reads_a_deterministic_persisted_page(tmp_path: Path) -> None:
    database = tmp_path / "lines.duckdb"
    _database(database)

    response = _client(database).get(
        "/lines/top", params={"region": "MN", "limit": 1, "offset": 1}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["scenario_id"] == "mn_fixture"
    assert [line["line_id"] for line in body["lines"]] == ["10"]
    assert body["provenance"][0]["source_kind"] == "fixture"


def test_top_lines_reports_unavailable_artifact_states(tmp_path: Path) -> None:
    missing = _client(tmp_path / "missing.duckdb").get(
        "/lines/top", params={"region": "MN"}
    )
    assert missing.status_code == 503
    assert missing.json()["error"]["details"]["reason"] == "artifact_unavailable"

    database = tmp_path / "empty.duckdb"
    _database(database)
    with duckdb.connect(str(database)) as con:
        con.execute("DELETE FROM line_upgrade_scores")
    empty = _client(database).get("/lines/top", params={"region": "MN"})
    assert empty.status_code == 503
    assert empty.json()["error"]["details"]["reason"] == "artifact_unavailable"


def test_top_lines_rejects_invalid_page_bounds(tmp_path: Path) -> None:
    database = tmp_path / "lines.duckdb"
    _database(database)
    response = _client(database).get(
        "/lines/top", params={"region": "MN", "limit": 101}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"

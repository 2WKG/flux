from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings


def client(path):
    return TestClient(create_app(Settings(duckdb_path=path)))


def db(path):
    c = duckdb.connect(str(path))
    c.execute(
        "CREATE TABLE site_candidates (site_id BIGINT,name TEXT,kind TEXT,county_fips TEXT,source_name TEXT,source_ref TEXT,source_version TEXT,source_retrieved_at TIMESTAMP,fixture_batch_id TEXT)"
    )
    c.execute(
        "CREATE TABLE site_scores (site_id BIGINT,scenario_id TEXT,unit_mw INTEGER,safety_score DOUBLE,safety_flags_json JSON,grid_value_score DOUBLE,lol_reduction_mwh DOUBLE,congestion_relief_pct DOUBLE,blackstart_reach_mw DOUBLE)"
    )
    c.execute(
        "INSERT INTO site_candidates VALUES (1,'fixture site','coal_retired','27001','fixture','test','1','2026-01-01','batch')"
    )
    c.execute("INSERT INTO site_scores VALUES (1,'mn_fixture',300,10,'[]',2,3,4,5)")
    c.close()


def test_site_and_comparison_reads_are_server_side(tmp_path: Path):
    p = tmp_path / "x.duckdb"
    db(p)
    r = client(p).post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )
    assert r.status_code == 200
    assert r.json()["provenance"]["source_name"] == "fixture"
    q = client(p).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )
    assert q.status_code == 200 and q.json()["interventions"][0]["site_id"] == "1"


def test_missing_artifact_is_unavailable(tmp_path: Path):
    r = client(tmp_path / "none.duckdb").post(
        "/site-score", json={"site_id": "1", "unit_mw": 300, "scenario_id": "x"}
    )
    assert r.status_code == 503 and r.json()["status"] == "unavailable"


def test_line_comparison_is_not_invented(tmp_path: Path):
    p = tmp_path / "x.duckdb"
    db(p)
    r = client(p).post(
        "/compare", json={"scenario_id": "mn_fixture", "intervention_ids": ["line:1"]}
    )
    assert (
        r.status_code == 503
        and r.json()["error"]["details"]["reason"] == "unsupported_request"
    )

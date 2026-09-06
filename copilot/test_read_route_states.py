"""Cross-route HTTP acceptance coverage for persisted Minnesota read states."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from pipelines.minnesota_schema import SCHEMA_VERSION, ensure_minnesota_schema


def _client(path: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=path)))


def _database(path: Path) -> None:
    with duckdb.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE site_candidates (site_id BIGINT, name TEXT, kind TEXT, "
            "county_fips TEXT, source_name TEXT, source_ref TEXT, source_version TEXT, "
            "source_retrieved_at TIMESTAMP, fixture_batch_id TEXT)"
        )
        con.execute(
            "CREATE TABLE site_scores (site_id BIGINT, scenario_id TEXT, unit_mw INTEGER, "
            "safety_score DOUBLE, safety_flags_json JSON, grid_value_score DOUBLE, "
            "lol_reduction_mwh DOUBLE, congestion_relief_pct DOUBLE, "
            "blackstart_reach_mw DOUBLE, model_mode TEXT, limitations_json JSON, "
            "source_name TEXT, source_ref TEXT, source_version TEXT, "
            "source_retrieved_at TIMESTAMP, fixture_batch_id TEXT)"
        )
        con.execute(
            "CREATE TABLE lines (line_id BIGINT, from_bus BIGINT, to_bus BIGINT, "
            "base_kv DOUBLE)"
        )
        con.execute(
            "CREATE TABLE line_upgrade_scores (line_id BIGINT, scenario_id TEXT, "
            "ranking_version TEXT, computed_at TIMESTAMP, source_name TEXT, source_ref TEXT, "
            "source_kind TEXT, mw_per_musd DOUBLE, congestion_usd_yr DOUBLE, "
            "dlr_uplift_mw DOUBLE, reconductor_uplift_mw DOUBLE, dlr_cost_usd DOUBLE, "
            "reconductor_cost_usd DOUBLE, ferc_screen_pass BOOLEAN, spark_eligible BOOLEAN, "
            "simulation_run_id TEXT)"
        )
        con.execute(
            "CREATE TABLE line_upgrade_detail (line_id BIGINT, scenario_id TEXT, region TEXT, "
            "best_tech TEXT, congestion_method TEXT)"
        )
        con.execute(
            "INSERT INTO site_candidates VALUES "
            "(1, 'fixture site', 'coal_retired', '27001', 'fixture:site', "
            "'fixture://site', 'v1', '2026-01-01', 'batch-1')"
        )
        con.execute(
            "INSERT INTO site_scores VALUES "
            "(1, 'mn_fixture', 300, 91, '[\"fixture safety flag\"]', 80, 70, 6, "
            "12, 'topology', '[\"fixture limitation\"]', 'fixture:site-score', "
            "'fixture://site-score', 'v1', '2026-01-01', 'batch-1')"
        )
        con.execute("INSERT INTO lines VALUES (10, 1, 2, 230)")
        con.execute(
            "INSERT INTO line_upgrade_scores VALUES "
            "(10, 'mn_fixture', 'v1', '2026-01-01', 'fixture:line-score', "
            "'fixture://line-score', 'fixture', 20, 2, 10, 9, 3, 4, true, false, NULL)"
        )
        con.execute(
            "INSERT INTO line_upgrade_detail VALUES "
            "(10, 'mn_fixture', 'mn', 'dlr', 'exact')"
        )
        ensure_minnesota_schema(con)


def _score(
    path: Path,
    artifact_id: str,
    *,
    components: str,
    metric: str = "comparison",
    model_mode: str = "topology",
) -> None:
    component_values = json.loads(components)
    source_identity = {
        "family": "critical_elements" if metric == "critical_element" else "comparison",
        "scenario_id": component_values["scenario_id"],
    }
    if metric == "critical_element":
        source_identity |= {
            "region": "mn",
            "element_id": component_values["element_id"],
        }
    else:
        source_identity["intervention_id"] = component_values["intervention_id"]
    identity = json.dumps(
        {"source_identity": source_identity}, sort_keys=True, separators=(",", ":")
    )
    with duckdb.connect(str(path)) as con:
        con.execute(
            "INSERT INTO mn_artifact_manifests VALUES "
            "(?, 'score', ?, 'mn', 'available', ?, ?, CURRENT_TIMESTAMP, '[]', "
            "'[\"fixture limitation\"]', '[]')",
            [artifact_id, SCHEMA_VERSION, model_mode, identity],
        )
        con.execute(
            "INSERT INTO mn_artifact_provenance VALUES "
            "(?, 0, 'fixture:score', 'fixture://score', 'v1', CURRENT_TIMESTAMP, "
            "'test fixture', ?, ?, FALSE)",
            [artifact_id, artifact_id, "a" * 64],
        )
        con.execute(
            "INSERT INTO mn_score_results VALUES (?, ?, 3, 'MW', ?, 'hypothetical')",
            [artifact_id, metric, components],
        )


def _unavailable_score_manifest(
    path: Path,
    artifact_id: str,
    *,
    family: str,
    scenario_id: str | None = None,
    intervention_id: str | None = None,
    region: str = "mn",
) -> None:
    if family == "comparison":
        assert scenario_id is not None
        assert intervention_id is not None
        source_identity = {
            "family": "comparison",
            "scenario_id": scenario_id,
            "intervention_id": intervention_id,
        }
    else:
        assert family == "critical_elements"
        source_identity = {
            "family": "critical_elements",
            "region": region,
            "status": "unavailable",
        }
    identity = json.dumps(
        {"source_identity": source_identity}, sort_keys=True, separators=(",", ":")
    )
    with duckdb.connect(str(path)) as con:
        con.execute(
            "INSERT INTO mn_artifact_manifests VALUES "
            "(?, 'score', ?, ?, 'unavailable', 'not_applicable', ?, CURRENT_TIMESTAMP, "
            "'[]', '[\"not built\"]', '[]')",
            [artifact_id, SCHEMA_VERSION, region, identity],
        )


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "routes.duckdb"
    _database(path)
    _score(
        path,
        "mn:score:comparison",
        components='{"scenario_id":"mn_fixture","intervention_id":"site:1@300"}',
    )
    _score(
        path,
        "mn:score:critical",
        metric="critical_element",
        components=(
            '{"scenario_id":"mn_fixture","element_id":"line-10","kind":"line",'
            '"critical_loads_lost":["load-1"],"runs":2}'
        ),
    )
    return path


def _assert_unavailable(response, reason: str, artifact: str) -> None:
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["data"] is None
    assert response.json()["error"]["code"] == "unavailable"
    assert response.json()["error"]["details"]["artifact"] == artifact
    assert response.json()["error"]["details"]["reason"] == reason


def test_persisted_results_expose_evidence_on_each_read_route(database: Path) -> None:
    client = _client(database)

    site = client.post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )
    lines = client.get("/lines/top", params={"region": "mn"})
    comparison = client.post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )
    critical = client.get("/elements/critical", params={"region": "mn"})

    assert site.status_code == lines.status_code == comparison.status_code == 200
    assert site.json()["model_mode"] == "topology"
    assert site.json()["limitations"] == ["fixture limitation"]
    assert (
        site.json()["provenance"]["site_score"]["source_name"] == "fixture:site-score"
    )
    assert lines.json()["status"] == "available"
    assert lines.json()["provenance"][0]["source_kind"] == "fixture"
    assert comparison.json()["interventions"][0]["model_mode"] == "topology"
    assert comparison.json()["interventions"][0]["limitations"] == [
        "fixture limitation"
    ]
    assert (
        comparison.json()["interventions"][0]["provenance"][0]["source_name"]
        == "fixture:score"
    )
    assert critical.json()["elements"][0]["model_mode"] == "topology"
    assert critical.json()["elements"][0]["limitations"] == ["fixture limitation"]
    assert (
        critical.json()["elements"][0]["provenance"][0]["source_name"]
        == "fixture:score"
    )


def test_absent_results_return_the_unavailable_envelope(database: Path) -> None:
    client = _client(database)
    with duckdb.connect(str(database)) as con:
        con.execute("DELETE FROM site_scores")
        con.execute("DELETE FROM line_upgrade_scores")
        con.execute("DELETE FROM mn_score_results")

    _assert_unavailable(
        client.post(
            "/site-score",
            json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
        ),
        "no_persisted_outcome",
        "site_scores",
    )
    _assert_unavailable(
        client.get("/lines/top", params={"region": "mn"}),
        "artifact_unavailable",
        "line_upgrade_scores",
    )
    _assert_unavailable(
        client.post(
            "/compare",
            json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
        ),
        "no_qualified_result",
        "comparison",
    )
    _assert_unavailable(
        client.get("/elements/critical", params={"region": "mn"}),
        "no_qualified_result",
        "critical_elements",
    )


def test_unavailable_artifacts_return_empty_truthful_envelopes(tmp_path: Path) -> None:
    missing_site = _client(tmp_path / "missing-site.duckdb").post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )

    missing_lines_db = tmp_path / "missing-lines.duckdb"
    _database(missing_lines_db)
    with duckdb.connect(str(missing_lines_db)) as con:
        con.execute("DROP TABLE line_upgrade_scores")
    missing_lines = _client(missing_lines_db).get("/lines/top", params={"region": "mn"})

    unavailable_db = tmp_path / "unavailable-manifests.duckdb"
    _database(unavailable_db)
    _unavailable_score_manifest(
        unavailable_db,
        "mn:score:unavailable-comparison",
        family="comparison",
        scenario_id="mn_fixture",
        intervention_id="site:1@300",
    )
    _unavailable_score_manifest(
        unavailable_db,
        "mn:score:unavailable-critical",
        family="critical_elements",
    )
    with duckdb.connect(str(unavailable_db), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM mn_score_results").fetchone() == (0,)

    unavailable_comparison = _client(unavailable_db).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )
    unavailable_critical = _client(unavailable_db).get(
        "/elements/critical", params={"region": "mn"}
    )

    _assert_unavailable(missing_site, "missing", "database")
    _assert_unavailable(missing_lines, "artifact_unavailable", "line_upgrade_scores")
    _assert_unavailable(unavailable_comparison, "artifact_unavailable", "comparison")
    _assert_unavailable(
        unavailable_critical, "artifact_unavailable", "critical_elements"
    )


def test_non_topology_artifacts_are_explicitly_unsupported(database: Path) -> None:
    client = _client(database)
    with duckdb.connect(str(database)) as con:
        con.execute("UPDATE site_scores SET model_mode='aggregate'")
        con.execute(
            "UPDATE mn_artifact_manifests SET model_mode='aggregate' "
            "WHERE artifact_id IN ('mn:score:comparison', 'mn:score:critical')"
        )

    _assert_unavailable(
        client.post(
            "/site-score",
            json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
        ),
        "unsupported_model_mode",
        "site_scores",
    )
    _assert_unavailable(
        client.post(
            "/compare",
            json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
        ),
        "unsupported_model_mode",
        "comparison",
    )
    _assert_unavailable(
        client.get("/elements/critical", params={"region": "mn"}),
        "unsupported_model_mode",
        "critical_elements",
    )


def test_invalid_input_is_rejected_before_a_persisted_read(database: Path) -> None:
    client = _client(database)
    responses = (
        client.post(
            "/site-score",
            json={"site_id": "1", "unit_mw": 200, "scenario_id": "mn_fixture"},
        ),
        client.get("/lines/top", params={"region": "mn", "tech": "invalid"}),
        client.post(
            "/compare",
            json={"scenario_id": "mn_fixture", "intervention_ids": ["site:"]},
        ),
        client.get("/elements/critical", params={"region": "mn", "n": 0}),
    )

    for response in responses:
        assert response.status_code == 422
        assert response.json()["status"] == "error"
        assert response.json()["error"]["code"] == "invalid_input"

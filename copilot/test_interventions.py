from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from pipelines.minnesota_schema import SCHEMA_VERSION, ensure_minnesota_schema


def client(path: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=path)))


def db(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE site_candidates (site_id BIGINT,name TEXT,kind TEXT,county_fips TEXT,source_name TEXT,source_ref TEXT,source_version TEXT,source_retrieved_at TIMESTAMP,fixture_batch_id TEXT)"
    )
    con.execute(
        "CREATE TABLE site_scores (site_id BIGINT,scenario_id TEXT,unit_mw INTEGER,safety_score DOUBLE,safety_flags_json JSON,grid_value_score DOUBLE,lol_reduction_mwh DOUBLE,congestion_relief_pct DOUBLE,blackstart_reach_mw DOUBLE,model_mode TEXT,limitations_json JSON,source_name TEXT,source_ref TEXT,source_version TEXT,source_retrieved_at TIMESTAMP,fixture_batch_id TEXT)"
    )
    con.execute(
        "INSERT INTO site_candidates VALUES (1,'fixture site','coal_retired','27001','fixture:site','test','1','2026-01-01','batch')"
    )
    con.execute(
        "INSERT INTO site_scores VALUES (1,'mn_fixture',300,10,'[]',2,3,4,5,'topology','[\"fixture limitation\"]','fixture:site-score','site-score-test','1','2026-01-01','batch')"
    )
    con.close()


def score_artifact(
    path: Path,
    artifact_id: str,
    *,
    components: str,
    metric: str = "comparison",
    score: float = 3.0,
    mode: str = "topology",
    geography_id: str = "mn",
    availability: str = "available",
) -> None:
    with duckdb.connect(str(path)) as con:
        ensure_minnesota_schema(con)
        con.execute(
            "INSERT INTO mn_artifact_manifests VALUES (?, 'score', ?, ?, ?, ?, '{}', CURRENT_TIMESTAMP, '[]', '[\"fixture limitation\"]', '[]')",
            [artifact_id, SCHEMA_VERSION, geography_id, availability, mode],
        )
        con.execute(
            "INSERT INTO mn_artifact_provenance VALUES (?, 0, 'fixture:synthetic', 'fixture://score', 'v1', CURRENT_TIMESTAMP, 'test fixture', ?, ?, FALSE)",
            [artifact_id, artifact_id, "a" * 64],
        )
        con.execute(
            "INSERT INTO mn_score_results VALUES (?, ?, ?, 'MW', ?, 'hypothetical')",
            [artifact_id, metric, score, components],
        )


def test_site_read_is_server_side_and_unqualified_comparison_is_unavailable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "x.duckdb"
    db(path)
    response = client(path).post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )
    assert response.status_code == 200
    assert response.json()["model_mode"] == "topology"
    assert response.json()["limitations"] == ["fixture limitation"]
    assert response.json()["source_kind"] == "fixture"
    assert (
        response.json()["provenance"]["site_score"]["source_name"]
        == "fixture:site-score"
    )

    comparison = client(path).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )
    assert comparison.status_code == 503
    assert comparison.json()["error"]["details"]["reason"] == "missing"


def test_comparison_reads_a_qualified_persisted_score_without_deriving_a_delta(
    tmp_path: Path,
) -> None:
    path = tmp_path / "comparison.duckdb"
    db(path)
    score_artifact(
        path,
        "mn:score:0000000000000001",
        components='{"scenario_id":"mn_fixture","intervention_id":"site:1@300"}',
    )

    response = client(path).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )

    assert response.status_code == 200
    intervention = response.json()["interventions"][0]
    assert intervention["score_value"] == 3.0
    assert intervention["scenario_id"] == "mn_fixture"
    assert intervention["intervention_id"] == "site:1@300"
    assert intervention["provenance"][0]["source_name"] == "fixture:synthetic"
    assert intervention["model_mode"] == "topology"
    assert intervention["limitations"] == ["fixture limitation"]
    assert response.json()["comparison_status"] == "persisted_scores_not_derived_deltas"


def test_aggregate_comparison_is_explicitly_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "aggregate.duckdb"
    db(path)
    score_artifact(
        path,
        "mn:score:0000000000000002",
        mode="aggregate",
        components='{"scenario_id":"mn_fixture","intervention_id":"site:1@300"}',
    )

    response = client(path).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "unsupported_model_mode"


def test_line_comparison_reads_a_named_persisted_score(tmp_path: Path) -> None:
    path = tmp_path / "line-comparison.duckdb"
    db(path)
    score_artifact(
        path,
        "mn:score:0000000000000003",
        components='{"scenario_id":"mn_fixture","intervention_id":"line:line-1"}',
    )

    response = client(path).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["line:line-1"]},
    )
    assert response.status_code == 200
    assert response.json()["interventions"][0]["intervention_id"] == "line:line-1"


def test_critical_elements_use_persisted_values_with_stable_paging(
    tmp_path: Path,
) -> None:
    path = tmp_path / "critical.duckdb"
    db(path)
    for artifact_id, element_id, score in (
        ("mn:score:000000000000000a", "line-a", 5.0),
        ("mn:score:000000000000000b", "line-b", 5.0),
        ("mn:score:000000000000000c", "line-c", 2.0),
    ):
        score_artifact(
            path,
            artifact_id,
            metric="critical_element",
            score=score,
            components=(
                '{"scenario_id":"mn_fixture","element_id":"'
                + element_id
                + '","kind":"line","critical_loads_lost":["cl-1"],"runs":2}'
            ),
        )

    first_page = client(path).get("/elements/critical", params={"region": "mn", "n": 2})
    assert first_page.status_code == 200
    assert [item["element_id"] for item in first_page.json()["elements"]] == [
        "line-a",
        "line-b",
    ]
    assert first_page.json()["elements"][0]["scenario_id"] == "mn_fixture"
    assert first_page.json()["elements"][0]["provenance"]
    assert first_page.json()["elements"][0]["limitations"] == ["fixture limitation"]
    assert first_page.json()["partial"] is False

    second_page = client(path).get(
        "/elements/critical", params={"region": "mn", "n": 1, "offset": 2}
    )
    assert second_page.status_code == 200
    assert [item["element_id"] for item in second_page.json()["elements"]] == ["line-c"]


def test_missing_and_invalid_comparison_inputs_are_not_empty_successes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "x.duckdb"
    db(path)
    assert (
        client(path)
        .post(
            "/compare",
            json={"scenario_id": "mn_fixture", "intervention_ids": ["line:1"]},
        )
        .status_code
        == 503
    )
    critical = client(path).get("/elements/critical", params={"region": "mn"})
    assert critical.status_code == 503
    assert critical.json()["error"]["details"]["reason"] == "missing"
    for identifier in ("site:", "site:1@not-a-number", "site:1@200"):
        assert (
            client(path)
            .post(
                "/compare",
                json={"scenario_id": "mn_fixture", "intervention_ids": [identifier]},
            )
            .status_code
            == 422
        )


def test_declared_unavailable_score_is_not_reported_as_invalid_persisted_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unavailable.duckdb"
    db(path)
    score_artifact(
        path,
        "mn:score:0000000000000004",
        availability="unavailable",
        components='{"scenario_id":"mn_fixture","intervention_id":"site:1@300"}',
    )

    response = client(path).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "artifact_unavailable"


def test_malformed_safety_flags_fail_closed(tmp_path: Path):
    p = tmp_path / "x.duckdb"
    db(p)
    with duckdb.connect(str(p)) as con:
        con.execute("UPDATE site_scores SET safety_flags_json='\"not-a-list\"'")
    assert (
        client(p)
        .post(
            "/site-score",
            json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
        )
        .status_code
        == 503
    )


def test_site_score_rejects_aggregate_outcomes(tmp_path: Path):
    p = tmp_path / "x.duckdb"
    db(p)
    with duckdb.connect(str(p)) as con:
        con.execute("UPDATE site_scores SET model_mode='aggregate'")
    response = client(p).post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "unsupported_model_mode"


def test_site_score_without_persisted_outcome_is_unavailable(tmp_path: Path):
    p = tmp_path / "x.duckdb"
    db(p)
    response = client(p).post(
        "/site-score",
        json={"site_id": "99", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "no_persisted_outcome"

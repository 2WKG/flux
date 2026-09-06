"""Cross-route HTTP acceptance coverage for persisted Minnesota read states.

The database is built through the real contracts - `pipelines.db.connect`
(`ensure_schema`, SCHEMA_VERSION 2.1.0) and `ensure_minnesota_schema` - via
`copilot.persisted_fixtures`, so a column rename or constraint change in either
fails these acceptance tests instead of leaving a hand-typed shadow schema
green. The earlier hand-written fixture invented `site_scores.model_mode` and
`site_scores.limitations_json`, which the real DDL does not define.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from copilot.api.envelope import API_VERSION
from copilot.api.errors import API_VERSION_HEADER
from copilot.app import create_app
from copilot.config import Settings
from copilot.persisted_fixtures import persisted_read_route_database
from pipelines.minnesota_schema import SCHEMA_VERSION


def _client(path: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=path)))


def _database(path: Path) -> None:
    persisted_read_route_database(path)


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
        components=json.dumps(
            {
                "scenario_id": "mn_fixture",
                "intervention_id": "site:1@300",
                "baseline_run_id": "run-baseline",
                "run_id": "run-with",
                "lol_reduction_mwh": 3.0,
                "customer_hours_avoided": 12.0,
                "critical_loads_protected": ["load-1"],
            }
        ),
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
    """Pin the whole documented failure envelope, not just its reason.

    `docs/specs/05-copilot.md` states that every response carries
    `X-Flux-Api-Version: v1`, and that an unavailable artifact is the shared
    retryable envelope. Asserting only `status`/`data`/`reason` left the code,
    the retryability, the meta version and the header free to drift.
    """

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["data"] is None
    assert body["error"]["code"] == "unavailable"
    assert body["error"]["retryable"] is True
    assert body["error"]["retry_after_s"] == 30
    assert body["error"]["details"]["artifact"] == artifact
    assert body["error"]["details"]["reason"] == reason
    assert body["meta"]["api_version"] == API_VERSION == "v1"
    assert response.headers[API_VERSION_HEADER] == "v1"


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

    assert (
        site.status_code
        == lines.status_code
        == comparison.status_code
        == critical.status_code
        == 200
    )
    assert site.json()["model_mode"] == "topology"
    assert site.json()["limitations"] == ["fixture limitation"]
    assert (
        site.json()["provenance"]["site_score"]["source_name"] == "fixture:site-score"
    )
    assert lines.json()["status"] == "available"
    # The ready cell must assert the rows themselves: a ranking route that
    # returns zero lines with valid provenance is not a ready read.
    assert [line["line_id"] for line in lines.json()["lines"]] == ["10"]
    assert lines.json()["scenario_id"] == "mn_fixture"
    assert lines.json()["provenance"][0]["source_kind"] == "fixture"
    assert comparison.json()["interventions"][0]["intervention_id"] == "site:1@300"
    assert comparison.json()["interventions"][0]["lol_reduction_mwh"] == 3.0
    assert comparison.json()["evidence"][0]["model_mode"] == "topology"
    assert comparison.json()["evidence"][0]["limitations"] == ["fixture limitation"]
    assert (
        comparison.json()["evidence"][0]["provenance"][0]["source_name"]
        == "fixture:score"
    )
    assert [item["element_id"] for item in critical.json()["elements"]] == ["line-10"]
    assert critical.json()["scenario_ids"] == ["mn_fixture"]
    assert critical.json()["evidence"][0]["model_mode"] == "topology"
    assert critical.json()["evidence"][0]["limitations"] == ["fixture limitation"]
    assert (
        critical.json()["evidence"][0]["provenance"][0]["source_name"]
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
        # `model_mode` lives on the manifest, not on site_scores: the real DDL
        # 2.1.0 contract defines no such column.
        con.execute("UPDATE mn_artifact_manifests SET model_mode='aggregate'")

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


def test_invalid_input_is_rejected_before_a_persisted_read(tmp_path: Path) -> None:
    """The ordering claim is made real: the database does not exist.

    Every route below would answer 503 if it attempted a persisted read, so a
    422 is only reachable when the input boundary rejects first.
    """

    client = _client(tmp_path / "never-created.duckdb")
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
        assert response.json()["error"]["retryable"] is False
        assert response.json()["meta"]["api_version"] == "v1"
        assert response.headers[API_VERSION_HEADER] == "v1"

    # The same reads against the same absent database are 503, which is what
    # makes the 422s above evidence of ordering rather than of an absent file.
    assert (
        client.post(
            "/site-score",
            json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
        ).status_code
        == 503
    )
    assert client.get("/elements/critical", params={"region": "mn"}).status_code == 503

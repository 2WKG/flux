"""HTTP checks for the persisted site-score and comparison reads.

Fixtures are built through `pipelines.db.connect` (real `ensure_schema` DDL) and
`pipelines.minnesota_schema.ensure_minnesota_schema`, so a column rename or
constraint change in either contract fails this suite instead of leaving a
hand-typed shadow schema green.  `copilot/test_tools_lines.py` states the same
rule for the line-upgrade reader.
"""

from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.persisted_fixtures import persisted_site_database


def client(path):
    return TestClient(create_app(Settings(duckdb_path=path)))


def db(path, **kwargs):
    persisted_site_database(Path(path), **kwargs)


def test_site_and_comparison_reads_are_server_side(tmp_path: Path):
    p = tmp_path / "x.duckdb"
    db(p)
    r = client(p).post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )
    assert r.status_code == 200
    assert r.json()["model_mode"] == "topology"
    assert r.json()["limitations"] == ["fixture limitation"]
    assert r.json()["source_kind"] == "fixture"
    assert r.json()["artifact_id"] == "mn:score:site-1"
    assert r.json()["provenance"]["site_score"]["source_name"] == "fixture:site-score"
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


def test_invalid_capacity_and_identifiers_are_validation_errors(tmp_path: Path):
    p = tmp_path / "x.duckdb"
    db(p)
    for body in ({"site_id": "1", "unit_mw": 200, "scenario_id": "mn_fixture"},):
        assert client(p).post("/site-score", json=body).status_code == 422
    for identifier in ("site:", "site:1@not-a-number", "site:1@200"):
        assert (
            client(p)
            .post(
                "/compare",
                json={"scenario_id": "mn_fixture", "intervention_ids": [identifier]},
            )
            .status_code
            == 422
        )


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
    db(p, model_mode="aggregate")
    response = client(p).post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "unsupported_model_mode"


def test_site_score_without_persisted_outcome_is_unavailable(tmp_path: Path):
    """A persisted site with no score for this scenario/unit is a 503, retryable."""

    p = tmp_path / "x.duckdb"
    db(p)
    response = client(p).post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 1000, "scenario_id": "mn_fixture"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "no_persisted_outcome"


def test_unknown_site_is_not_found_rather_than_retryable(tmp_path: Path):
    """A site that is not persisted at all is permanent: 404, never a retry loop."""

    p = tmp_path / "x.duckdb"
    db(p)
    response = client(p).post(
        "/site-score",
        json={"site_id": "99", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )
    assert response.status_code == 404
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "not_found"
    assert body["error"]["retryable"] is False
    assert body["error"]["details"]["site_id"] == "99"
    assert response.headers["X-Flux-Api-Version"] == "v1"


def test_outcome_metadata_comes_from_the_manifest_not_from_site_scores(tmp_path: Path):
    """The route must not read model metadata from a column the DDL lacks.

    `pipelines/db.py` SCHEMA_VERSION 2.1.0 defines no `site_scores.model_mode`
    and no `site_scores.limitations_json`; both live on the artifact manifest.
    A real-DDL database with a qualified outcome must therefore answer 200, and
    an outcome whose manifest is absent must say so by name.
    """

    with_manifest = tmp_path / "with.duckdb"
    db(with_manifest)
    columns = {
        row[1]
        for row in duckdb.connect(str(with_manifest))
        .execute("PRAGMA table_info('site_scores')")
        .fetchall()
    }
    assert "model_mode" not in columns
    assert "limitations_json" not in columns
    assert (
        client(with_manifest)
        .post(
            "/site-score",
            json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
        )
        .status_code
        == 200
    )

    without_manifest = tmp_path / "without.duckdb"
    db(without_manifest, with_manifest=False)
    response = client(without_manifest).post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )
    assert response.status_code == 503
    assert (
        response.json()["error"]["details"]["reason"] == "outcome_metadata_unavailable"
    )


def test_declared_unavailable_outcome_metadata_is_named(tmp_path: Path):
    p = tmp_path / "x.duckdb"
    db(p, model_mode="not_applicable", availability="unavailable")
    response = client(p).post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "artifact_unavailable"


def test_missing_provenance_is_named_rather_than_served(tmp_path: Path):
    p = tmp_path / "x.duckdb"
    db(p)
    with duckdb.connect(str(p)) as con:
        con.execute("UPDATE site_scores SET source_ref=''")
    response = client(p).post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "provenance_missing"


def test_underivable_topology_label_is_unavailable_not_a_null_in_a_200(tmp_path: Path):
    """The sibling GET /cascade contract forbids serving a null label in a 200."""

    p = tmp_path / "x.duckdb"
    db(p, site_source_name="acme-registry", score_source_name="acme-scores")
    response = client(p).post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "topology_label_unavailable"

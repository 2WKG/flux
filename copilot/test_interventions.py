"""HTTP checks for the persisted site-score and comparison reads.

Fixtures are built through `pipelines.db.connect` (real `ensure_schema` DDL) and
`pipelines.minnesota_schema.ensure_minnesota_schema`, so a column rename or
constraint change in either contract fails this suite instead of leaving a
hand-typed shadow schema green.  `copilot/test_tools_lines.py` states the same
rule for the line-upgrade reader.
"""

import json
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.persisted_fixtures import persisted_site_database
from pipelines.minnesota_schema import SCHEMA_VERSION, ensure_minnesota_schema


def client(path: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=path)))


def db(path: Path, **kwargs: object) -> None:
    persisted_site_database(Path(path), **kwargs)  # type: ignore[arg-type]


def score_artifact(
    path: Path,
    artifact_id: str,
    *,
    components: str,
    metric: str = "comparison",
    score: float = 3.0,
    mode: str = "topology",
    geography_id: str = "mn",
) -> None:
    component_values = json.loads(components)
    source_identity = {
        "family": "critical_elements" if metric == "critical_element" else "comparison",
        "scenario_id": component_values["scenario_id"],
    }
    if metric == "critical_element":
        source_identity |= {
            "region": geography_id,
            "element_id": component_values["element_id"],
        }
    else:
        source_identity["intervention_id"] = component_values["intervention_id"]
    identity = json.dumps(
        {
            "artifact_kind": "score",
            "geography_id": geography_id,
            "model_mode": mode,
            "source_identity": source_identity,
            "source_version": "v1",
            "content_sha256": "a" * 64,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    with duckdb.connect(str(path)) as con:
        ensure_minnesota_schema(con)
        con.execute(
            "INSERT INTO mn_artifact_manifests VALUES (?, 'score', ?, ?, 'available', ?, ?, CURRENT_TIMESTAMP, '[]', '[\"fixture limitation\"]', '[]')",
            [artifact_id, SCHEMA_VERSION, geography_id, mode, identity],
        )
        con.execute(
            "INSERT INTO mn_artifact_provenance VALUES (?, 0, 'fixture:synthetic', 'fixture://score', 'v1', CURRENT_TIMESTAMP, 'test fixture', ?, ?, FALSE)",
            [artifact_id, artifact_id, "a" * 64],
        )
        con.execute(
            "INSERT INTO mn_score_results VALUES (?, ?, ?, 'MW', ?, 'hypothetical')",
            [artifact_id, metric, score, components],
        )


def unavailable_score_manifest(
    path: Path,
    artifact_id: str,
    *,
    family: str,
    scenario_id: str | None = None,
    intervention_id: str | None = None,
    region: str = "mn",
) -> None:
    if family == "comparison":
        if scenario_id is None or intervention_id is None:
            raise ValueError(
                "comparison unavailable identity requires scenario and intervention"
            )
        source_identity = {
            "family": family,
            "scenario_id": scenario_id,
            "intervention_id": intervention_id,
        }
    elif family == "critical_elements":
        source_identity = {
            "family": family,
            "region": region,
            "status": "unavailable",
        }
    else:
        raise ValueError("unsupported unavailable score family")
    identity = json.dumps(
        {
            "artifact_kind": "score",
            "geography_id": region,
            "model_mode": "not_applicable",
            "source_identity": source_identity,
            "source_version": "v1",
            "content_sha256": "b" * 64,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    with duckdb.connect(str(path)) as con:
        ensure_minnesota_schema(con)
        con.execute(
            "INSERT INTO mn_artifact_manifests VALUES (?, 'score', ?, ?, 'unavailable', 'not_applicable', ?, CURRENT_TIMESTAMP, '[]', '[\"not built\"]', '[]')",
            [artifact_id, SCHEMA_VERSION, region, identity],
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
    assert response.json()["artifact_id"] == "mn:score:site-1"
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


def test_unrelated_invalid_score_does_not_poison_a_qualified_comparison(
    tmp_path: Path,
) -> None:
    path = tmp_path / "comparison-scope.duckdb"
    db(path)
    score_artifact(
        path,
        "mn:score:0000000000000005",
        components='{"scenario_id":"mn_fixture","intervention_id":"site:1@300"}',
    )
    score_artifact(
        path,
        "mn:score:0000000000000006",
        components='{"scenario_id":"another_scenario","intervention_id":"site:9@300"}',
    )
    with duckdb.connect(str(path)) as con:
        con.execute(
            "UPDATE mn_score_results SET score_components_json='[]' WHERE artifact_id=?",
            ["mn:score:0000000000000006"],
        )

    response = client(path).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )
    assert response.status_code == 200
    assert (
        response.json()["interventions"][0]["artifact_id"]
        == "mn:score:0000000000000005"
    )


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


def test_canonical_unavailable_comparison_manifest_needs_no_domain_row(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unavailable.duckdb"
    db(path)
    unavailable_score_manifest(
        path,
        "mn:score:0000000000000004",
        family="comparison",
        scenario_id="mn_fixture",
        intervention_id="site:1@300",
    )
    with duckdb.connect(str(path), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM mn_score_results").fetchone() == (0,)

    response = client(path).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "artifact_unavailable"


def test_unrelated_unavailable_manifest_does_not_poison_available_comparison(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unavailable-scope.duckdb"
    db(path)
    score_artifact(
        path,
        "mn:score:0000000000000007",
        components='{"scenario_id":"mn_fixture","intervention_id":"site:1@300"}',
    )
    unavailable_score_manifest(
        path,
        "mn:score:0000000000000008",
        family="comparison",
        scenario_id="another_scenario",
        intervention_id="site:9@300",
    )

    response = client(path).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )
    assert response.status_code == 200


def test_canonical_unavailable_critical_manifest_needs_no_domain_row(
    tmp_path: Path,
) -> None:
    path = tmp_path / "critical-unavailable.duckdb"
    db(path)
    unavailable_score_manifest(
        path,
        "mn:score:0000000000000009",
        family="critical_elements",
        region="mn",
    )
    with duckdb.connect(str(path), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM mn_score_results").fetchone() == (0,)

    response = client(path).get("/elements/critical", params={"region": "mn"})
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "artifact_unavailable"


def test_broad_critical_unavailable_manifest_does_not_blanket_a_region(
    tmp_path: Path,
) -> None:
    path = tmp_path / "critical-unavailable-scope.duckdb"
    db(path)
    unavailable_score_manifest(
        path,
        "mn:score:000000000000000a",
        family="critical_elements",
        region="mn",
    )
    with duckdb.connect(str(path)) as con:
        con.execute(
            "UPDATE mn_artifact_manifests SET identity_json=? WHERE artifact_id=?",
            [
                json.dumps(
                    {
                        "artifact_kind": "score",
                        "geography_id": "mn",
                        "model_mode": "not_applicable",
                        "source_identity": {
                            "family": "critical_elements",
                            "region": "mn",
                        },
                        "source_version": "v1",
                        "content_sha256": "b" * 64,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "mn:score:000000000000000a",
            ],
        )

    response = client(path).get("/elements/critical", params={"region": "mn"})
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "no_qualified_result"


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

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
from copilot.tools.schemas import (
    CriticalElement,
    CriticalElementsData,
    Intervention,
    InterventionsData,
)
from pipelines.minnesota_schema import SCHEMA_VERSION, ensure_minnesota_schema


def client(path: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=path)))


def db(path: Path, **kwargs: object) -> None:
    persisted_site_database(Path(path), **kwargs)  # type: ignore[arg-type]


def comparison_components(
    intervention_id: str,
    *,
    scenario_id: str = "mn_fixture",
    baseline_run_id: str = "run-baseline",
    run_id: str = "run-with",
    lol_reduction_mwh: float = 3.0,
    customer_hours_avoided: float = 12.0,
    critical_loads_protected: tuple[str, ...] = ("cl-1",),
) -> str:
    """The persisted component payload the A8 comparison shape is read from."""

    return json.dumps(
        {
            "scenario_id": scenario_id,
            "intervention_id": intervention_id,
            "baseline_run_id": baseline_run_id,
            "run_id": run_id,
            "lol_reduction_mwh": lol_reduction_mwh,
            "customer_hours_avoided": customer_hours_avoided,
            "critical_loads_protected": list(critical_loads_protected),
        }
    )


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
    assert comparison.json()["error"]["details"]["reason"] == "no_qualified_result"

    # The mn_* namespace absent entirely is a distinct, separately named state.
    absent = tmp_path / "absent.duckdb"
    db(absent, with_minnesota=False)
    without_tables = client(absent).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )
    assert without_tables.status_code == 503
    assert without_tables.json()["error"]["details"]["reason"] == "missing"


def test_comparison_reads_a_qualified_persisted_score_without_deriving_a_delta(
    tmp_path: Path,
) -> None:
    path = tmp_path / "comparison.duckdb"
    db(path)
    score_artifact(
        path,
        "mn:score:0000000000000001",
        components=comparison_components("site:1@300"),
    )

    response = client(path).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )

    assert response.status_code == 200
    body = response.json()
    intervention = body["interventions"][0]
    assert intervention["intervention_id"] == "site:1@300"
    assert intervention["kind"] == "site"
    assert intervention["run_id"] == "run-with"
    assert intervention["lol_reduction_mwh"] == 3.0
    assert intervention["customer_hours_avoided"] == 12.0
    assert intervention["critical_loads_protected"] == ["cl-1"]
    assert body["baseline_run_id"] == "run-baseline"
    assert body["assumptions"] == []
    evidence = body["evidence"][0]
    assert evidence["score_value"] == 3.0
    assert evidence["scenario_id"] == "mn_fixture"
    assert evidence["intervention_id"] == "site:1@300"
    assert evidence["provenance"][0]["source_name"] == "fixture:synthetic"
    assert evidence["model_mode"] == "topology"
    assert evidence["limitations"] == ["fixture limitation"]
    assert body["comparison_status"] == "persisted_scores_not_derived_deltas"


def test_aggregate_comparison_is_explicitly_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "aggregate.duckdb"
    db(path)
    score_artifact(
        path,
        "mn:score:0000000000000002",
        mode="aggregate",
        components=comparison_components("site:1@300"),
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
        components=comparison_components("line:line-1"),
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
        components=comparison_components("site:1@300"),
    )
    score_artifact(
        path,
        "mn:score:0000000000000006",
        components=comparison_components("site:9@300", scenario_id="another_scenario"),
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
    assert response.json()["evidence"][0]["artifact_id"] == "mn:score:0000000000000005"
    assert response.json()["interventions"][0]["intervention_id"] == "site:1@300"


def test_critical_elements_use_persisted_values_with_stable_paging(
    tmp_path: Path,
) -> None:
    path = tmp_path / "critical.duckdb"
    db(path)
    # Inserted against both the primary sort and the tie-break: `line-b` ties
    # `line-a` on score_value and is stored first, so physical order cannot
    # produce the asserted sequence and a non-unique tie-break cannot fake it.
    for artifact_id, element_id, score in (
        ("mn:score:000000000000000b", "line-b", 5.0),
        ("mn:score:000000000000000a", "line-a", 5.0),
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
    assert first_page.json()["scenario_ids"] == ["mn_fixture"]
    assert first_page.json()["evidence"][0]["scenario_id"] == "mn_fixture"
    assert first_page.json()["evidence"][0]["provenance"]
    assert first_page.json()["evidence"][0]["limitations"] == ["fixture limitation"]
    assert first_page.json()["partial"] is False

    second_page = client(path).get(
        "/elements/critical", params={"region": "mn", "n": 1, "offset": 2}
    )
    assert second_page.status_code == 200
    assert [item["element_id"] for item in second_page.json()["elements"]] == ["line-c"]

    # Walking one row at a time must partition the relation exactly: no repeat,
    # no omission, and the tied pair in the documented artifact_id order.
    walked = []
    for offset in range(3):
        page = client(path).get(
            "/elements/critical", params={"region": "mn", "n": 1, "offset": offset}
        )
        assert page.status_code == 200
        walked.extend(item["element_id"] for item in page.json()["elements"])
    assert walked == ["line-a", "line-b", "line-c"]


def test_critical_elements_rejects_an_out_of_bounds_page_with_shared_envelope(
    tmp_path: Path,
) -> None:
    """The bounded query contract fails before a persisted read can occur."""

    path = tmp_path / "critical-invalid-page.duckdb"
    db(path)

    response = client(path).get("/elements/critical", params={"region": "mn", "n": 0})

    assert response.status_code == 422
    assert response.json()["status"] == "error"
    assert response.json()["error"] == {
        "code": "invalid_input",
        "message": "Request parameters do not match the documented contract.",
        "retryable": False,
        "retry_after_s": None,
        "details": {"field": "query.n"},
    }


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
    assert critical.json()["error"]["details"]["reason"] == "no_qualified_result"

    absent = tmp_path / "absent.duckdb"
    db(absent, with_minnesota=False)
    without_tables = client(absent).get("/elements/critical", params={"region": "mn"})
    assert without_tables.status_code == 503
    assert without_tables.json()["error"]["details"]["reason"] == "missing"
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
        components=comparison_components("site:1@300"),
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


def test_site_score_missing_database_is_unavailable(tmp_path: Path) -> None:
    """Restored with #196: /site-score against an absent database is a 503."""

    response = client(tmp_path / "none.duckdb").post(
        "/site-score", json={"site_id": "1", "unit_mw": 300, "scenario_id": "x"}
    )
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_site_score_capacity_bound_is_a_validation_error(tmp_path: Path) -> None:
    """Restored with #196: unit_mw is Literal[300, 1000], not any int."""

    path = tmp_path / "capacity.duckdb"
    db(path)
    assert (
        client(path)
        .post(
            "/site-score",
            json={"site_id": "1", "unit_mw": 200, "scenario_id": "mn_fixture"},
        )
        .status_code
        == 422
    )
    assert (
        client(path)
        .post(
            "/site-score",
            json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
        )
        .status_code
        == 200
    )


def test_compare_payload_validates_against_the_frozen_a8_contract(
    tmp_path: Path,
) -> None:
    """The A8 half of the /compare body is exactly `InterventionsData`.

    The body is a superset: it adds the `evidence` list and `comparison_status`
    this route documents in docs/specs/05-copilot.md.  Every field the frozen
    contract declares is projected here and validated by the frozen model
    itself, so a shape drift is a failure rather than a silent divergence.
    The scenario is one of the four `ScenarioId` values the frozen contract
    admits; a Minnesota scenario id is covered by the spec'd widening.
    """

    path = tmp_path / "a8.duckdb"
    db(path, scenario_id="uri_2021")
    score_artifact(
        path,
        "mn:score:00000000000000a8",
        components=comparison_components("site:1@300", scenario_id="uri_2021"),
    )

    response = client(path).post(
        "/compare",
        json={"scenario_id": "uri_2021", "intervention_ids": ["site:1@300"]},
    )
    assert response.status_code == 200
    body = response.json()

    # `unavailable` is absent because this is an available result; every other
    # frozen field, `provenance` included, is present and persisted.
    assert set(InterventionsData.model_fields) - set(body) == {"unavailable"}
    assert body["provenance"][0]["source_kind"] == "fixture"
    projected = {
        name: body[name] for name in InterventionsData.model_fields if name in body
    }
    data = InterventionsData.model_validate(projected)
    assert data.scenario_id == "uri_2021"
    assert data.baseline_run_id == "run-baseline"
    assert data.interventions[0] == Intervention(
        intervention_id="site:1@300",
        kind="site",
        run_id="run-with",
        lol_reduction_mwh=3.0,
        customer_hours_avoided=12.0,
        critical_loads_protected=["cl-1"],
    )


def test_critical_elements_payload_validates_against_the_frozen_a8_contract(
    tmp_path: Path,
) -> None:
    """The A8 half of the /elements/critical body is `CriticalElementsData`.

    `scenario_ids` was absent entirely before this test existed, so the payload
    could not validate at all.
    """

    path = tmp_path / "a8-critical.duckdb"
    db(path, scenario_id="uri_2021")
    score_artifact(
        path,
        "mn:score:00000000000000c8",
        metric="critical_element",
        score=5.0,
        components=json.dumps(
            {
                "scenario_id": "uri_2021",
                "element_id": "line-a",
                "kind": "line",
                "critical_loads_lost": ["cl-1"],
                "runs": 2,
            }
        ),
    )

    response = client(path).get("/elements/critical", params={"region": "mn", "n": 1})
    assert response.status_code == 200
    body = response.json()

    assert set(CriticalElementsData.model_fields) - set(body) == {"unavailable"}
    assert body["provenance"][0]["source_kind"] == "fixture"
    projected = {
        name: body[name] for name in CriticalElementsData.model_fields if name in body
    }
    data = CriticalElementsData.model_validate(projected)
    assert data.scenario_ids == ["uri_2021"]
    assert data.elements[0] == CriticalElement(
        element_id="line-a",
        kind="line",
        lost_load_mw=5.0,
        critical_loads_lost=["cl-1"],
        runs=2,
    )


def test_comparison_without_persisted_a8_components_is_named_not_defaulted(
    tmp_path: Path,
) -> None:
    """A persisted score with no delta fields is unavailable, never zeroes."""

    path = tmp_path / "no-delta.duckdb"
    db(path)
    score_artifact(
        path,
        "mn:score:00000000000000d0",
        components='{"scenario_id":"mn_fixture","intervention_id":"site:1@300"}',
    )

    response = client(path).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )
    assert response.status_code == 503
    details = response.json()["error"]["details"]
    assert details["reason"] == "persisted_delta_unavailable"
    assert details["field"] == "lol_reduction_mwh"
    assert details["intervention_id"] == "site:1@300"


def test_two_qualified_artifacts_for_one_intervention_are_ambiguous(
    tmp_path: Path,
) -> None:
    """Duplicate qualified scores must be named, never last-write-wins."""

    path = tmp_path / "duplicate.duckdb"
    db(path)
    for artifact_id, lol in (
        ("mn:score:00000000000000aa", 1.0),
        ("mn:score:00000000000000bb", 99.0),
    ):
        score_artifact(
            path,
            artifact_id,
            score=lol,
            components=comparison_components("site:1@300", lol_reduction_mwh=lol),
        )

    response = client(path).post(
        "/compare",
        json={"scenario_id": "mn_fixture", "intervention_ids": ["site:1@300"]},
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "ambiguous_identity"


def test_disagreeing_baselines_are_ambiguous_not_silently_mixed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "baselines.duckdb"
    db(path)
    score_artifact(
        path,
        "mn:score:00000000000000b1",
        components=comparison_components("site:1@300", baseline_run_id="run-a"),
    )
    score_artifact(
        path,
        "mn:score:00000000000000b2",
        components=comparison_components("line:line-1", baseline_run_id="run-b"),
    )

    response = client(path).post(
        "/compare",
        json={
            "scenario_id": "mn_fixture",
            "intervention_ids": ["site:1@300", "line:line-1"],
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "ambiguous_identity"


def test_partial_comparison_is_never_a_200_with_fewer_rows(tmp_path: Path) -> None:
    """Two qualified artifacts for a three-id request is a named failure."""

    path = tmp_path / "partial.duckdb"
    db(path)
    score_artifact(
        path,
        "mn:score:00000000000000p1",
        components=comparison_components("site:1@300"),
    )
    score_artifact(
        path,
        "mn:score:00000000000000p2",
        components=comparison_components("line:line-1"),
    )

    response = client(path).post(
        "/compare",
        json={
            "scenario_id": "mn_fixture",
            "intervention_ids": ["site:1@300", "line:line-1", "line:line-2"],
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "no_qualified_result"
    assert response.json()["data"] is None


def test_critical_partial_counts_the_relation_not_the_page(tmp_path: Path) -> None:
    """`partial` means "fewer than n have any persisted run", not "page ended"."""

    path = tmp_path / "critical-partial.duckdb"
    db(path)
    for artifact_id, element_id in (
        ("mn:score:00000000000000e1", "line-a"),
        ("mn:score:00000000000000e2", "line-b"),
    ):
        score_artifact(
            path,
            artifact_id,
            metric="critical_element",
            score=5.0,
            components=json.dumps(
                {
                    "scenario_id": "mn_fixture",
                    "element_id": element_id,
                    "kind": "line",
                    "critical_loads_lost": ["cl-1"],
                    "runs": 2,
                }
            ),
        )

    # A last page shorter than n is NOT partial: the relation has enough rows.
    last_page = client(path).get(
        "/elements/critical", params={"region": "mn", "n": 2, "offset": 1}
    )
    assert last_page.status_code == 200
    assert len(last_page.json()["elements"]) == 1
    assert last_page.json()["partial"] is False

    # Asking for more elements than the relation holds IS partial.
    over = client(path).get("/elements/critical", params={"region": "mn", "n": 3})
    assert over.status_code == 200
    assert over.json()["partial"] is True

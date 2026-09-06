"""HTTP coverage for qualified prediction and persisted cascade reads.

Success bodies carry the ``status: "available"`` discriminator pinned by
``docs/specs/00-overview.md`` §4.2 (the winning authority); the qualified
``GET /cascade`` success also carries ``X-Flux-Artifact`` (#158).

Fixtures are built on the real ``pipelines.db`` 2.1.0 DDL plus the
``models.outage.persistence`` companion tables and the ``pipelines.minnesota_schema``
namespace, so the tests cannot drift from the columns the routes read.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

import pipelines.db as pdb
from copilot.api import API_VERSION
from copilot.app import create_app
from copilot.config import Settings
from copilot.routes import predictions as predictions_module
from models.outage.persistence import PersistenceError, ensure_persistence_schema
from pipelines.minnesota_schema import SCHEMA_VERSION, ensure_minnesota_schema

SCENARIO = "mn_winter_2023_snow"
OTHER_SCENARIO = "mn_spring_2024_flood"
_FIXTURE_PROVENANCE = (
    "fixture:flux-demo",
    "fixture://minnesota",
    "1.0.0",
    "2026-01-01 00:00:00",
    "fixture:flux-demo@1.0.0",
)
_ACTIVSG_PROVENANCE = (
    "twin.cascade",
    "data/raw/activsg2000/scenarios_ACTIVSg2000.m",
    "2018",
    "2026-09-05 12:00:00",
    "activsg2000@2018",
)
_UNLABELLED_PROVENANCE = (
    "vendor.export",
    "s3://bucket/export.parquet",
    "1",
    "2026-09-05 12:00:00",
    "vendor@1",
)


def _client(path: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=path)))


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _evaluation_sha(index: int) -> str:
    return f"{index:064x}"


def _real_database(path: Path, *, scenarios: tuple[str, ...] = (SCENARIO,)) -> None:
    """Create the shared 2.1.0 contract with the scenarios the fixtures reference."""
    con = pdb.connect(path)
    try:
        for scenario_id in scenarios:
            con.execute(
                "INSERT INTO scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    scenario_id,
                    "Minnesota winter storm",
                    "historical",
                    "2023-01-01 00:00:00",
                    "2023-01-08 00:00:00",
                    *_FIXTURE_PROVENANCE,
                ],
            )
    finally:
        con.close()


@dataclass(frozen=True)
class _Prediction:
    county_fips: str
    qualified: bool | None = True  # None: heuristic row, no evaluation cited
    scenario_id: str = SCENARIO
    hour: int = 0


def _prediction_database(path: Path, rows: tuple[_Prediction, ...]) -> None:
    """Persist prediction rows on the real DDL; the routes only read them."""
    scenarios = tuple(dict.fromkeys(row.scenario_id for row in rows)) or (SCENARIO,)
    _real_database(path, scenarios=scenarios)
    con = duckdb.connect(str(path))
    try:
        ensure_persistence_schema(con)
        for county in dict.fromkeys(row.county_fips for row in rows):
            con.execute(
                "INSERT INTO counties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [county, f"County {county}", "MN", 1000, b"\x00", *_FIXTURE_PROVENANCE],
            )
        for index, row in enumerate(rows):
            ts = f"2023-01-01 {row.hour:02}:00:00"
            con.execute(
                "INSERT INTO outage_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    row.scenario_id,
                    row.county_fips,
                    ts,
                    0.4,
                    100,
                    "ice",
                    *_FIXTURE_PROVENANCE,
                ],
            )
            if row.qualified is None:
                con.execute(
                    """INSERT INTO prediction_provenance
                       (scenario_id, county_fips, ts, model_kind, rule_id, rule_version,
                        persisted_at)
                       VALUES (?, ?, ?, 'heuristic', 'rule-1', 'r1', ?)""",
                    [row.scenario_id, row.county_fips, ts, "2026-09-05 00:00:00"],
                )
                continue
            evaluation = _evaluation_sha(index)
            con.execute(
                """INSERT INTO evaluation_artifacts VALUES
                   (?, 'ready', ?, ?, ?, 'model-v1', 'holdout-v1', NULL, '{}', '{}',
                    NULL, 'not_applicable', NULL, NULL, ?)""",
                [
                    evaluation,
                    row.qualified,
                    None if row.qualified else "brier_above_acceptance",
                    "a" * 64,
                    "2026-09-05 00:00:00",
                ],
            )
            con.execute(
                """INSERT INTO prediction_provenance
                   (scenario_id, county_fips, ts, model_kind, model_version,
                    artifact_sha256, split_id, feature_set_version, evaluation_sha256,
                    persisted_at)
                   VALUES (?, ?, ?, 'lightgbm', 'model-v1', ?, 'holdout-v1',
                           'features-v1', ?, ?)""",
                [
                    row.scenario_id,
                    row.county_fips,
                    ts,
                    "a" * 64,
                    evaluation,
                    "2026-09-05 00:00:00",
                ],
            )
    finally:
        con.close()


@dataclass(frozen=True)
class _Run:
    """One persisted cascade run and the Minnesota artifact that qualifies it."""

    run_id: str
    created_at: str = "2026-09-05 00:00:00"
    hours: tuple[int, ...] = (0,)
    scenario_id: str = SCENARIO
    provenance: tuple[str, str, str | None, str | None, str] = _ACTIVSG_PROVENANCE
    # None: a bare cascade row with no Minnesota artifact at all.
    model_mode: str | None = "topology"
    availability: str = "available"
    validation_status: str = "validated"
    with_provenance: bool = True
    limitations: str = '["Fixture topology evidence only."]'
    # Two available topology manifests can cite one ``model_run_id``; the suffix
    # builds that tie without a second cascade_runs row.
    artifact_suffix: str = ""
    artifact_id_override: str | None = None
    cascade_rows: bool = True
    # None: a model result exists exactly when the manifest is available.  Set it
    # explicitly to persist a result for a manifest the route must still refuse,
    # so the WHERE clause that refuses it is the only thing standing in the way.
    with_model_result: bool | None = None

    @property
    def artifact_id(self) -> str:
        if self.artifact_id_override is not None:
            return self.artifact_id_override
        return f"mn:model:{self.run_id}{self.artifact_suffix}"


def _cascade_database(path: Path, runs: tuple[_Run, ...]) -> None:
    _real_database(path)
    con = duckdb.connect(str(path))
    try:
        ensure_minnesota_schema(con)
        for run in runs:
            for hour in run.hours if run.cascade_rows else ():
                con.execute(
                    "INSERT INTO cascade_runs VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)",
                    [
                        run.run_id,
                        run.scenario_id,
                        hour,
                        '[{"element_id": "line-7", "kind": "line", "stage": 1, "cause": "weather"}]',
                        12.5 * (hour + 1),
                        '["27000"]',
                        '["cl-1"]',
                        run.provenance[0],
                        run.provenance[1],
                        run.provenance[2],
                        run.provenance[3],
                        run.provenance[4],
                    ],
                )
            if run.model_mode is None:
                continue
            con.execute(
                "INSERT INTO mn_artifact_manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run.artifact_id,
                    "model_result",
                    SCHEMA_VERSION,
                    "mn",
                    run.availability,
                    run.model_mode,
                    "{}",
                    run.created_at,
                    "[]",
                    run.limitations,
                    "[]",
                ],
            )
            if run.with_provenance:
                con.execute(
                    "INSERT INTO mn_artifact_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        run.artifact_id,
                        0,
                        run.provenance[0],
                        run.provenance[1],
                        run.provenance[2] or "v1",
                        run.provenance[3] or "2026-09-05 00:00:00",
                        "test fixture",
                        run.run_id,
                        "b" * 64,
                        False,
                    ],
                )
            if not (
                run.availability == "available"
                if run.with_model_result is None
                else run.with_model_result
            ):
                continue
            topology = run.model_mode == "topology"
            con.execute(
                "INSERT INTO mn_model_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run.artifact_id,
                    "fixture-cascade",
                    "v1",
                    run.run_id,
                    "a" * 64,
                    run.validation_status,
                    "lost_load_mw",
                    1.0,
                    "MW",
                    None if topology else "regional sum",
                    100.0 if topology else None,
                    "pandapower" if topology else None,
                    "fixture-converter" if topology else None,
                ],
            )
    finally:
        con.close()


def _details(response) -> dict[str, str]:  # type: ignore[no-untyped-def]
    body = response.json()
    assert body["status"] in {"unavailable", "error"}
    return body["error"]["details"]


# --- GET /predictions -------------------------------------------------------


def test_qualified_persisted_prediction_is_returned_under_the_status_shape(
    tmp_path: Path,
) -> None:
    """00-overview §4.2 pins ``{status:"available", predictions:[…]}`` here."""
    database = tmp_path / "qualified.duckdb"
    _prediction_database(
        database, (_Prediction("27000", True), _Prediction("27001", False))
    )
    before = _file_sha256(database)

    response = _client(database).get("/predictions", params={"scenario_id": SCENARIO})

    assert response.status_code == 200
    assert _file_sha256(database) == before
    assert response.headers["X-Flux-Api-Version"] == API_VERSION
    assert "X-Flux-Artifact" not in response.headers
    body = response.json()
    assert body["status"] == "available"
    assert body["predictions"] == [
        {
            "scenario_id": SCENARIO,
            "county_fips": "27000",
            "ts": "2023-01-01T00:00:00Z",
            "p_out": 0.4,
            "customers_at_risk": 100,
            "driver": "ice",
            "model_kind": "lightgbm",
            "model_version": "model-v1",
            "artifact_sha256": "a" * 64,
            "split_id": "holdout-v1",
            "feature_set_version": "features-v1",
            "evaluation_sha256": _evaluation_sha(0),
            "rule_id": None,
            "rule_version": None,
            "persisted_at": "2026-09-05T00:00:00Z",
            "evaluation_status": "ready",
            "qualified": True,
            "qualification_reason": None,
        }
    ]


def test_unqualified_prediction_is_not_returned_as_success(tmp_path: Path) -> None:
    database = tmp_path / "unqualified.duckdb"
    _prediction_database(database, (_Prediction("27000", False),))

    response = _client(database).get("/predictions")

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "outage_predictions",
        "reason": "no_qualified_prediction",
    }


def test_qualified_row_behind_unqualified_rows_beyond_limit_is_returned(
    tmp_path: Path,
) -> None:
    """The qualified predicate runs in SQL before LIMIT, not on the limited page."""
    database = tmp_path / "buried.duckdb"
    unqualified = tuple(_Prediction(f"270{i:02}", False) for i in range(3))
    _prediction_database(database, (*unqualified, _Prediction("27999", True)))

    response = _client(database).get("/predictions", params={"limit": 2})

    assert response.status_code == 200
    assert [r["county_fips"] for r in response.json()["predictions"]] == ["27999"]


def test_heuristic_rows_without_evaluation_are_not_qualified(tmp_path: Path) -> None:
    """A NULL ``qualified`` (no evaluation cited) is not treated as qualified."""
    database = tmp_path / "heuristic.duckdb"
    _prediction_database(database, (_Prediction("27000", None),))

    response = _client(database).get("/predictions", params={"model_kind": "heuristic"})

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "outage_predictions",
        "reason": "no_qualified_prediction",
    }


def test_limit_bounds_the_returned_rows(tmp_path: Path) -> None:
    database = tmp_path / "limit.duckdb"
    _prediction_database(
        database, tuple(_Prediction(f"270{i:02}", True) for i in range(3))
    )

    response = _client(database).get("/predictions", params={"limit": 2})

    assert response.status_code == 200
    assert [r["county_fips"] for r in response.json()["predictions"]] == [
        "27000",
        "27001",
    ]


def test_county_fips_filter_is_wired_through_to_the_query(tmp_path: Path) -> None:
    """Passing ``county_fips`` must change the result set, not just validate."""
    database = tmp_path / "counties.duckdb"
    _prediction_database(
        database, (_Prediction("27000", True), _Prediction("27001", True))
    )
    client = _client(database)

    filtered = client.get("/predictions", params={"county_fips": "27001"})
    unfiltered = client.get("/predictions")

    assert filtered.status_code == 200
    assert [r["county_fips"] for r in filtered.json()["predictions"]] == ["27001"]
    assert [r["county_fips"] for r in unfiltered.json()["predictions"]] == [
        "27000",
        "27001",
    ]


def test_model_kind_filter_is_wired_through_to_the_query(tmp_path: Path) -> None:
    """``model_kind=heuristic`` excludes the qualified lightgbm row; None does not."""
    database = tmp_path / "kinds.duckdb"
    _prediction_database(
        database, (_Prediction("27000", True), _Prediction("27001", None))
    )
    client = _client(database)

    heuristic = client.get("/predictions", params={"model_kind": "heuristic"})
    lightgbm = client.get("/predictions", params={"model_kind": "lightgbm"})
    unfiltered = client.get("/predictions")

    assert heuristic.status_code == 503
    assert _details(heuristic)["reason"] == "no_qualified_prediction"
    assert lightgbm.status_code == 200
    assert [r["county_fips"] for r in lightgbm.json()["predictions"]] == ["27000"]
    assert unfiltered.status_code == 200
    assert [r["county_fips"] for r in unfiltered.json()["predictions"]] == ["27000"]


def test_scenario_filter_selects_only_that_scenario(tmp_path: Path) -> None:
    database = tmp_path / "scenarios.duckdb"
    _prediction_database(
        database,
        (
            _Prediction("27000", True, scenario_id=SCENARIO),
            _Prediction("27001", True, scenario_id=OTHER_SCENARIO),
        ),
    )

    response = _client(database).get(
        "/predictions", params={"scenario_id": OTHER_SCENARIO}
    )

    assert response.status_code == 200
    assert [
        (r["scenario_id"], r["county_fips"]) for r in response.json()["predictions"]
    ] == [(OTHER_SCENARIO, "27001")]


@pytest.mark.parametrize(
    ("path", "params", "field"),
    [
        ("/predictions", {"model_kind": "bogus"}, "query.model_kind"),
        ("/predictions", {"scenario_id": "a" * 65}, "query.scenario_id"),
        ("/predictions", {"scenario_id": "../x;DROP TABLE"}, "query.scenario_id"),
        ("/predictions", {"scenario_id": "URI_2021"}, "query.scenario_id"),
        ("/predictions", {"county_fips": "zz"}, "query.county_fips"),
        ("/predictions", {"limit": 0}, "query.limit"),
        ("/predictions", {"limit": 1001}, "query.limit"),
        ("/cascade", {"scenario_id": "a" * 65}, "query.scenario_id"),
        ("/cascade", {"scenario_id": "../x"}, "query.scenario_id"),
        ("/cascade", {"scenario_id": SCENARIO, "run_id": "run id"}, "query.run_id"),
        ("/cascade", {}, "query.scenario_id"),
    ],
)
def test_malformed_parameters_are_the_shared_validation_envelope(
    tmp_path: Path, path: str, params: dict[str, object], field: str
) -> None:
    # No database exists: validation must reject the request before opening it.
    database = tmp_path / "missing.duckdb"
    response = _client(database).get(path, params=params)

    assert response.status_code == 422
    assert not database.exists()
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "invalid_input"
    assert body["error"]["details"] == {"field": field}


def test_prediction_missing_database_is_unavailable(tmp_path: Path) -> None:
    response = _client(tmp_path / "missing.duckdb").get("/predictions")

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "outage_predictions",
        "reason": "database_missing",
    }


def test_prediction_companion_tables_absent_is_named_missing(tmp_path: Path) -> None:
    """A real grid.duckdb whose persistence tables were never created."""
    database = tmp_path / "grid.duckdb"
    _real_database(database)

    response = _client(database).get("/predictions")

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "prediction_provenance",
        "reason": "missing",
    }


def test_prediction_schema_drift_is_unavailable(tmp_path: Path) -> None:
    database = tmp_path / "drift.duckdb"
    con = duckdb.connect(str(database))
    con.execute("CREATE TABLE outage_predictions (scenario_id TEXT)")
    con.execute("CREATE TABLE prediction_provenance (scenario_id TEXT)")
    con.execute("CREATE TABLE evaluation_artifacts (evaluation_sha256 TEXT)")
    con.close()

    response = _client(database).get("/predictions")

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "outage_predictions",
        "reason": "schema_mismatch",
    }


def test_persistence_rejection_is_a_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "qualified.duckdb"
    _prediction_database(database, (_Prediction("27000", True),))

    def _reject(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise PersistenceError("rejected by the persistence layer")

    monkeypatch.setattr(predictions_module, "query_predictions", _reject)
    response = _client(database).get("/predictions")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"
    assert _details(response) == {"reason": "invalid_request"}


def test_prediction_read_failure_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "qualified.duckdb"
    _prediction_database(database, (_Prediction("27000", True),))

    def _fail(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise duckdb.Error("storage failure")

    monkeypatch.setattr(predictions_module, "query_predictions", _fail)
    response = _client(database).get("/predictions")

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "outage_predictions",
        "reason": "query_failed",
    }


# --- GET /cascade -------------------------------------------------------------


def _hour(hour: int) -> dict[str, object]:
    return {
        "hour": hour,
        "tripped_element_ids": [
            {"element_id": "line-7", "kind": "line", "stage": 1, "cause": "weather"}
        ],
        "lost_load_mw": 12.5 * (hour + 1),
        "counties_dark": ["27000"],
        "critical_loads_lost": ["cl-1"],
    }


def test_persisted_cascade_is_returned_with_its_status_and_artifact_header(
    tmp_path: Path,
) -> None:
    """The 00-overview §4.2 status shape, plus #158's ``X-Flux-Artifact``."""
    database = tmp_path / "cascade.duckdb"
    run = _Run("mn_winter_2023_snow-s0-0badf00d", hours=(1, 0))
    _cascade_database(database, (run,))
    before = _file_sha256(database)

    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 200
    assert _file_sha256(database) == before
    body = response.json()
    assert body == {
        "status": "available",
        "run_id": "mn_winter_2023_snow-s0-0badf00d",
        "scenario_id": SCENARIO,
        "artifact_id": "mn:model:mn_winter_2023_snow-s0-0badf00d",
        "model_mode": "topology",
        "geography_id": "mn",
        "hours": [_hour(0), _hour(1)],
        "provenance": [
            {
                "source_name": "twin.cascade",
                "source_ref": "data/raw/activsg2000/scenarios_ACTIVSg2000.m",
                "source_version": "2018",
                "retrieved_at": "2026-09-05T12:00:00Z",
                "license_or_terms": "test fixture",
                "source_record_id": "mn_winter_2023_snow-s0-0badf00d",
                "content_sha256": "b" * 64,
                "is_derived": False,
            }
        ],
        "limitations": ["Fixture topology evidence only."],
        "source_kind": "simulated",
        "topology": "synthetic (ACTIVSg2000)",
        "attributes": predictions_module.CASCADE_ATTRIBUTES,
    }
    assert body["attributes"]["lost_load_mw"]["unit"] == "MW"
    assert response.headers["X-Flux-Artifact"] == body["artifact_id"]
    assert response.headers["X-Flux-Api-Version"] == API_VERSION


def test_cascade_labels_come_from_the_persisted_provenance(tmp_path: Path) -> None:
    """A fixture-sourced run is labelled a fixture; an unidentifiable one fails closed."""
    fixture = tmp_path / "fixture-run.duckdb"
    _cascade_database(
        fixture,
        (_Run("mn_winter_2023_snow-s0-f1f1f1f1", provenance=_FIXTURE_PROVENANCE),),
    )
    unlabelled = tmp_path / "unlabelled-run.duckdb"
    _cascade_database(
        unlabelled,
        (_Run("mn_winter_2023_snow-s0-0000beef", provenance=_UNLABELLED_PROVENANCE),),
    )

    labelled = _client(fixture).get("/cascade", params={"scenario_id": SCENARIO})
    refused = _client(unlabelled).get("/cascade", params={"scenario_id": SCENARIO})

    assert labelled.status_code == 200
    assert labelled.json()["source_kind"] == "fixture"
    assert labelled.json()["topology"] is None
    assert refused.status_code == 503
    assert _details(refused) == {
        "artifact": "cascade_runs",
        "reason": "topology_label_unavailable",
        "run_id": "mn_winter_2023_snow-s0-0000beef",
    }


def test_latest_cascade_run_is_by_artifact_time_not_run_id_order(
    tmp_path: Path,
) -> None:
    """Lexically-later run ids must not win over a more recently created artifact."""
    database = tmp_path / "runs.duckdb"
    _cascade_database(
        database,
        (
            _Run("mn_winter_2023_snow-s0-ffffffff", "2026-09-01 00:00:00"),
            _Run("mn_winter_2023_snow-s0-00000000", "2026-09-05 00:00:00"),
            _Run("mn_winter_2023_snow-s0-aaaaaaaa", "2026-09-03 00:00:00"),
        ),
    )

    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 200
    assert response.json()["run_id"] == "mn_winter_2023_snow-s0-00000000"


def test_latest_cascade_run_is_a_total_order_when_created_at_ties(
    tmp_path: Path,
) -> None:
    """Eight available manifests, one ``model_run_id``, one ``created_at``.

    ``created_at`` and ``run_id`` are tied across all eight, so only the
    ``artifact_id`` tie-break decides which one ``LIMIT 1`` may keep, and the
    lexically greatest (``…:h``) must be served.  The two databases differ only
    in the order the tied manifests were inserted, and each is asked five times:
    a total order over the selected columns answers ``…:h`` all ten times, while
    a partial order is free to follow whatever the scan reaches first (without
    ``, m.artifact_id DESC`` DuckDB serves ``…:b`` here, from both orders).
    """
    run_id = "mn_winter_2023_snow-s0-7ie7ie00"
    tied = "2026-09-05 00:00:00"
    suffixes = tuple(f":{letter}" for letter in "abcdefgh")

    def _tied(path: Path, order: tuple[str, ...]) -> None:
        _cascade_database(
            path,
            tuple(
                _Run(
                    run_id,
                    tied,
                    artifact_suffix=suffix,
                    # One shared set of cascade_runs rows; the manifests are what
                    # tie.
                    cascade_rows=index == 0,
                )
                for index, suffix in enumerate(order)
            ),
        )

    ascending = tmp_path / "tied-ascending.duckdb"
    _tied(ascending, suffixes)
    descending = tmp_path / "tied-descending.duckdb"
    _tied(descending, tuple(reversed(suffixes)))

    served = [
        _client(database).get("/cascade", params={"scenario_id": SCENARIO})
        for database in (ascending, descending)
        for _ in range(5)
    ]

    assert [r.status_code for r in served] == [200] * 10
    assert {r.json()["artifact_id"] for r in served} == {f"mn:model:{run_id}:h"}
    assert {r.headers["X-Flux-Artifact"] for r in served} == {f"mn:model:{run_id}:h"}


def test_cascade_run_id_selects_that_run_or_is_not_found(tmp_path: Path) -> None:
    database = tmp_path / "runs.duckdb"
    _cascade_database(
        database,
        (
            _Run("mn_winter_2023_snow-s0-ffffffff", "2026-09-01 00:00:00"),
            _Run("mn_winter_2023_snow-s0-00000000", "2026-09-05 00:00:00"),
        ),
    )
    client = _client(database)

    chosen = client.get(
        "/cascade",
        params={"scenario_id": SCENARIO, "run_id": "mn_winter_2023_snow-s0-ffffffff"},
    )
    unknown = client.get(
        "/cascade",
        params={"scenario_id": SCENARIO, "run_id": "mn_winter_2023_snow-s1-0"},
    )

    assert chosen.status_code == 200
    assert chosen.json()["run_id"] == "mn_winter_2023_snow-s0-ffffffff"
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "not_found"
    assert _details(unknown) == {
        "scenario_id": SCENARIO,
        "run_id": "mn_winter_2023_snow-s1-0",
    }


def test_bare_cascade_row_is_not_a_qualified_topology_artifact(tmp_path: Path) -> None:
    """A cascade row with no Minnesota model result behind it is not served."""
    database = tmp_path / "bare-cascade.duckdb"
    _cascade_database(
        database, (_Run("mn_winter_2023_snow-s0-bare0000", model_mode=None),)
    )

    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "cascade_runs",
        "reason": "topology_cascade_unsupported_or_absent",
    }


def test_aggregate_model_cannot_be_relabelled_as_a_cascade(tmp_path: Path) -> None:
    database = tmp_path / "aggregate-cascade.duckdb"
    run = _Run("mn_winter_2023_snow-s0-a66re6a7", model_mode="aggregate")
    _cascade_database(database, (run,))

    latest = _client(database).get("/cascade", params={"scenario_id": SCENARIO})
    named = _client(database).get(
        "/cascade", params={"scenario_id": SCENARIO, "run_id": run.run_id}
    )

    assert latest.status_code == 503
    assert _details(latest) == {
        "artifact": "cascade_runs",
        "reason": "topology_cascade_unsupported_or_absent",
    }
    # The run exists but is unqualified: named, not 404.
    assert named.status_code == 503
    assert _details(named) == {
        "artifact": "cascade_runs",
        "reason": "topology_cascade_unsupported_or_absent",
        "run_id": run.run_id,
    }


def test_unavailable_manifest_is_not_a_qualified_cascade(tmp_path: Path) -> None:
    """The manifest is otherwise complete: only ``availability`` refuses it.

    ``with_model_result=True`` persists the validated ``mn_model_results`` row that
    an unavailable manifest would not normally get, so the join and the provenance
    EXISTS both succeed and ``m.availability = 'available'`` is the single clause
    standing between this fixture and a 200.
    """
    database = tmp_path / "unavailable-manifest.duckdb"
    _cascade_database(
        database,
        (
            _Run(
                "mn_winter_2023_snow-s0-0ff11ne0",
                availability="unavailable",
                with_model_result=True,
            ),
        ),
    )

    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 503
    assert "X-Flux-Artifact" not in response.headers
    assert _details(response)["reason"] == "topology_cascade_unsupported_or_absent"


def test_manifest_without_provenance_is_not_a_qualified_cascade(
    tmp_path: Path,
) -> None:
    """An available, validated topology manifest with no provenance row is refused."""
    database = tmp_path / "no-provenance.duckdb"
    _cascade_database(
        database,
        (_Run("mn_winter_2023_snow-s0-c0ffee00", with_provenance=False),),
    )

    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 503
    assert "X-Flux-Artifact" not in response.headers
    assert _details(response)["reason"] == "topology_cascade_unsupported_or_absent"


def test_cascade_rejects_an_artifact_id_unsafe_for_an_http_header(
    tmp_path: Path,
) -> None:
    """#158: a control-character artifact id fails closed, it is never emitted."""
    database = tmp_path / "unsafe-artifact.duckdb"
    run = _Run(
        "mn_winter_2023_snow-s0-badhdr00",
        artifact_id_override="mn:storm\r\nX-Injected: yes",
    )
    _cascade_database(database, (run,))

    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 503
    assert "X-Flux-Artifact" not in response.headers
    assert "X-Injected" not in response.headers
    assert _details(response) == {
        "artifact": "cascade_runs",
        "reason": "invalid_topology_artifact",
        "run_id": run.run_id,
    }


def test_cascade_artifact_with_empty_limitations_is_invalid(tmp_path: Path) -> None:
    database = tmp_path / "no-limitations.duckdb"
    run = _Run("mn_winter_2023_snow-s0-11111111", limitations="[]")
    _cascade_database(database, (run,))

    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "cascade_runs",
        "reason": "invalid_topology_artifact",
        "run_id": run.run_id,
    }


def test_cascade_table_absent_from_real_database_is_unavailable(tmp_path: Path) -> None:
    """A 2.1.0 database file that exists but has no ``cascade_runs`` is a 503, not a 500."""
    database = tmp_path / "grid.duckdb"
    _real_database(database)
    con = duckdb.connect(str(database))
    con.execute("DROP TABLE cascade_runs")
    con.close()

    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 503
    assert _details(response) == {"artifact": "cascade_runs", "reason": "missing"}


def test_cascade_without_minnesota_metadata_tables_is_named_missing(
    tmp_path: Path,
) -> None:
    """A real grid.duckdb whose ``mn_*`` namespace was never created."""
    database = tmp_path / "grid.duckdb"
    _real_database(database)

    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "mn_artifact_manifests",
        "reason": "missing",
    }


def test_cascade_without_a_run_for_the_scenario_is_unavailable(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _cascade_database(database, ())

    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "cascade_runs",
        "reason": "topology_cascade_unsupported_or_absent",
    }


def test_cascade_schema_drift_is_unavailable(tmp_path: Path) -> None:
    database = tmp_path / "drift.duckdb"
    _cascade_database(database, (_Run("mn_winter_2023_snow-s0-0badf00d"),))
    con = duckdb.connect(str(database))
    con.execute("DROP TABLE cascade_runs")
    con.execute(
        "CREATE TABLE cascade_runs (run_id TEXT, scenario_id TEXT, hour INTEGER)"
    )
    con.execute(
        "INSERT INTO cascade_runs VALUES ('mn_winter_2023_snow-s0-0badf00d', ?, 0)",
        [SCENARIO],
    )
    con.close()

    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "cascade_runs",
        "reason": "schema_mismatch",
    }


def test_cascade_row_without_a_lost_load_number_is_unavailable(tmp_path: Path) -> None:
    """A row the contract forbids (no ``lost_load_mw``) is named, never invented."""
    database = tmp_path / "nullable.duckdb"
    run = _Run("mn_winter_2023_snow-s0-0badf00d")
    _cascade_database(database, (run,))
    con = duckdb.connect(str(database))
    # Same columns as the 2.1.0 DDL, without the NOT NULL the contract requires.
    con.execute("CREATE TABLE drifted AS SELECT * FROM cascade_runs")
    con.execute("DROP TABLE cascade_runs")
    con.execute("ALTER TABLE drifted RENAME TO cascade_runs")
    con.execute(
        "UPDATE cascade_runs SET lost_load_mw = NULL WHERE run_id = ?", [run.run_id]
    )
    con.close()

    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "cascade_runs",
        "reason": "schema_mismatch",
        "run_id": run.run_id,
    }


def test_cascade_read_failure_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "cascade.duckdb"
    _cascade_database(database, (_Run("mn_winter_2023_snow-s0-0badf00d"),))
    real_connect = duckdb.connect

    class _FailingConnection:
        def __init__(self, inner: duckdb.DuckDBPyConnection) -> None:
            self._inner = inner

        def execute(self, sql: str, params: object = None) -> object:
            if "FROM cascade_runs" in sql:
                raise duckdb.Error("storage failure")
            return self._inner.execute(sql, params)

        def close(self) -> None:
            self._inner.close()

    monkeypatch.setattr(
        duckdb, "connect", lambda *a, **k: _FailingConnection(real_connect(*a, **k))
    )
    response = _client(database).get("/cascade", params={"scenario_id": SCENARIO})

    assert response.status_code == 503
    assert _details(response) == {"artifact": "cascade_runs", "reason": "query_failed"}


def test_missing_cascade_database_is_unavailable(tmp_path: Path) -> None:
    response = _client(tmp_path / "missing.duckdb").get(
        "/cascade", params={"scenario_id": SCENARIO}
    )

    assert response.status_code == 503
    assert _details(response) == {
        "artifact": "cascade_runs",
        "reason": "database_missing",
    }

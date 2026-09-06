"""No-write checks for FastAPI startup and every registered route.

The fixture is the shared artifact contract from
:mod:`copilot._artifact_fixtures` (the real ``pipelines.db`` 2.1.0 DDL plus the
persistence and Minnesota namespaces) with rows for every route, so each route
runs its *read path* rather than short-circuiting on a missing-table guard.
That is what makes the no-write property meaningful: a write placed anywhere in
a route's query path is executed, and therefore observable.

Two independent observations carry the property:

* the expected status is pinned **per route**, so a route that degrades into a
  permanent ``503`` fails rather than quietly counting as coverage; and
* the whole working directory is snapshotted by path *and* SHA-256 before and
  after startup and after every request, so a new or modified file anywhere
  under it -- not only next to the database -- is caught.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from copilot._artifact_fixtures import (
    OTHER_SCENARIO,
    SCENARIO,
    Prediction,
    Run,
    cascade_database,
    file_sha256,
    prediction_database,
    registered_routes,
)
from copilot.app import create_app
from copilot.config import Settings
from copilot.persisted_fixtures import (
    DEFAULT_SCENARIO,
    SHA256,
    insert,
    persisted_read_route_database,
    site_intervention_id,
)

Request = Callable[[TestClient], object]

#: The geography ``persisted_read_route_database`` files its rows under.
REGION = "mn"
SITE_ID = 1
CRITICAL_ARTIFACT = "mn:score:critical-line-10"

#: Every registered route, the request that drives its read path against the
#: fixture below, and the status that fixture produces.  A 503 here would mean
#: the route never reached its data.
READ_REQUESTS: dict[tuple[str, str], tuple[Request, int]] = {
    ("GET", "/health"): (lambda client: client.get("/health"), 200),
    ("GET", "/layers/{layer_name}"): (
        lambda client: client.get("/layers/buses"),
        200,
    ),
    ("POST", "/site-score"): (
        lambda client: client.post(
            "/site-score",
            json={
                "site_id": str(SITE_ID),
                "unit_mw": 300,
                "scenario_id": DEFAULT_SCENARIO,
            },
        ),
        200,
    ),
    ("POST", "/compare"): (
        lambda client: client.post(
            "/compare",
            json={
                "scenario_id": DEFAULT_SCENARIO,
                "intervention_ids": [site_intervention_id(SITE_ID, 300)],
            },
        ),
        200,
    ),
    ("GET", "/lines/top"): (
        lambda client: client.get("/lines/top", params={"region": REGION}),
        200,
    ),
    ("GET", "/elements/critical"): (
        lambda client: client.get("/elements/critical", params={"region": REGION}),
        200,
    ),
    ("GET", "/scenarios"): (lambda client: client.get("/scenarios"), 200),
    ("GET", "/scenarios/{scenario_id}"): (
        lambda client: client.get(f"/scenarios/{SCENARIO}"),
        200,
    ),
    ("GET", "/predictions"): (
        lambda client: client.get(
            "/predictions", params={"scenario_id": OTHER_SCENARIO}
        ),
        200,
    ),
    ("GET", "/cascade"): (
        lambda client: client.get("/cascade", params={"scenario_id": SCENARIO}),
        200,
    ),
    # ``/ask`` streams; with no provider configured the fixture produces a 200
    # SSE stream whose terminal frame is the documented unavailable error.
    ("POST", "/ask"): (
        lambda client: client.post(
            "/ask",
            json={"attempt_id": "read-only-attempt", "question": "What is available?"},
        ),
        200,
    ),
}


def _add_critical_element(connection: duckdb.DuckDBPyConnection) -> None:
    """The one persisted artifact ``persisted_read_route_database`` omits."""
    identity = {
        "source_identity": {
            "family": "critical_elements",
            "region": REGION,
            "scenario_id": DEFAULT_SCENARIO,
            "element_id": "line-10",
        }
    }
    insert(
        connection,
        "mn_artifact_manifests",
        {
            "artifact_id": CRITICAL_ARTIFACT,
            "artifact_kind": "score",
            "contract_version": "1.0.0",
            "geography_id": REGION,
            "availability": "available",
            "model_mode": "topology",
            "identity_json": json.dumps(identity),
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "assumptions_json": json.dumps([]),
            "limitations_json": json.dumps(["Fixture topology evidence only."]),
            "input_artifact_ids_json": json.dumps([]),
        },
    )
    insert(
        connection,
        "mn_artifact_provenance",
        {
            "artifact_id": CRITICAL_ARTIFACT,
            "provenance_ordinal": 0,
            "source_name": "fixture:critical-elements",
            "source_ref": "fixture://critical-elements",
            "source_version": "v1",
            "retrieved_at": datetime(2026, 1, 1, tzinfo=UTC),
            "license_or_terms": "test fixture",
            "source_record_id": CRITICAL_ARTIFACT,
            "content_sha256": SHA256,
            "is_derived": False,
        },
    )
    insert(
        connection,
        "mn_score_results",
        {
            "artifact_id": CRITICAL_ARTIFACT,
            "metric": "critical_element",
            "score_value": 12.5,
            "score_unit": "MW",
            "score_components_json": json.dumps(
                {
                    "scenario_id": DEFAULT_SCENARIO,
                    "element_id": "line-10",
                    "kind": "line",
                    "runs": 1,
                    "critical_loads_lost": ["cl-1"],
                }
            ),
            "regulatory_label": "hypothetical",
        },
    )


def _populate(database: Path) -> None:
    """Build a database every route can read, on the shared artifact contract.

    ``persisted_read_route_database`` carries the grid, site and line-upgrade
    halves; the prediction and cascade builders add their own scenarios (each a
    distinct row, so they cannot collide on the ``scenarios`` primary key).
    Every table is created by the real DDL, so a contract change breaks the
    fixture rather than quietly turning these routes back into 503s.
    """
    persisted_read_route_database(database, site_id=SITE_ID, region=REGION)
    prediction_database(database, (Prediction("27000", scenario_id=OTHER_SCENARIO),))
    cascade_database(database, (Run("run-1"),))
    connection = duckdb.connect(str(database))
    try:
        _add_critical_element(connection)
    finally:
        connection.close()


def _tree(root: Path) -> tuple[tuple[str, str], ...]:
    """Every file under ``root``, by relative path and content hash."""
    return tuple(
        (str(candidate.relative_to(root)), file_sha256(candidate))
        for candidate in sorted(root.rglob("*"))
        if candidate.is_file()
    )


def test_startup_and_every_registered_route_leave_the_working_tree_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    database = Path("fixture.duckdb")
    _populate(database)
    before = _tree(tmp_path)
    assert before, "the fixture database itself must be in the snapshot"

    app = create_app(Settings(_env_file=None, duckdb_path=database))
    assert _tree(tmp_path) == before, "startup wrote to the working tree"
    assert set(READ_REQUESTS) == registered_routes()

    client = TestClient(app)
    for route, (request, expected_status) in READ_REQUESTS.items():
        response = request(client)
        assert response.status_code == expected_status, (route, response.text[:400])
        assert _tree(tmp_path) == before, route


def test_the_fixture_drives_every_route_past_its_unavailable_guard(
    tmp_path: Path,
) -> None:
    """No route may answer with the unavailable envelope on this fixture.

    Without this the suite above could pass while every route 503s before
    touching the database, which is the state in which "reads do not write" is
    trivially true and proves nothing.
    """
    database = tmp_path / "fixture.duckdb"
    _populate(database)
    client = TestClient(create_app(Settings(_env_file=None, duckdb_path=database)))

    for route, (request, _) in READ_REQUESTS.items():
        response = request(client)
        if route == ("POST", "/ask"):
            # The stream starts, then reports the unconfigured local backend.
            assert "event: lifecycle" in response.text, route
            continue
        body = response.json()
        assert not (isinstance(body, dict) and body.get("status") == "unavailable"), (
            route,
            response.text[:400],
        )

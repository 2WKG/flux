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

from collections.abc import Callable
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from copilot._artifact_fixtures import (
    FIXTURE_PROVENANCE,
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

Request = Callable[[TestClient], object]

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
            json={"site_id": "1", "unit_mw": 300, "scenario_id": SCENARIO},
        ),
        200,
    ),
    ("POST", "/compare"): (
        lambda client: client.post(
            "/compare",
            json={"scenario_id": SCENARIO, "intervention_ids": ["site:1"]},
        ),
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


def _populate(database: Path) -> None:
    """Build a database every route can read, on the shared artifact contract.

    ``prediction_database`` and ``cascade_database`` each seed their own
    scenario row, so they are given different scenarios rather than colliding on
    the ``scenarios`` primary key.  The bus, site-candidate and site-score rows
    are inserted into the DDL those builders created -- no schema is re-declared
    here, so the fixture cannot drift from the columns the routes read.
    """
    prediction_database(database, (Prediction("27000", scenario_id=OTHER_SCENARIO),))
    cascade_database(database, (Run("run-1"),))
    connection = duckdb.connect(str(database))
    try:
        connection.execute(
            "INSERT INTO buses (bus_id, name, base_kv, lon, lat, county_fips, ba_code,"
            " coord_source, zone, area, source_name, source_ref, source_version,"
            " source_retrieved_at, fixture_batch_id)"
            " VALUES (1, 'Fixture Bus', 115.0, -93.1, 44.9, '27000', 'MISO',"
            " 'fixture:hand-placed', 1, 1, ?, ?, ?, ?, ?)",
            list(FIXTURE_PROVENANCE),
        )
        connection.execute(
            "INSERT INTO site_candidates (site_id, name, kind, lon, lat, county_fips,"
            " bus_id, capacity_slot_mw, source_site_id, source_name, source_ref,"
            " source_version, source_retrieved_at, fixture_batch_id)"
            " VALUES (1, 'Fixture Site', 'coal_retired', -93.1, 44.9, '27000', 1,"
            " 300.0, 'fixture-site', ?, ?, ?, ?, ?)",
            list(FIXTURE_PROVENANCE),
        )
        connection.execute(
            "INSERT INTO site_scores (site_id, scenario_id, unit_mw, safety_score,"
            " safety_flags_json, grid_value_score, lol_reduction_mwh,"
            " congestion_relief_pct, blackstart_reach_mw, source_name, source_ref,"
            " source_version, source_retrieved_at, fixture_batch_id)"
            " VALUES (1, ?, 300.0, 10.0, '[]', 2.0, 3.0, 4.0, 5.0, ?, ?, ?, ?, ?)",
            [SCENARIO, *FIXTURE_PROVENANCE],
        )
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

"""No-write checks for FastAPI startup and every registered route."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings

Request = Callable[[TestClient], object]


READ_REQUESTS: dict[tuple[str, str], Request] = {
    ("GET", "/health"): lambda client: client.get("/health"),
    ("GET", "/layers/{layer_name}"): lambda client: client.get("/layers/buses"),
    ("POST", "/site-score"): lambda client: client.post(
        "/site-score",
        json={"site_id": "fixture-site", "unit_mw": 300, "scenario_id": "fixture"},
    ),
    ("POST", "/compare"): lambda client: client.post(
        "/compare",
        json={"scenario_id": "fixture", "intervention_ids": ["site:fixture-site"]},
    ),
    ("GET", "/scenarios"): lambda client: client.get("/scenarios"),
    ("GET", "/scenarios/{scenario_id}"): lambda client: client.get(
        "/scenarios/fixture"
    ),
    ("GET", "/predictions"): lambda client: client.get("/predictions"),
    ("GET", "/cascade"): lambda client: client.get(
        "/cascade", params={"scenario_id": "fixture"}
    ),
    ("POST", "/ask"): lambda client: client.post(
        "/ask",
        json={"attempt_id": "read-only-attempt", "question": "What is available?"},
    ),
}


def _files(path: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (candidate.name, sha256(candidate.read_bytes()).hexdigest())
        for candidate in sorted(path.parent.glob(f"{path.name}*"))
    )


def test_startup_and_every_registered_route_leave_fixture_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    database = Path("fixture.duckdb")
    connection = duckdb.connect(str(database))
    connection.execute("CREATE TABLE fixture_marker (id INTEGER)")
    connection.close()
    before = _files(database)

    app = create_app(Settings(_env_file=None, duckdb_path=database))
    assert _files(database) == before
    registered = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    assert set(READ_REQUESTS) == registered

    client = TestClient(app)
    for route, request in READ_REQUESTS.items():
        response = request(client)
        assert response.status_code in {200, 503}, route
        assert _files(database) == before, route

"""HTTP checks for the persisted, paged line-upgrade read.

Fixtures are built through `pipelines.db.connect` (real `ensure_schema` DDL,
with its primary keys, foreign keys, CHECKs and NOT NULLs) so a column rename or
constraint change in `pipelines/db.py` fails this suite instead of leaving a
hand-typed shadow schema green, exactly as `copilot/test_tools_lines.py` does.
"""

from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.persisted_fixtures import persisted_lines_database
from copilot.tools.schemas import TOP_LINES_MAX_LIMIT


def _client(path: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=path)))


def _database(path: Path) -> None:
    persisted_lines_database(path)


def test_top_lines_reads_a_deterministic_persisted_page(tmp_path: Path) -> None:
    database = tmp_path / "lines.duckdb"
    _database(database)

    response = _client(database).get(
        "/lines/top", params={"region": "MN", "limit": 1, "offset": 1}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["scenario_id"] == "mn_fixture"
    assert [line["line_id"] for line in body["lines"]] == ["10"]
    assert body["provenance"][0]["source_kind"] == "fixture"


def test_top_lines_reports_unavailable_artifact_states(tmp_path: Path) -> None:
    missing = _client(tmp_path / "missing.duckdb").get(
        "/lines/top", params={"region": "MN"}
    )
    assert missing.status_code == 503
    assert missing.json()["error"]["details"]["reason"] == "artifact_unavailable"

    database = tmp_path / "empty.duckdb"
    _database(database)
    with duckdb.connect(str(database)) as con:
        con.execute("DELETE FROM line_upgrade_scores")
    empty = _client(database).get("/lines/top", params={"region": "MN"})
    assert empty.status_code == 503
    assert empty.json()["error"]["details"]["reason"] == "artifact_unavailable"


def test_top_lines_rejects_invalid_page_bounds(tmp_path: Path) -> None:
    database = tmp_path / "lines.duckdb"
    _database(database)
    response = _client(database).get(
        "/lines/top", params={"region": "MN", "limit": 101}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"

    # The HTTP page may not exceed the model-facing tool bound for the same read.
    over_tool_bound = _client(database).get(
        "/lines/top", params={"region": "MN", "limit": TOP_LINES_MAX_LIMIT + 1}
    )
    assert over_tool_bound.status_code == 422
    assert over_tool_bound.json()["error"]["code"] == "invalid_input"
    assert (
        _client(database)
        .get("/lines/top", params={"region": "MN", "limit": TOP_LINES_MAX_LIMIT})
        .status_code
        == 200
    )

from __future__ import annotations

import duckdb
import pytest

from pipelines.db import (
    CONTRACT_TABLES,
    PROVENANCE_COLUMN_NAMES,
    SCHEMA_VERSION,
    ensure_schema,
)


def test_schema_is_versioned_and_idempotent() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    ensure_schema(con)

    assert con.execute(
        "SELECT value FROM schema_meta WHERE key = 'contract_version'"
    ).fetchone() == (SCHEMA_VERSION,)
    assert set(CONTRACT_TABLES) <= {
        row[0] for row in con.execute("SHOW TABLES").fetchall()
    }
    columns = {
        row[1] for row in con.execute("PRAGMA table_info('corpus_chunks')").fetchall()
    }
    assert set(PROVENANCE_COLUMN_NAMES) <= columns
    assert (
        con.execute("PRAGMA table_info('corpus_chunks')").fetchall()[6][2]
        == "FLOAT[1024]"
    )


@pytest.mark.parametrize("table", ["line_upgrade_scores", "line_upgrade_detail"])
def test_line_upgrade_artifacts_persist_scenario_identity_and_contract_provenance(
    table: str,
) -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)

    columns = {
        row[1]: row for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()
    }
    assert columns["line_id"][5] is True
    assert columns["scenario_id"][5] is True
    assert columns["scenario_id"][3] is True
    assert {
        "ranking_version",
        "contract_version",
        "computed_at",
        "simulation_run_id",
        "grid_input_sha256",
        "weather_input_sha256",
        "cost_params_sha256",
    } <= columns.keys()
    assert columns["simulation_run_id"][3] is False


def test_line_upgrade_score_index_supports_scenario_ranking() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    index_names = {
        row[0]
        for row in con.execute("SELECT index_name FROM duckdb_indexes()").fetchall()
    }
    assert "line_upgrade_scores_scenario_rank" in index_names

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from pipelines.db import (
    CONTRACT_TABLES,
    PROVENANCE_COLUMN_NAMES,
    SCHEMA_STATEMENTS,
    SCHEMA_VERSION,
    connect,
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


def test_line_upgrade_score_index_exists_for_scenario_filtering() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    index_names = {
        row[0]
        for row in con.execute("SELECT index_name FROM duckdb_indexes()").fetchall()
    }
    assert "line_upgrade_scores_scenario_rank" in index_names


# The 1.0.0 shape of the two derived tables, frozen from the pre-2.0.0 pipelines/db.py
# (master at the time of this change) so a v1 database can be rebuilt without git history.
_V1_LINE_UPGRADE_STATEMENTS = {
    "line_upgrade_scores": """CREATE TABLE IF NOT EXISTS line_upgrade_scores (
        line_id BIGINT PRIMARY KEY REFERENCES lines(line_id), congestion_usd_yr DOUBLE,
        dlr_uplift_mw DOUBLE, reconductor_uplift_mw DOUBLE, dlr_cost_usd DOUBLE,
        reconductor_cost_usd DOUBLE, mw_per_musd DOUBLE, ferc_screen_pass BOOLEAN,
        spark_eligible BOOLEAN, source_name TEXT NOT NULL, source_ref TEXT NOT NULL, source_version TEXT,
        source_retrieved_at TIMESTAMP, fixture_batch_id TEXT NOT NULL)""",
    "line_upgrade_detail": """CREATE TABLE IF NOT EXISTS line_upgrade_detail (
        line_id BIGINT PRIMARY KEY REFERENCES lines(line_id), owner TEXT, conductor_material TEXT,
        conductor_kcmil DOUBLE, static_rating_mw DOUBLE NOT NULL CHECK (static_rating_mw >= 0),
        aar_rating_mw DOUBLE, dlr_p50_mw DOUBLE, dlr_hours_above_static INTEGER,
        best_tech TEXT CHECK (best_tech IN ('dlr', 'reconductor')), payback_yr DOUBLE,
        congestion_method TEXT NOT NULL CHECK (congestion_method IN ('exact', 'fuzzy', 'twin_proxy', 'unmapped')),
        region TEXT NOT NULL, source_name TEXT NOT NULL, source_ref TEXT NOT NULL, source_version TEXT,
        source_retrieved_at TIMESTAMP, fixture_batch_id TEXT NOT NULL)""",
}


def _build_v1_database(path: Path) -> set[str]:
    """Create a 1.0.0 grid.duckdb: v1 line-upgrade tables, no scenario index, v1 version row."""
    con = duckdb.connect(str(path))
    try:
        for statement in SCHEMA_STATEMENTS:
            if statement.lstrip().startswith("CREATE INDEX"):
                continue
            for table, v1_statement in _V1_LINE_UPGRADE_STATEMENTS.items():
                if f"CREATE TABLE IF NOT EXISTS {table} (" in statement:
                    statement = v1_statement
            con.execute(statement)
        con.execute("INSERT INTO schema_meta (key, value) VALUES ('contract_version', '1.0.0')")
        return {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    finally:
        con.close()


def test_opening_a_v1_database_raises_the_named_migration_error_before_any_ddl(tmp_path: Path) -> None:
    """A stale database must fail on the version guard, not on a DDL bind error.

    On a v1 file every CREATE TABLE IF NOT EXISTS is a no-op, so without the guard
    running first the scenario index binds `scenario_id` against the old table and
    raises an unnamed duckdb BinderException.
    """
    path = tmp_path / "grid.duckdb"
    v1_tables = _build_v1_database(path)

    with pytest.raises(RuntimeError, match=r"contract version is '1\.0\.0', expected '2\.0\.0'; migrate explicitly"):
        connect(path)

    con = duckdb.connect(str(path))
    try:
        assert con.execute("SELECT value FROM schema_meta WHERE key = 'contract_version'").fetchone() == ("1.0.0",)
        assert {row[0] for row in con.execute("SHOW TABLES").fetchall()} == v1_tables
        v1_columns = {row[1] for row in con.execute("PRAGMA table_info('line_upgrade_scores')").fetchall()}
        assert "scenario_id" not in v1_columns
        assert con.execute("SELECT count(*) FROM duckdb_indexes()").fetchone() == (0,)
    finally:
        con.close()

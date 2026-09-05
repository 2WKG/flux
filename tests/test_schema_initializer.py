from __future__ import annotations

import duckdb
import pytest

from pipelines.db import ADDITIVE_TABLES, CONTRACT_TABLES, SCHEMA_VERSION, ensure_schema


def test_initializer_is_idempotent_and_records_stable_contract_metadata() -> None:
    con = duckdb.connect(":memory:")

    ensure_schema(con)
    first_metadata = con.execute(
        "SELECT key, value FROM schema_meta ORDER BY key"
    ).fetchall()
    ensure_schema(con)
    second_metadata = con.execute(
        "SELECT key, value FROM schema_meta ORDER BY key"
    ).fetchall()

    assert first_metadata == [("contract_version", SCHEMA_VERSION)]
    assert second_metadata == first_metadata
    assert set(CONTRACT_TABLES + ADDITIVE_TABLES) <= {
        row[0] for row in con.execute("SHOW TABLES").fetchall()
    }


def test_initializer_creates_documented_primary_key_constraints() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)

    expected_primary_keys = {
        "counties": {"county_fips"},
        "lines": {"line_id"},
        "eaglei_outages": {"county_fips", "ts"},
        "outage_predictions": {"scenario_id", "county_fips", "ts"},
        "cascade_runs": {"run_id", "hour"},
        "site_scores": {"site_id", "scenario_id", "unit_mw"},
        "line_upgrade_detail": {"line_id"},
        "corpus_chunks": {"chunk_id"},
    }

    for table, expected in expected_primary_keys.items():
        columns = con.execute(f"PRAGMA table_info('{table}')").fetchall()
        assert {column[1] for column in columns if column[5]} == expected


def test_initializer_preserves_existing_fixture_rows() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute(
        """INSERT INTO counties VALUES (
            '27053', 'Hennepin', 'MN', 1260000, X'00',
            'fixture', 'county:27053', '2026.09', NULL, 'minnesota-v1'
        )"""
    )

    ensure_schema(con)

    assert con.execute(
        "SELECT county_fips, name, fixture_batch_id FROM counties"
    ).fetchall() == [("27053", "Hennepin", "minnesota-v1")]


def test_initializer_requires_an_explicit_migration_for_another_version() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("UPDATE schema_meta SET value = '0.9.0' WHERE key = 'contract_version'")

    with pytest.raises(RuntimeError, match="migrate explicitly"):
        ensure_schema(con)

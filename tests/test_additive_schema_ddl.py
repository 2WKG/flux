from __future__ import annotations

import duckdb
import pytest

from pipelines.db import (
    ADDITIVE_SCHEMA_STATEMENTS,
    ADDITIVE_TABLES,
    PROVENANCE_COLUMNS,
    SCHEMA_STATEMENTS,
)


def _schema_with_additions() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    for statement in SCHEMA_STATEMENTS + ADDITIVE_SCHEMA_STATEMENTS:
        con.execute(statement)
    return con


def test_additive_ddl_creates_only_the_documented_extension_tables() -> None:
    con = _schema_with_additions()
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}

    assert set(ADDITIVE_TABLES) <= tables


def test_additive_tables_preserve_contract_provenance_and_embedding_type() -> None:
    con = _schema_with_additions()
    expected_provenance = {
        line.split()[0] for line in PROVENANCE_COLUMNS.splitlines() if line.strip()
    }

    for table in ADDITIVE_TABLES:
        columns = {
            row[1]: row[2]
            for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()
        }
        assert expected_provenance <= columns.keys()

    assert (
        con.execute("PRAGMA table_info('corpus_chunks')").fetchall()[6][2]
        == "FLOAT[1024]"
    )


def test_corpus_chunk_identity_is_unique_and_requires_a_positive_page() -> None:
    con = _schema_with_additions()
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            """INSERT INTO corpus_chunks VALUES (
                'bad-page', 'nrc', 'NRC', 0, 0, 'text', NULL,
                'fixture', 'document:nrc', NULL, NULL, 'b1'
            )"""
        )

    con.execute(
        """INSERT INTO corpus_chunks VALUES (
            'nrc-1-0', 'nrc', 'NRC', 1, 0, 'text', NULL,
            'fixture', 'document:nrc', NULL, NULL, 'b1'
        )"""
    )
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            """INSERT INTO corpus_chunks VALUES (
                'nrc-1-0-rechunked', 'nrc', 'NRC', 1, 0, 'different text', NULL,
                'fixture', 'document:nrc', NULL, NULL, 'b1'
            )"""
        )

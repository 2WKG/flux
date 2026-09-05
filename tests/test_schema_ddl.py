from __future__ import annotations

import duckdb
import pytest

from pipelines.db import CONTRACT_TABLES, PROVENANCE_COLUMNS, SCHEMA_STATEMENTS


def _fresh_schema() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    for statement in SCHEMA_STATEMENTS:
        con.execute(statement)
    return con


def test_contract_ddl_creates_every_non_additive_table() -> None:
    con = _fresh_schema()

    assert {row[0] for row in con.execute("SHOW TABLES").fetchall()} == set(
        CONTRACT_TABLES
    )
    assert "line_upgrade_detail" not in CONTRACT_TABLES
    assert "corpus_chunks" not in CONTRACT_TABLES


def test_every_contract_table_carries_the_declared_provenance_fields() -> None:
    con = _fresh_schema()
    expected = {
        line.split()[0] for line in PROVENANCE_COLUMNS.splitlines() if line.strip()
    }

    for table in CONTRACT_TABLES:
        columns = {
            row[1] for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()
        }
        assert expected <= columns


@pytest.mark.parametrize(
    ("statement", "match"),
    [
        (
            """INSERT INTO counties VALUES (
                '4800', 'Bad FIPS', 'TX', 1, X'00', 'fixture', 'record', NULL, NULL, 'b1'
            )""",
            "CHECK",
        ),
        (
            """INSERT INTO counties VALUES (
                '48001', 'Valid County', 'TX', 1, X'00', 'fixture', 'record', NULL, NULL, 'b1'
            )""",
            None,
        ),
        (
            """INSERT INTO buses VALUES (
                1, 'bad coordinates', 115.0, 200.0, 45.0, '48001', NULL, 'fixture', NULL, NULL,
                'fixture', 'bus:1', NULL, NULL, 'b1'
            )""",
            "CHECK",
        ),
    ],
)
def test_key_and_coordinate_constraints(statement: str, match: str | None) -> None:
    con = _fresh_schema()
    if match is None:
        con.execute(statement)
    else:
        with pytest.raises(duckdb.ConstraintException, match=match):
            con.execute(statement)


def test_contract_enforces_documented_foreign_key_and_unique_rules() -> None:
    con = _fresh_schema()
    con.execute(
        """INSERT INTO counties VALUES (
            '48001', 'Valid County', 'TX', 1, X'00', 'fixture', 'county:48001', NULL, NULL, 'b1'
        )"""
    )
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            """INSERT INTO eaglei_outages VALUES (
                '99999', TIMESTAMP '2021-02-13 00:00:00', 0,
                'fixture', 'outage:missing-county', NULL, NULL, 'b1'
            )"""
        )

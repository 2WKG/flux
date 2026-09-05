from __future__ import annotations

import duckdb

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

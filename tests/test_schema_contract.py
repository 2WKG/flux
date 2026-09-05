from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from pipelines.db import CONTRACT_TABLES, PROVENANCE_COLUMN_NAMES, SCHEMA_VERSION, ensure_schema, replace_frame


def test_schema_is_versioned_and_idempotent() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    ensure_schema(con)

    assert con.execute("SELECT value FROM schema_meta WHERE key = 'contract_version'").fetchone() == (SCHEMA_VERSION,)
    assert set(CONTRACT_TABLES) <= {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    columns = {row[1] for row in con.execute("PRAGMA table_info('corpus_chunks')").fetchall()}
    assert set(PROVENANCE_COLUMN_NAMES) <= columns
    assert con.execute("PRAGMA table_info('corpus_chunks')").fetchall()[6][2] == "FLOAT[1024]"


def test_contract_rows_reject_missing_provenance() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    with pytest.raises(ValueError, match="requires source_name"):
        replace_frame(con, "counties", pd.DataFrame([{
            "county_fips": "48001", "name": "Fixture", "state": "TX", "pop": 1, "geom_wkb": b"fixture",
        }]))

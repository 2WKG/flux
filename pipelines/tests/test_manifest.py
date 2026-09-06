import json

import duckdb
import pytest

from pipelines.db import SCHEMA_VERSION, ensure_schema
from pipelines.manifest import (
    SYNTHETIC_TABLES,
    build_manifest,
    store_manifest,
    write_manifest,
)


def test_manifest_records_schema_version_and_scope(tmp_path):
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    ensure_schema(con)
    manifest = build_manifest(con, state_scope="tx")
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["state_scope"] == "tx"
    assert "build_timestamp" in manifest
    assert manifest["build_timestamp"].endswith("Z")
    con.close()


def test_manifest_classifies_tables_as_synthetic_or_real(tmp_path):
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    ensure_schema(con)
    manifest = build_manifest(con, state_scope="tx")
    tables = manifest["tables"]
    for table in SYNTHETIC_TABLES:
        if table in tables:
            assert tables[table]["classification"] == "synthetic"
    for table_name, entry in tables.items():
        if table_name not in SYNTHETIC_TABLES:
            assert entry["classification"] == "real"
    con.close()


def test_manifest_empty_db_has_zero_row_counts(tmp_path):
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    ensure_schema(con)
    manifest = build_manifest(con, state_scope="mn")
    for table_name, entry in manifest["tables"].items():
        assert entry["row_count"] == 0, f"{table_name} should be empty"
    con.close()


def test_manifest_has_content_sha256_for_all_tables(tmp_path):
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    ensure_schema(con)
    manifest = build_manifest(con, state_scope="tx")
    for table_name, entry in manifest["tables"].items():
        assert isinstance(entry["content_sha256"], str)
        assert len(entry["content_sha256"]) == 64
    con.close()


def test_manifest_stable_hash_for_same_data(tmp_path):
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    ensure_schema(con)
    manifest1 = build_manifest(con, state_scope="tx")
    manifest2 = build_manifest(con, state_scope="tx")
    for table_name in manifest1["tables"]:
        assert (
            manifest1["tables"][table_name]["content_sha256"]
            == manifest2["tables"][table_name]["content_sha256"]
        )
    con.close()


def test_store_and_read_manifest(tmp_path):
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    ensure_schema(con)
    manifest = build_manifest(con, state_scope="tx")
    store_manifest(con, manifest)
    stored = con.execute(
        "SELECT value FROM schema_meta WHERE key = 'manifest'"
    ).fetchone()
    assert stored is not None
    parsed = json.loads(stored[0])
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert parsed["state_scope"] == "tx"
    con.close()


def test_write_manifest_file(tmp_path):
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    ensure_schema(con)
    manifest = build_manifest(con, state_scope="mn")
    output = tmp_path / "manifest.json"
    written = write_manifest(manifest, output)
    assert written == output
    assert output.exists()
    parsed = json.loads(output.read_text())
    assert parsed["state_scope"] == "mn"
    assert parsed["schema_version"] == SCHEMA_VERSION
    con.close()


def test_manifest_primary_key_match(tmp_path):
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    ensure_schema(con)
    manifest = build_manifest(con, state_scope="tx")
    from pipelines.db import TABLE_COLUMNS

    for table_name, entry in manifest["tables"].items():
        if table_name in TABLE_COLUMNS:
            expected_pk = TABLE_COLUMNS[table_name][0]
            assert entry["primary_key"] == expected_pk, (
                f"{table_name}: expected pk={expected_pk}, got {entry['primary_key']}"
            )
    con.close()
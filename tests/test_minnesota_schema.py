import duckdb
import pytest

from pipelines.db import SCHEMA_VERSION as LEGACY_SCHEMA_VERSION
from pipelines.db import ensure_schema
from pipelines.minnesota_schema import SCHEMA_VERSION, TABLES, ensure_minnesota_schema


def test_initialization_is_idempotent_and_preserves_rows():
    con = duckdb.connect(":memory:")
    ensure_minnesota_schema(con)
    con.execute(
        "INSERT INTO mn_artifact_manifests VALUES ('mn:fixture:0000000000000000','fixture',?,'mn','unavailable','not_applicable','{}',CURRENT_TIMESTAMP,'[]','[\"not built\"]','[]')",
        [SCHEMA_VERSION],
    )
    ensure_minnesota_schema(con)
    assert set(TABLES) <= {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert con.execute("SELECT count(*) FROM mn_artifact_manifests").fetchone() == (1,)


def test_incompatible_version_fails_before_mutation():
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE mn_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    con.execute("INSERT INTO mn_schema_meta VALUES ('contract_version','old')")
    with pytest.raises(RuntimeError, match="migrate explicitly"):
        ensure_minnesota_schema(con)
    assert con.execute("SHOW TABLES").fetchall() == [("mn_schema_meta",)]


def test_unversioned_minnesota_table_fails_before_mutation():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE mn_artifact_manifests (artifact_id TEXT)")
    with pytest.raises(RuntimeError, match="metadata is absent"):
        ensure_minnesota_schema(con)
    assert con.execute("SHOW TABLES").fetchall() == [("mn_artifact_manifests",)]


def test_coordinates_and_available_provenance_are_enforced():
    con = duckdb.connect(":memory:")
    ensure_minnesota_schema(con)
    con.execute(
        "INSERT INTO mn_artifact_manifests VALUES ('mn:geography:0000000000000000','geography',?,'mn','available','not_applicable','{}',CURRENT_TIMESTAMP,'[]','[\"limit\"]','[]')",
        [SCHEMA_VERSION],
    )
    with pytest.raises(RuntimeError, match="no provenance"):
        ensure_minnesota_schema(con)


def test_legacy_schema_and_rows_remain_untouched():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("INSERT INTO schema_meta VALUES ('legacy_marker', 'kept')")
    ensure_minnesota_schema(con)
    assert con.execute(
        "SELECT value FROM schema_meta WHERE key='contract_version'"
    ).fetchone() == (LEGACY_SCHEMA_VERSION,)
    assert con.execute(
        "SELECT value FROM schema_meta WHERE key='legacy_marker'"
    ).fetchone() == ("kept",)
    assert con.execute(
        "SELECT value FROM mn_schema_meta WHERE key='contract_version'"
    ).fetchone() == (SCHEMA_VERSION,)


def test_malformed_coordinates_and_provenance_are_rejected_by_database():
    con = duckdb.connect(":memory:")
    ensure_minnesota_schema(con)
    con.execute(
        "INSERT INTO mn_artifact_manifests VALUES ('mn:g:1','geography',?,'mn','unavailable','not_applicable','{}',CURRENT_TIMESTAMP,'[]','[\"limit\"]','[]')",
        [SCHEMA_VERSION],
    )
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO mn_geography_artifacts VALUES ('mn:g:1',NULL,1,NULL,'source',NULL)"
        )
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO mn_artifact_provenance VALUES ('mn:g:1',0,'x','y','v',CURRENT_TIMESTAMP,'terms',NULL,'bad',false)"
        )


def test_unavailable_domain_row_is_rejected_on_rerun():
    con = duckdb.connect(":memory:")
    ensure_minnesota_schema(con)
    con.execute(
        "INSERT INTO mn_artifact_manifests VALUES ('mn:f:1','fixture',?,'mn','unavailable','not_applicable','{}',CURRENT_TIMESTAMP,'[]','[\"limit\"]','[]')",
        [SCHEMA_VERSION],
    )
    con.execute(
        "INSERT INTO mn_fixture_artifacts VALUES ('mn:f:1','mn:f:1','preview',NULL)"
    )
    with pytest.raises(RuntimeError, match="domain row requires available"):
        ensure_minnesota_schema(con)

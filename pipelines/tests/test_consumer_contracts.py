from __future__ import annotations

from pathlib import Path

import duckdb

from pipelines.consumer_contracts import CONSUMER_READ_PATHS, check_consumer_contracts
from pipelines.db import ensure_schema


def _fixture_db(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.duckdb"
    with duckdb.connect(str(path)) as con:
        ensure_schema(con)
    return path


def test_each_consumer_reads_a_complete_offline_fixture(tmp_path: Path) -> None:
    report = check_consumer_contracts(_fixture_db(tmp_path))

    assert report.available
    assert [result.consumer for result in report.results] == list(CONSUMER_READ_PATHS)
    assert all(result.status == "available" for result in report.results)


def test_missing_table_names_the_exact_contract_element(tmp_path: Path) -> None:
    path = _fixture_db(tmp_path)
    with duckdb.connect(str(path)) as con:
        con.execute("DROP TABLE corpus_chunks")

    result = check_consumer_contracts(path).result_for("retrieval")

    assert result.status == "unavailable"
    assert result.unavailable_code == "invalid_prerequisite"
    assert result.reason is not None
    assert '"corpus_chunks"' in result.reason


def test_missing_column_names_the_exact_contract_element(tmp_path: Path) -> None:
    path = tmp_path / "missing-rate.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO schema_meta VALUES ('contract_version', '1.0.0')")
        con.execute("CREATE TABLE buses (bus_id BIGINT, base_kv DOUBLE, lon DOUBLE, lat DOUBLE)")
        con.execute("CREATE TABLE lines (line_id BIGINT, from_bus BIGINT, to_bus BIGINT, r_pu DOUBLE, x_pu DOUBLE)")
        con.execute("CREATE TABLE gens (gen_id BIGINT, bus_id BIGINT, pmax_mw DOUBLE)")
        con.execute("CREATE TABLE loads (load_id BIGINT, bus_id BIGINT, p_mw_nominal DOUBLE)")

    result = check_consumer_contracts(path).result_for("twin")

    assert result.status == "unavailable"
    assert result.reason is not None
    assert '"rate_a_mw"' in result.reason


def test_missing_fixture_is_documented_unavailable(tmp_path: Path) -> None:
    missing = tmp_path / "missing.duckdb"
    report = check_consumer_contracts(missing)

    assert not report.available
    assert {result.unavailable_code for result in report.results} == {"invalid_prerequisite"}
    assert all(result.reason is not None and "does not exist" in result.reason for result in report.results)


def test_wrong_contract_version_is_named(tmp_path: Path) -> None:
    path = _fixture_db(tmp_path)
    with duckdb.connect(str(path)) as con:
        con.execute("UPDATE schema_meta SET value = '0.0.0' WHERE key = 'contract_version'")

    result = check_consumer_contracts(path).result_for("api")

    assert result.status == "unavailable"
    assert result.reason == 'invalid contract element "schema_meta.contract_version": expected 1.0.0, found \'0.0.0\''

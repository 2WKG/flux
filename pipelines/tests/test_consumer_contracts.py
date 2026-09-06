from __future__ import annotations

import hashlib
import os
from pathlib import Path

import duckdb
import pytest

from copilot.tools.schemas import Unavailable
from pipelines import consumer_contracts
from pipelines.consumer_contracts import CONSUMER_READ_PATHS, check_consumer_contracts
from pipelines.db import ensure_schema


def _fixture_db(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.duckdb"
    with duckdb.connect(str(path)) as con:
        ensure_schema(con)
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_digests(directory: Path) -> dict[str, str]:
    return {entry.name: _sha256(entry) for entry in sorted(directory.iterdir())}


def _twin_contract_db(
    path: Path,
    *,
    lon_type: str = "DOUBLE",
    provenance: str = "source_name TEXT, source_ref TEXT, fixture_batch_id TEXT",
) -> None:
    """Make an unconstrained twin fixture for diagnostics that DDL blocks."""

    with duckdb.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        con.execute("INSERT INTO schema_meta VALUES ('contract_version', '1.0.0')")
        con.execute(
            f"CREATE TABLE buses (bus_id BIGINT, base_kv DOUBLE, lon {lon_type}, lat DOUBLE, {provenance})"
        )
        con.execute(
            "CREATE TABLE lines (line_id BIGINT, from_bus BIGINT, to_bus BIGINT, r_pu DOUBLE, "
            f"x_pu DOUBLE, rate_a_mw DOUBLE, {provenance})"
        )
        con.execute(
            f"CREATE TABLE gens (gen_id BIGINT, bus_id BIGINT, pmax_mw DOUBLE, {provenance})"
        )
        con.execute(
            f"CREATE TABLE loads (load_id BIGINT, bus_id BIGINT, p_mw_nominal DOUBLE, {provenance})"
        )


def test_each_consumer_reads_a_complete_offline_fixture(tmp_path: Path) -> None:
    report = check_consumer_contracts(_fixture_db(tmp_path))

    assert report.available
    assert [result.consumer for result in report.results] == list(CONSUMER_READ_PATHS)
    assert all(result.status == "available" for result in report.results)
    assert all(result.unavailable is None for result in report.results)


def test_full_check_suite_opens_read_only_and_leaves_no_wal(tmp_path: Path) -> None:
    path = _fixture_db(tmp_path)
    before = _directory_digests(tmp_path)
    assert list(before) == ["fixture.duckdb"]

    # A read-write open of a 0444 file fails, so any non-read-only connection
    # inside the harness surfaces as an unavailable result instead of a write.
    path.chmod(0o444)
    try:
        if os.geteuid() != 0:
            with pytest.raises(duckdb.IOException):
                duckdb.connect(str(path))
        with duckdb.connect(str(path), read_only=True) as con:
            assert con.execute(
                "SELECT value FROM schema_meta WHERE key = 'contract_version'"
            ).fetchone() == ("1.0.0",)

        report = check_consumer_contracts(path)
    finally:
        path.chmod(0o644)

    assert report.available, [result.reason for result in report.results]
    # A write through a connection that is never closed lands in
    # ``fixture.duckdb.wal`` while the main file's hash stays unchanged.
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["fixture.duckdb"]
    assert _directory_digests(tmp_path) == before


def test_missing_table_names_the_exact_contract_element(tmp_path: Path) -> None:
    path = _fixture_db(tmp_path)
    with duckdb.connect(str(path)) as con:
        con.execute("DROP TABLE corpus_chunks")

    result = check_consumer_contracts(path).result_for("retrieval")

    assert result.status == "unavailable"
    assert result.unavailable_code == "invalid_prerequisite"
    assert result.diagnostic_kind == "contract_violation"
    assert result.reason is not None
    assert '"corpus_chunks"' in result.reason


def test_missing_column_names_the_exact_contract_element(tmp_path: Path) -> None:
    path = tmp_path / "missing-rate.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        con.execute("INSERT INTO schema_meta VALUES ('contract_version', '1.0.0')")
        con.execute(
            "CREATE TABLE buses (bus_id BIGINT, base_kv DOUBLE, lon DOUBLE, lat DOUBLE)"
        )
        con.execute(
            "CREATE TABLE lines (line_id BIGINT, from_bus BIGINT, to_bus BIGINT, r_pu DOUBLE, x_pu DOUBLE)"
        )
        con.execute("CREATE TABLE gens (gen_id BIGINT, bus_id BIGINT, pmax_mw DOUBLE)")
        con.execute(
            "CREATE TABLE loads (load_id BIGINT, bus_id BIGINT, p_mw_nominal DOUBLE)"
        )

    result = check_consumer_contracts(path).result_for("twin")

    assert result.status == "unavailable"
    assert result.diagnostic_kind == "contract_violation"
    assert result.reason is not None
    assert '"lines.rate_a_mw"' in result.reason


def test_missing_provenance_column_names_the_exact_contract_element(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing-batch.duckdb"
    _twin_contract_db(path, provenance="source_name TEXT, source_ref TEXT")

    result = check_consumer_contracts(path).result_for("twin")

    assert result.status == "unavailable"
    assert result.diagnostic_kind == "contract_violation"
    assert result.reason == 'contract violation: missing field "buses.fixture_batch_id"'


def test_missing_fixture_is_documented_unavailable_without_opening_duckdb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.duckdb"

    def refuse_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "a missing fixture must be detected before DuckDB is opened"
        )

    monkeypatch.setattr(consumer_contracts.duckdb, "connect", refuse_connect)

    report = check_consumer_contracts(missing)

    assert not report.available
    assert {result.unavailable_code for result in report.results} == {
        "artifact_unavailable"
    }
    assert {result.diagnostic_kind for result in report.results} == {
        "artifact_unavailable"
    }
    assert {result.reason for result in report.results} == {
        f"fixture database unavailable: {missing} does not exist"
    }


def test_unavailable_results_carry_the_shared_unavailable_contract(
    tmp_path: Path,
) -> None:
    path = _fixture_db(tmp_path)
    with duckdb.connect(str(path)) as con:
        con.execute("DROP TABLE corpus_chunks")

    missing = check_consumer_contracts(tmp_path / "missing.duckdb").result_for("twin")
    violated = check_consumer_contracts(path).result_for("retrieval")

    assert missing.unavailable == Unavailable(
        code="artifact_unavailable",
        reason=f"fixture database unavailable: {tmp_path / 'missing.duckdb'} does not exist",
        retryable=False,
    )
    assert violated.unavailable == Unavailable(
        code="invalid_prerequisite",
        reason='contract violation: missing table "corpus_chunks"',
        retryable=False,
    )
    for result in (missing, violated):
        assert result.unavailable is not None
        assert set(result.unavailable.model_dump()) == {"code", "reason", "retryable"}
        assert (
            Unavailable.model_validate(result.unavailable.model_dump())
            == result.unavailable
        )


def test_wrong_contract_version_is_named(tmp_path: Path) -> None:
    path = _fixture_db(tmp_path)
    with duckdb.connect(str(path)) as con:
        con.execute(
            "UPDATE schema_meta SET value = '0.0.0' WHERE key = 'contract_version'"
        )

    result = check_consumer_contracts(path).result_for("api")

    assert result.status == "unavailable"
    assert result.diagnostic_kind == "contract_violation"
    assert result.reason == (
        "contract violation: invalid contract element "
        "\"schema_meta.contract_version\": expected 1.0.0, found '0.0.0'"
    )


@pytest.mark.parametrize(
    ("row", "expected_reason"),
    [
        pytest.param(
            "(1, 115, 999, 44, 'fixture', 'bus:1', 'batch-1')",
            'field "buses.lon" is not a valid EPSG:4326 longitude in [-180, 180]',
            id="lon-above-upper-bound",
        ),
        pytest.param(
            "(1, 115, -181, 44, 'fixture', 'bus:1', 'batch-1')",
            'field "buses.lon" is not a valid EPSG:4326 longitude in [-180, 180]',
            id="lon-below-lower-bound",
        ),
        pytest.param(
            "(1, 115, -93, 91, 'fixture', 'bus:1', 'batch-1')",
            'field "buses.lat" is not a valid EPSG:4326 latitude in [-90, 90]',
            id="lat-above-upper-bound",
        ),
        pytest.param(
            "(1, 115, 30, -97, 'fixture', 'bus:1', 'batch-1')",
            'field "buses.lat" is not a valid EPSG:4326 latitude in [-90, 90]',
            id="lat-below-lower-bound-swapped-axes",
        ),
        pytest.param(
            "(1, 115, NULL, 44, 'fixture', 'bus:1', 'batch-1')",
            'field "buses.lon" is not a valid EPSG:4326 longitude in [-180, 180]',
            id="lon-null",
        ),
        pytest.param(
            "(1, 115, -93, NULL, 'fixture', 'bus:1', 'batch-1')",
            'field "buses.lat" is not a valid EPSG:4326 latitude in [-90, 90]',
            id="lat-null",
        ),
    ],
)
def test_bad_coordinate_is_an_epsg_4326_contract_violation(
    tmp_path: Path, row: str, expected_reason: str
) -> None:
    path = tmp_path / "bad-coordinate.duckdb"
    _twin_contract_db(path)
    with duckdb.connect(str(path)) as con:
        con.execute(f"INSERT INTO buses VALUES {row}")

    result = check_consumer_contracts(path).result_for("twin")

    assert result.status == "unavailable"
    assert result.diagnostic_kind == "contract_violation"
    assert result.reason == f"contract violation: {expected_reason}"


@pytest.mark.parametrize("lon_type", ["TEXT", "BOOLEAN", "BLOB"])
def test_wrong_coordinate_type_is_a_named_contract_violation(
    tmp_path: Path, lon_type: str
) -> None:
    path = tmp_path / "text-coordinate.duckdb"
    _twin_contract_db(path, lon_type=lon_type)
    with duckdb.connect(str(path)) as con:
        literal = {"TEXT": "'west'", "BOOLEAN": "true", "BLOB": "'\\x00'::BLOB"}[
            lon_type
        ]
        con.execute(
            f"INSERT INTO buses VALUES (1, 115, {literal}, 44, 'fixture', 'bus:1', 'batch-1')"
        )

    result = check_consumer_contracts(path).result_for("twin")

    assert result.status == "unavailable"
    assert result.diagnostic_kind == "contract_violation"
    declared = {"TEXT": "VARCHAR", "BOOLEAN": "BOOLEAN", "BLOB": "BLOB"}[lon_type]
    assert result.reason == (
        f'contract violation: field "buses.lon" has type {declared}, expected a numeric EPSG:4326 coordinate'
    )
    assert "Binder Error" not in result.reason


def test_binder_failures_inside_contract_checks_are_contract_violations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _fixture_db(tmp_path)

    def explode(*args: object, **kwargs: object) -> str | None:
        raise duckdb.BinderException(
            "Binder Error: Cannot compare values of type VARCHAR and type INTEGER"
        )

    monkeypatch.setattr(consumer_contracts, "_coordinate_contract_error", explode)

    result = check_consumer_contracts(path).result_for("twin")

    assert result.status == "unavailable"
    assert result.diagnostic_kind == "contract_violation"
    assert result.unavailable_code == "invalid_prerequisite"
    assert result.reason == (
        "contract violation: fixture read for twin did not bind against the contract: "
        "Binder Error: Cannot compare values of type VARCHAR and type INTEGER"
    )


@pytest.mark.parametrize(
    ("row", "field"),
    [
        pytest.param(
            "(1, 115, -93, 44, '', 'bus:1', 'batch-1')",
            "source_name",
            id="blank-source-name",
        ),
        pytest.param(
            "(1, 115, -93, 44, 'fixture', NULL, 'batch-1')",
            "source_ref",
            id="null-source-ref",
        ),
        pytest.param(
            "(1, 115, -93, 44, 'fixture', 'bus:1', NULL)",
            "fixture_batch_id",
            id="null-batch-id",
        ),
        pytest.param(
            "(1, 115, -93, 44, 'fixture', 'bus:1', '   ')",
            "fixture_batch_id",
            id="whitespace-batch-id",
        ),
    ],
)
def test_missing_provenance_is_a_named_contract_violation(
    tmp_path: Path, row: str, field: str
) -> None:
    path = tmp_path / "blank-provenance.duckdb"
    _twin_contract_db(path)
    with duckdb.connect(str(path)) as con:
        con.execute(f"INSERT INTO buses VALUES {row}")

    result = check_consumer_contracts(path).result_for("twin")

    assert result.status == "unavailable"
    assert result.diagnostic_kind == "contract_violation"
    assert (
        result.reason
        == f'contract violation: field "buses.{field}" is blank or unavailable'
    )

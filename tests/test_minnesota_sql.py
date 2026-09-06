"""Behavioral checks for the fail-closed Minnesota SQL executor."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import duckdb
import pytest
from pydantic import ValidationError

from copilot.tools.schemas import ArtifactRef, SqlInput
from copilot.tools.sql import (
    ROW_LIMIT,
    ApprovedMinnesotaQuery,
    ApprovedMinnesotaView,
    MinnesotaSqlExecutor,
    SqlRejected,
)


def _view() -> ApprovedMinnesotaView:
    return ApprovedMinnesotaView(
        "mn_summary",
        (
            ArtifactRef(
                artifact_id="mn:fixture:0123456789abcdef",
                artifact_version="2.0.0-mn",
                source_kind="fixture",
                source_ref="data/duck/grid.duckdb",
            ),
        ),
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "accepted-mn.duckdb"
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE accepted_rows (id INTEGER, label TEXT)")
        con.execute("CREATE TABLE secret_rows (id INTEGER, label TEXT)")
        con.execute(
            "INSERT INTO accepted_rows SELECT range, 'row-' || range::VARCHAR FROM range(205)"
        )
        con.execute("INSERT INTO secret_rows VALUES (1, 'not-approved')")
        con.execute("CREATE VIEW mn_summary AS SELECT * FROM accepted_rows")
    finally:
        con.close()
    return path


def _execute(executor: MinnesotaSqlExecutor, query: str):
    return asyncio.run(executor.execute(SqlInput(query=query)))


def test_no_registered_views_and_missing_database_are_explicitly_unavailable(
    tmp_path: Path,
) -> None:
    result = _execute(MinnesotaSqlExecutor(tmp_path / "absent.duckdb"), "SELECT 1")

    assert result.status == "unavailable"
    assert result.unavailable is not None
    assert result.unavailable.code == "artifact_unavailable"
    assert not (tmp_path / "absent.duckdb").exists()


def test_no_registered_minnesota_views_fails_closed(db_path: Path) -> None:
    result = _execute(MinnesotaSqlExecutor(db_path), "SELECT * FROM mn_summary")

    assert result.status == "unavailable"
    assert result.unavailable is not None
    assert result.unavailable.code == "artifact_unavailable"


def test_named_template_registry_executes_declared_view_and_rejects_raw_sql(
    db_path: Path,
) -> None:
    template = ApprovedMinnesotaQuery(
        name="summary_rows",
        sql="SELECT id, label FROM mn_summary ORDER BY id",
        relations=frozenset({"mn_summary"}),
    )
    executor = MinnesotaSqlExecutor(db_path, [_view()], [template])

    result = asyncio.run(executor.execute(SqlInput(template_id="summary_rows")))
    raw = _execute(executor, "SELECT id, label FROM mn_summary")
    unknown = asyncio.run(executor.execute(SqlInput(template_id="not_registered")))

    assert result.status == "available"
    assert result.rows[0] == [0, "row-0"]
    assert raw.status == unknown.status == "unavailable"
    assert raw.unavailable is not None and raw.unavailable.code == "unsupported_request"
    assert (
        unknown.unavailable is not None
        and unknown.unavailable.code == "unsupported_request"
    )


def test_template_registry_rejects_mismatched_or_unapproved_relation_declarations(
    db_path: Path,
) -> None:
    with pytest.raises(ValueError, match="not an approved view"):
        MinnesotaSqlExecutor(
            db_path,
            [_view()],
            [
                ApprovedMinnesotaQuery(
                    "wrong_relation",
                    "SELECT * FROM mn_summary",
                    frozenset({"mn_other"}),
                )
            ],
        )


def _other_view() -> ApprovedMinnesotaView:
    return ApprovedMinnesotaView("mn_other", _view().provenance)


def _summary_template(name: str = "summary_rows") -> ApprovedMinnesotaQuery:
    return ApprovedMinnesotaQuery(
        name, "SELECT id, label FROM mn_summary ORDER BY id", frozenset({"mn_summary"})
    )


def _forbid_connect(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []

    def connect(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("duckdb.connect must not be reached")

    monkeypatch.setattr("copilot.tools.sql.duckdb.connect", connect)
    return calls


def test_registry_mode_rejects_raw_and_unknown_input_before_any_connection(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _forbid_connect(monkeypatch)
    executor = MinnesotaSqlExecutor(db_path, [_view()], [_summary_template()])

    raw = _execute(executor, "SELECT id, label FROM mn_summary")
    unknown = asyncio.run(executor.execute(SqlInput(template_id="not_registered")))

    assert raw.status == unknown.status == "unavailable"
    assert raw.unavailable is not None
    assert raw.unavailable.code == "unsupported_request"
    assert unknown.unavailable is not None
    assert unknown.unavailable.code == "unsupported_request"
    assert calls == []


def test_query_and_template_id_together_are_rejected_at_the_boundary() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        SqlInput(query="SELECT id FROM mn_summary", template_id="summary_rows")
    with pytest.raises(ValidationError, match="exactly one"):
        SqlInput()


def test_executor_rejects_both_fields_before_the_registry_or_a_connection(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller that bypasses pydantic still cannot reach the template or DuckDB."""
    calls = _forbid_connect(monkeypatch)
    bypassed = SqlInput.model_construct(
        query="SELECT id FROM mn_summary", template_id="summary_rows"
    )

    registry = asyncio.run(
        MinnesotaSqlExecutor(db_path, [_view()], [_summary_template()]).execute(
            bypassed
        )
    )
    legacy = asyncio.run(MinnesotaSqlExecutor(db_path, [_view()]).execute(bypassed))

    for result in (registry, legacy):
        assert result.status == "unavailable"
        assert result.unavailable is not None
        assert result.unavailable.code == "unsupported_request"
        assert "exactly one" in result.unavailable.reason
    assert calls == []


def test_legacy_mode_names_the_missing_registry_instead_of_dropping_template_id(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _forbid_connect(monkeypatch)

    result = asyncio.run(
        MinnesotaSqlExecutor(db_path, [_view()]).execute(
            SqlInput(template_id="summary_rows")
        )
    )

    assert result.status == "unavailable"
    assert result.unavailable is not None
    assert result.unavailable.code == "unsupported_request"
    assert "registry is not configured" in result.unavailable.reason
    assert calls == []


def test_template_relation_declaration_must_match_the_parsed_sql(
    db_path: Path,
) -> None:
    with pytest.raises(ValueError, match="does not match SQL"):
        MinnesotaSqlExecutor(
            db_path,
            [_view(), _other_view()],
            [
                ApprovedMinnesotaQuery(
                    "declared_superset",
                    "SELECT id FROM mn_summary",
                    frozenset({"mn_summary", "mn_other"}),
                )
            ],
        )


def test_duplicate_template_names_are_rejected_at_construction(db_path: Path) -> None:
    with pytest.raises(ValueError, match="unique"):
        MinnesotaSqlExecutor(
            db_path,
            [_view()],
            [_summary_template(), _summary_template()],
        )


@pytest.mark.parametrize(
    "sql",
    [
        "COPY (SELECT * FROM mn_summary) TO 'x.csv'",
        "SELECT * FROM mn_summary, read_csv('x.csv')",
        "SELECT * FROM mn_summary WHERE id = $1",
        "SELECT * FROM mn_summary; SELECT 1",
    ],
)
def test_template_sql_is_validated_when_the_registry_is_constructed(
    db_path: Path, sql: str
) -> None:
    with pytest.raises(SqlRejected):
        MinnesotaSqlExecutor(
            db_path,
            [_view()],
            [ApprovedMinnesotaQuery("hardened", sql, frozenset({"mn_summary"}))],
        )


@pytest.mark.parametrize(
    "name", ["Summary_rows", "_summary_rows", "summary-rows", "a" * 65]
)
def test_template_names_match_the_public_template_id_contract(name: str) -> None:
    with pytest.raises(ValueError, match="template_id contract"):
        ApprovedMinnesotaQuery(
            name,
            "SELECT id FROM mn_summary",
            frozenset({"mn_summary"}),
        )


def test_reads_only_registered_view_with_cte_comments_and_bound_row_cap(
    db_path: Path,
) -> None:
    result = _execute(
        MinnesotaSqlExecutor(db_path, [_view()]),
        "-- COPY must be ignored in comments\nWITH selected AS (SELECT id, label FROM mn_summary) SELECT * FROM selected; -- trailing",
    )

    assert result.status == "available"
    assert result.columns == ["id", "label"]
    assert result.row_count == ROW_LIMIT
    assert result.truncated is True
    assert result.rows[0] == [0, "row-0"]
    assert result.provenance[0].artifact_id == "mn:fixture:0123456789abcdef"


def test_keywords_in_literals_do_not_trip_the_statement_policy(db_path: Path) -> None:
    result = _execute(
        MinnesotaSqlExecutor(db_path, [_view()]),
        "SELECT 'it''s; COPY read_csv ATTACH' AS \"copy\" FROM mn_summary LIMIT 1; -- ;",
    )

    assert result.status == "available"
    assert result.rows == [["it's; COPY read_csv ATTACH"]]


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1",
        "SELECT version()",
        "SELECT * FROM accepted_rows",
        "SELECT * FROM main.mn_summary",
        "SELECT * FROM mn_summary; SELECT 1",
        "SELECT * FROM mn_summary WHERE id = ?",
        "SELECT * FROM mn_summary WHERE id = $1",
        "SELECT * FROM mn_summary WHERE id = $value",
        "COPY (SELECT * FROM mn_summary) TO 'x.csv'",
        "SELECT * FROM read_csv('x.csv')",
        "SELECT * FROM query_table('mn_summary')",
        "SELECT * FROM glob('*')",
        "SELECT * FROM mn_summary, read_csv('x.csv')",
        "SELECT current_setting('home_directory') FROM mn_summary",
        "SELECT * FROM duckdb_tables()",
        "SELECT * FROM mn_summary WHERE id IN (SELECT id FROM read_parquet('x.parquet'))",
        "WITH x AS (SELECT * FROM mn_summary) SELECT * FROM x JOIN (SELECT * FROM accepted_rows) y USING (id)",
    ],
)
def test_rejects_non_view_relations_table_functions_and_catalog_access(
    db_path: Path, query: str
) -> None:
    result = _execute(MinnesotaSqlExecutor(db_path, [_view()]), query)

    assert result.status == "unavailable"
    assert result.unavailable is not None
    assert result.unavailable.code == "unsupported_request"


@pytest.mark.parametrize(
    "query",
    [
        "SELECT ((SELECT label FROM secret_rows LIMIT 1)) AS leaked FROM mn_summary",
        "SELECT coalesce((SELECT label FROM secret_rows LIMIT 1), label) FROM mn_summary",
        "SELECT CASE WHEN EXISTS (SELECT 1 FROM secret_rows) THEN label END FROM mn_summary",
        "SELECT sum((SELECT id FROM secret_rows LIMIT 1)) FROM mn_summary",
        "SELECT * FROM mn_summary WHERE id = (1 * (SELECT id FROM secret_rows LIMIT 1))",
        "SELECT * FROM mn_summary WHERE id IN ((SELECT id FROM secret_rows))",
        "WITH safe AS (SELECT * FROM mn_summary), leaked AS (SELECT * FROM secret_rows) SELECT * FROM safe",
        "WITH mn_summary AS (SELECT * FROM secret_rows) SELECT * FROM mn_summary",
        "WITH secret_rows AS (SELECT * FROM secret_rows) SELECT s.label FROM secret_rows s CROSS JOIN mn_summary",
        "SELECT label FROM secret_rows WHERE EXISTS (WITH secret_rows AS (SELECT * FROM mn_summary) SELECT 1 FROM secret_rows) LIMIT 1",
        "SELECT * FROM mn_summary UNION ALL SELECT * FROM secret_rows",
        "SELECT * FROM mn_summary m JOIN (SELECT * FROM secret_rows) s USING (id)",
        "SELECT id FROM mn_summary GROUP BY id HAVING id = (SELECT id FROM secret_rows LIMIT 1)",
        "SELECT * FROM mn_summary ORDER BY (SELECT id FROM secret_rows LIMIT 1)",
    ],
)
def test_rejects_unapproved_relations_at_every_ast_depth(
    db_path: Path, query: str
) -> None:
    result = _execute(MinnesotaSqlExecutor(db_path, [_view()]), query)

    assert result.status == "unavailable"
    assert result.unavailable is not None
    assert result.unavailable.code == "unsupported_request"
    assert "rows" not in result.model_dump()


def test_accepts_nested_subqueries_over_approved_view_and_cte(db_path: Path) -> None:
    result = _execute(
        MinnesotaSqlExecutor(db_path, [_view()]),
        "WITH selected AS (SELECT id FROM mn_summary) "
        "SELECT ((SELECT max(id) FROM selected)) AS approved_id FROM selected LIMIT 1",
    )

    assert result.status == "available"
    assert result.rows == [[204]]
    assert result.provenance[0].artifact_id == "mn:fixture:0123456789abcdef"


def test_empty_accepted_view_is_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "empty.duckdb"
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE rows (id INTEGER)")
        con.execute("CREATE VIEW mn_summary AS SELECT * FROM rows")
    finally:
        con.close()

    result = _execute(MinnesotaSqlExecutor(path, [_view()]), "SELECT * FROM mn_summary")

    assert result.status == "unavailable"
    assert result.unavailable is not None
    assert result.unavailable.code == "artifact_unavailable"


def test_rejects_persisted_scalar_macro_before_expansion(db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE MACRO mn_leak() AS current_setting('home_directory')")
    finally:
        con.close()

    result = _execute(
        MinnesotaSqlExecutor(db_path, [_view()]), "SELECT mn_leak() FROM mn_summary"
    )

    assert result.status == "unavailable"
    assert result.unavailable is not None
    assert result.unavailable.code == "unsupported_request"


def test_rejects_quoted_persisted_scalar_macro_before_expansion(
    db_path: Path,
) -> None:
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE MACRO \"mn leak\"() AS current_setting('home_directory')")
    finally:
        con.close()

    result = _execute(
        MinnesotaSqlExecutor(db_path, [_view()]), 'SELECT "mn leak"() FROM mn_summary'
    )

    assert result.status == "unavailable"
    assert result.unavailable is not None
    assert result.unavailable.code == "unsupported_request"


def test_rejected_copy_cannot_create_an_export_target(
    db_path: Path, tmp_path: Path
) -> None:
    target = tmp_path / "must-not-exist.csv"

    result = _execute(
        MinnesotaSqlExecutor(db_path, [_view()]),
        f"COPY (SELECT * FROM mn_summary) TO '{target}'",
    )

    assert result.status == "unavailable"
    assert result.unavailable is not None
    assert result.unavailable.code == "unsupported_request"
    assert not target.exists()


def test_serializes_nested_non_json_duckdb_values(tmp_path: Path) -> None:
    path = tmp_path / "types.duckdb"
    con = duckdb.connect(str(path))
    try:
        con.execute(
            "CREATE TABLE rows (amount DECIMAL(10,2), instant TIMESTAMP, identifier UUID, payload BLOB, metadata JSON)"
        )
        con.execute(
            "INSERT INTO rows VALUES (?, ?, ?, ?, ?)",
            [
                Decimal("1.25"),
                datetime(2024, 1, 2, 3, 4, 5),  # noqa: DTZ001 - DuckDB contract stores UTC-naive timestamps.
                UUID("12345678-1234-5678-1234-567812345678"),
                b"ok",
                '{"nested":[1,true]}',
            ],
        )
        con.execute("CREATE VIEW mn_summary AS SELECT * FROM rows")
    finally:
        con.close()

    result = _execute(MinnesotaSqlExecutor(path, [_view()]), "SELECT * FROM mn_summary")

    assert result.status == "available"
    assert result.rows == [
        [
            "1.25",
            "2024-01-02T03:04:05Z",
            "12345678-1234-5678-1234-567812345678",
            "b2s=",
            {"nested": [1, True]},
        ]
    ]


def test_read_only_execution_does_not_change_database(db_path: Path) -> None:
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    result = _execute(
        MinnesotaSqlExecutor(db_path, [_view()]),
        "SELECT count(*) AS row_count FROM mn_summary",
    )

    assert result.status == "available"
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_timeout_interrupts_the_per_request_connection_and_closes_it(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation has a bounded response even while DuckDB work is running."""

    class Cursor:
        def __init__(self, rows: list[tuple[object, ...]]) -> None:
            self.rows = rows
            self.description = [("value", "INTEGER")]

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.rows

        def fetchone(self) -> tuple[object, ...] | None:
            return self.rows[0] if self.rows else None

    class BlockingConnection:
        def __init__(self) -> None:
            self.interrupted = threading.Event()
            self.closed = False

        def execute(self, statement: str, _parameters: object = None) -> Cursor:
            if "duckdb_functions" in statement:
                return Cursor([])
            if "duckdb_views" in statement:
                return Cursor([("mn_summary",)])
            if statement.startswith("SELECT 1 FROM"):
                return Cursor([(1,)])
            self.interrupted.wait(1)
            raise RuntimeError("interrupted")

        def interrupt(self) -> None:
            self.interrupted.set()

        def close(self) -> None:
            self.closed = True

    connection = BlockingConnection()
    connect_kwargs: dict[str, object] = {}

    def connect(*_args: object, **kwargs: object) -> BlockingConnection:
        connect_kwargs.update(kwargs)
        return connection

    monkeypatch.setattr("copilot.tools.sql.duckdb.connect", connect)

    result = _execute(
        MinnesotaSqlExecutor(db_path, [_view()], timeout_seconds=0.01),
        "SELECT * FROM mn_summary",
    )

    assert result.status == "unavailable"
    assert result.unavailable is not None
    assert "time limit" in result.unavailable.reason
    assert connection.interrupted.is_set()
    assert connection.closed is True
    assert connect_kwargs["read_only"] is True
    assert connect_kwargs["config"] == {
        "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false",
        "enable_external_access": "false",
    }

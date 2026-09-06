"""Fail-closed, bounded SQL reads for accepted Minnesota artifacts.

The model-facing SQL contract deliberately has only a query string.  Deployment
code supplies the separate, trusted list of Minnesota views and their evidence;
this module never discovers tables or turns the ``mn_*`` storage relations into
an allowlist.  Until an artifact publisher registers views, calls therefore
return the normal unavailable result.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb

from copilot.tools.schemas import (
    ArtifactRef,
    JsonValue,
    SqlData,
    SqlInput,
    UnavailableOutput,
    unavailable_output,
)

ROW_LIMIT = 200
_FETCH_LIMIT = ROW_LIMIT + 1
DEFAULT_TIMEOUT_SECONDS = 5.0
_CLEANUP_SECONDS = 1.0

_FORBIDDEN_FUNCTIONS = frozenset(
    {
        "current_database",
        "current_schema",
        "current_setting",
        "getvariable",
        "glob",
        "query",
        "query_table",
        "setvariable",
        "sniff_csv",
        "union_by_name",
    }
)
_FORBIDDEN_FUNCTION_PREFIXES = (
    "azure_",
    "delta_",
    "duckdb_",
    "gcs_",
    "http_",
    "iceberg_",
    "mysql_",
    "parquet_",
    "postgres_",
    "pragma_",
    "read_",
    "s3_",
    "sqlite_",
)


class SqlRejected(ValueError):
    """The submitted statement is outside the bounded SQL surface."""


@dataclass(frozen=True)
class ApprovedMinnesotaView:
    """A deployment-owned, evidence-bearing local view available to SQL reads."""

    name: str
    provenance: tuple[ArtifactRef, ...]

    def __post_init__(self) -> None:
        if not _is_safe_view_name(self.name) or not self.name.startswith("mn_"):
            raise ValueError(
                "approved Minnesota views must use a simple mn_ local name"
            )
        if not self.provenance:
            raise ValueError("approved Minnesota views require artifact provenance")


def _is_safe_view_name(value: str) -> bool:
    return (
        bool(value)
        and (value[0].isalpha() or value[0] == "_")
        and all(character.isalnum() or character == "_" for character in value)
    )


def _serialized_statement(query: str) -> tuple[str, list[object]]:
    """Ask DuckDB to parse and normalize one statement without binding it."""

    try:
        statements = duckdb.extract_statements(query)
    except duckdb.ParserException as error:
        raise SqlRejected("query is not valid DuckDB SQL") from error
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise SqlRejected("only one SELECT statement is permitted")
    if statements[0].named_parameters:
        raise SqlRejected(
            "SQL parameters are not available in the fixed query-only tool contract"
        )
    try:
        serialized = duckdb.sql(
            "SELECT json_serialize_sql(?)", params=[statements[0].query]
        ).fetchone()[0]
        sql = duckdb.sql(
            "SELECT json_deserialize_sql(?)", params=[serialized]
        ).fetchone()[0]
    except (duckdb.Error, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SqlRejected("query is not valid DuckDB SQL") from error
    try:
        document = json.loads(serialized)
        statement_nodes = document["statements"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise SqlRejected("query parser result is unavailable") from error
    if document.get("error") or not isinstance(statement_nodes, list):
        raise SqlRejected("query is not valid DuckDB SQL")
    return str(sql), statement_nodes


def _validate_statement(
    query: str, allowed_views: set[str]
) -> tuple[str, set[str], set[str]]:
    sql, nodes = _serialized_statement(query)
    relations: set[str] = set()
    function_calls: set[str] = set()

    def validate_relation(node: object, ctes: set[str]) -> None:
        if not isinstance(node, dict):
            raise SqlRejected("query contains an invalid relation")
        node_type = node.get("type")
        if node_type == "BASE_TABLE":
            if node.get("catalog_name") or node.get("schema_name"):
                raise SqlRejected("schema-qualified relations are not permitted")
            name = str(node.get("table_name", "")).lower()
            if name not in ctes:
                if name not in allowed_views:
                    raise SqlRejected(
                        f"relation {name!r} is not an approved Minnesota view"
                    )
                relations.add(name)
            return
        if node_type == "JOIN":
            if "left" not in node or "right" not in node:
                raise SqlRejected("query contains an invalid join")
            validate_relation(node["left"], ctes)
            validate_relation(node["right"], ctes)
            for key, child in node.items():
                if key not in {"left", "right"}:
                    validate(child, ctes)
            return
        if node_type == "SUBQUERY":
            if "subquery" not in node:
                raise SqlRejected("query contains an invalid subquery relation")
            validate(node["subquery"], ctes)
            return
        if node_type == "EMPTY":
            return
        if node_type == "TABLE_FUNCTION":
            raise SqlRejected("table functions and macros are not permitted")
        raise SqlRejected(f"relation node {node_type!r} is not permitted")

    def validate_select(node: dict[str, object], outer_ctes: set[str]) -> None:
        cte_map = node.get("cte_map")
        entries = cte_map.get("map") if isinstance(cte_map, dict) else None
        if not isinstance(entries, list):
            raise SqlRejected("query contains an invalid CTE map")
        visible_ctes = outer_ctes.copy()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
                raise SqlRejected("query contains an invalid CTE")
            value = entry.get("value")
            if not isinstance(value, dict) or "query" not in value:
                raise SqlRejected("query contains an invalid CTE")
            # A CTE can use outer and preceding CTEs; adding its own name only
            # afterwards preserves lexical scope and rejects recursive CTEs.
            validate(value["query"], visible_ctes)
            visible_ctes.add(entry["key"].lower())
        for key, child in node.items():
            if key == "cte_map":
                continue
            if key == "from_table":
                validate_relation(child, visible_ctes)
            else:
                validate(child, visible_ctes)

    def validate(node: object, ctes: set[str]) -> None:
        if isinstance(node, list):
            for child in node:
                validate(child, ctes)
            return
        if not isinstance(node, dict):
            return
        node_type = node.get("type")
        if node_type == "SELECT_NODE":
            validate_select(node, ctes)
            return
        if node_type == "RECURSIVE_CTE_NODE":
            raise SqlRejected("recursive CTEs are not permitted")
        if (
            "class" not in node
            and isinstance(node_type, str)
            and node_type in {
            "BASE_TABLE",
            "JOIN",
            "SUBQUERY",
            "TABLE_FUNCTION",
            "EMPTY",
            }
        ):
            raise SqlRejected("query contains a relation outside FROM or JOIN")
        if node.get("class") == "FUNCTION":
            name = str(node.get("function_name", "")).lower()
            if not name:
                raise SqlRejected("unnamed function is not permitted")
            if name in _FORBIDDEN_FUNCTIONS or name.startswith(
                _FORBIDDEN_FUNCTION_PREFIXES
            ):
                raise SqlRejected(f"function {name!r} is not permitted")
            function_calls.add(name)
        for child in node.values():
            validate(child, ctes)

    validate(nodes, set())
    if not relations:
        raise SqlRejected("query must read at least one approved Minnesota view")
    return sql, relations, function_calls


def _quote_identifier(name: str) -> str:
    # View names are checked at construction and never come from the submitted SQL.
    return f'"{name}"'


def _json_value(value: Any, *, json_column: bool = False) -> JsonValue:
    if json_column and isinstance(value, str):
        return _json_value(json.loads(value))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite values cannot be returned by SQL")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return f"{value.isoformat()}Z"
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, (date, time, UUID)):
        return value.isoformat() if not isinstance(value, UUID) else str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise ValueError(f"SQL returned unsupported value type {type(value).__name__}")


class MinnesotaSqlExecutor:
    """Execute one validated SELECT against deployment-registered local views."""

    def __init__(
        self,
        database_path: Path | str,
        approved_views: Iterable[ApprovedMinnesotaView] = (),
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._database_path = Path(database_path)
        self._views = {view.name: view for view in approved_views}
        self._timeout_seconds = timeout_seconds
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def _unavailable(self, code: str, reason: str) -> UnavailableOutput:
        return unavailable_output(code, reason)  # type: ignore[arg-type]

    def _available_local_views(self, connection: duckdb.DuckDBPyConnection) -> set[str]:
        rows = connection.execute(
            "SELECT view_name FROM duckdb_views() WHERE database_name = current_database() AND schema_name = ?",
            ["main"],
        ).fetchall()
        return {str(row[0]).lower() for row in rows}

    def _registered_macro_names(
        self, connection: duckdb.DuckDBPyConnection
    ) -> set[str]:
        """Read the trusted catalog before user SQL can expand a stored macro."""

        rows = connection.execute(
            "SELECT function_name FROM duckdb_functions() WHERE function_type IN (?, ?)",
            ["macro", "table_macro"],
        ).fetchall()
        return {str(row[0]).lower() for row in rows}

    def _run(
        self, connection: duckdb.DuckDBPyConnection, sql: str, relations: set[str]
    ) -> tuple[list[str], list[list[JsonValue]], bool]:
        try:
            present_views = self._available_local_views(connection)
            missing = sorted(relations - present_views)
            if missing:
                raise LookupError(
                    f"approved view is not provisioned locally: {', '.join(missing)}"
                )
            for view_name in relations:
                exists = connection.execute(
                    f"SELECT 1 FROM {_quote_identifier(view_name)} LIMIT ?",
                    [_FETCH_LIMIT],
                ).fetchone()
                if exists is None:
                    raise LookupError(f"accepted artifact view is empty: {view_name}")
            cursor = connection.execute(
                f"SELECT * FROM ({sql}) AS bounded_minnesota_sql LIMIT ?",
                [_FETCH_LIMIT],
            )
            columns = [column[0] for column in cursor.description]
            json_columns = [
                str(column[1]).upper() == "JSON" for column in cursor.description
            ]
            fetched = cursor.fetchall()
            truncated = len(fetched) > ROW_LIMIT
            rows = [
                [
                    _json_value(value, json_column=json_columns[column])
                    for column, value in enumerate(row)
                ]
                for row in fetched[:ROW_LIMIT]
            ]
            return columns, rows, truncated
        finally:
            connection.close()

    async def execute(self, request: SqlInput | str) -> SqlData | UnavailableOutput:
        """Return a bounded result or an explicit unavailable envelope.

        The generated row limit is a bound parameter.  The caller never gets a
        parameter dictionary because the public ``SqlInput`` contract has only
        ``query``; submitted placeholders are rejected instead of guessed.
        """

        try:
            query = (
                request.query
                if isinstance(request, SqlInput)
                else SqlInput(query=request).query
            )
        except Exception:  # noqa: BLE001 - Pydantic is the public input boundary.
            return self._unavailable(
                "unsupported_request", "SQL query is outside the fixed input contract"
            )
        if not self._database_path.is_file():
            return self._unavailable(
                "artifact_unavailable",
                "Minnesota SQL artifact database is not available locally",
            )
        if not self._views:
            return self._unavailable(
                "artifact_unavailable",
                "no approved Minnesota SQL views are provisioned",
            )
        try:
            sql, relations, function_calls = _validate_statement(
                query, set(self._views)
            )
        except SqlRejected as error:
            return self._unavailable("unsupported_request", str(error))
        try:
            # A connection per request keeps cancellation isolated.  Opening
            # read-only never creates a missing database (checked above).
            connection = duckdb.connect(
                str(self._database_path),
                read_only=True,
                config={
                    "autoinstall_known_extensions": "false",
                    "autoload_known_extensions": "false",
                    "enable_external_access": "false",
                },
            )
        except Exception:  # noqa: BLE001 - driver errors must not expose local paths.
            return self._unavailable(
                "artifact_unavailable",
                "Minnesota SQL artifact cannot be opened read-only",
            )
        try:
            macro_calls = function_calls & self._registered_macro_names(connection)
        except Exception:  # noqa: BLE001 - a partial catalog cannot authorize execution.
            connection.close()
            return self._unavailable(
                "artifact_unavailable",
                "Minnesota SQL artifact catalog is not available locally",
            )
        if macro_calls:
            connection.close()
            return self._unavailable(
                "unsupported_request",
                "stored SQL macros are not permitted",
            )
        task = asyncio.create_task(
            asyncio.to_thread(self._run, connection, sql, relations)
        )
        try:
            columns, rows, truncated = await asyncio.wait_for(
                asyncio.shield(task), self._timeout_seconds
            )
        except TimeoutError:
            # DuckDB has no statement timeout.  Interrupt its per-request
            # connection, then bound the wait for the worker's ``finally``
            # close so a failed driver cannot retain the API response.
            connection.interrupt()
            try:
                await asyncio.wait_for(asyncio.shield(task), _CLEANUP_SECONDS)
            except (TimeoutError, duckdb.Error, RuntimeError, ValueError):
                # The worker still owns the connection and closes it on exit.
                pass
            return self._unavailable(
                "unsupported_request", "SQL query exceeded the execution time limit"
            )
        except LookupError as error:
            return self._unavailable("artifact_unavailable", str(error))
        except Exception:  # noqa: BLE001 - never return catalog or filesystem details to the model.
            return self._unavailable(
                "unsupported_request", "SQL query could not be executed"
            )
        provenance: list[ArtifactRef] = []
        for relation in sorted(relations):
            for artifact in self._views[relation].provenance:
                if artifact not in provenance:
                    provenance.append(artifact)
        return SqlData(
            status="available",
            provenance=provenance,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
        )

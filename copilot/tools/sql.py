"""Fail-closed, bounded SQL reads for accepted Minnesota artifacts.

The model-facing contract accepts either a legacy query string or an approved
deployment template id. Deployment code supplies the trusted list of Minnesota
views, evidence, and optional fixed templates; this module never discovers
tables or turns the ``mn_*`` storage relations into an allowlist. Until an
artifact publisher registers views, calls therefore return the normal
unavailable result.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from time import monotonic
from typing import Any, Literal
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
_EXECUTION_LOGGER = logging.getLogger("copilot.sql")

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
class SqlExecutionRecord:
    """Bound-safe operational record; it deliberately omits SQL and values."""

    template_id: str | None
    parameter_count: int | None
    row_count: int | None
    duration_ms: int
    provenance_artifact_ids: tuple[str, ...]
    outcome: Literal["available", "unavailable"]


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


def _is_template_id(value: str) -> bool:
    """Match the public ``SqlInput.template_id`` ASCII identifier contract."""
    return (
        bool(value)
        and len(value) <= 64
        and "a" <= value[0] <= "z"
        and all(
            "a" <= character <= "z" or "0" <= character <= "9" or character == "_"
            for character in value
        )
    )


def _bound_parameters(value: object) -> list[str | int | float | bool | None] | None:
    """Return only the finite, bounded scalar list the public model accepts."""

    if not isinstance(value, list) or len(value) > 25:
        return None
    for parameter in value:
        if parameter is None or isinstance(parameter, (str, bool, int)):
            continue
        if isinstance(parameter, float) and math.isfinite(parameter):
            continue
        return None
    return value


def _positional_placeholder_count(query: str) -> int:
    """Count only ``?`` tokens outside SQL literals and comments.

    Deployment templates may use DuckDB's positional form only.  The scanner is
    deliberately narrow: dollar parameters are rejected even when their AST
    identifiers look numeric, so a template cannot introduce a second binding
    syntax.
    """

    index = 0
    count = 0
    while index < len(query):
        if query.startswith("--", index):
            newline = query.find("\n", index + 2)
            index = len(query) if newline < 0 else newline + 1
        elif query.startswith("/*", index):
            end = query.find("*/", index + 2)
            index = len(query) if end < 0 else end + 2
        elif query[index] in "'\"":
            quote = query[index]
            index += 1
            while index < len(query):
                if query[index] == quote:
                    if index + 1 < len(query) and query[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
        elif query[index] == "?":
            count += 1
            index += 1
        elif query[index] == "$" and re.match(r"\$[A-Za-z0-9_]", query[index:]):
            raise SqlRejected("only positional ? SQL parameters are permitted")
        else:
            index += 1
    return count


def _serialized_statement(
    query: str, *, allow_positional_parameters: bool = False
) -> tuple[str, list[object], int]:
    """Ask DuckDB to parse and normalize one statement without binding it."""

    try:
        statements = duckdb.extract_statements(query)
    except duckdb.ParserException as error:
        raise SqlRejected("query is not valid DuckDB SQL") from error
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise SqlRejected("only one SELECT statement is permitted")
    placeholder_count = _positional_placeholder_count(query)
    expected_parameters = {str(index) for index in range(1, placeholder_count + 1)}
    if statements[0].named_parameters != expected_parameters:
        raise SqlRejected("SQL parameters are not available in the fixed tool contract")
    if placeholder_count and not allow_positional_parameters:
        raise SqlRejected("SQL parameters are not available in the fixed tool contract")
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
    return str(sql), statement_nodes, placeholder_count


def _validate_statement(
    query: str, allowed_views: set[str], *, allow_positional_parameters: bool = False
) -> tuple[str, set[str], set[str], int]:
    sql, nodes, placeholder_count = _serialized_statement(
        query, allow_positional_parameters=allow_positional_parameters
    )
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
            and node_type
            in {
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
    return sql, relations, function_calls, placeholder_count


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


@dataclass(frozen=True)
class ApprovedMinnesotaQuery:
    """A named deployment query with its complete relation declaration."""

    name: str
    sql: str
    relations: frozenset[str]
    parameter_count: int = field(init=False)

    def __post_init__(self) -> None:
        if not _is_template_id(self.name):
            raise ValueError("approved query names must match the template_id contract")
        if not self.relations or any(
            not _is_safe_view_name(name) for name in self.relations
        ):
            raise ValueError("approved queries require declared simple relations")
        object.__setattr__(
            self,
            "parameter_count",
            _serialized_statement(self.sql, allow_positional_parameters=True)[2],
        )


class MinnesotaSqlExecutor:
    """Execute one validated SELECT against deployment-registered local views."""

    def __init__(
        self,
        database_path: Path | str,
        approved_views: Iterable[ApprovedMinnesotaView] = (),
        approved_queries: Iterable[ApprovedMinnesotaQuery] = (),
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        execution_logger: Callable[[SqlExecutionRecord], None] | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._views = {view.name: view for view in approved_views}
        registered_queries = tuple(approved_queries)
        self._queries = {query.name: query for query in registered_queries}
        if len(self._queries) != len(registered_queries):
            raise ValueError("approved query names must be unique")
        for query in self._queries.values():
            if not query.relations <= set(self._views):
                raise ValueError("approved query relation is not an approved view")
            _, relations, _, parameter_count = _validate_statement(
                query.sql, set(self._views), allow_positional_parameters=True
            )
            if parameter_count != query.parameter_count:
                raise ValueError("approved query placeholder count is inconsistent")
            if relations != set(query.relations):
                raise ValueError(
                    "approved query relation declaration does not match SQL"
                )
        self._timeout_seconds = timeout_seconds
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._execution_logger = execution_logger

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
        self,
        connection: duckdb.DuckDBPyConnection,
        sql: str,
        relations: set[str],
        parameters: list[str | int | float | bool | None],
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
                [*parameters, _FETCH_LIMIT],
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
        """Execute once and emit a best-effort bound-safe operational record."""

        started = monotonic()
        result = await self._execute(request)
        payload = request if isinstance(request, SqlInput) else None
        parameter_count = (
            len(payload.parameters)
            if isinstance(getattr(payload, "parameters", None), list)
            else None
        )
        record = SqlExecutionRecord(
            template_id=getattr(payload, "template_id", None),
            parameter_count=parameter_count,
            row_count=result.row_count if isinstance(result, SqlData) else None,
            duration_ms=max(0, round((monotonic() - started) * 1000)),
            provenance_artifact_ids=tuple(
                item.artifact_id for item in result.provenance
            ),
            outcome=result.status,
        )
        _EXECUTION_LOGGER.info("sql_execution %s", record)
        if self._execution_logger is not None:
            try:
                self._execution_logger(record)
            except Exception:  # noqa: BLE001 - observability cannot change tool output.
                return result
        return result

    async def _execute(self, request: SqlInput | str) -> SqlData | UnavailableOutput:
        """Return a bounded result or an explicit unavailable envelope.

        Only a deployment-owned template may contain positional ``?`` markers.
        Values are passed separately to DuckDB; legacy query text retains the
        no-placeholder rule.
        """

        try:
            payload = (
                request if isinstance(request, SqlInput) else SqlInput(query=request)
            )
        except Exception:  # noqa: BLE001 - Pydantic is the public input boundary.
            return self._unavailable(
                "unsupported_request", "SQL query is outside the fixed input contract"
            )
        # ``SqlInput`` already enforces exactly one of ``query``/``template_id``;
        # this guard keeps the executor fail-closed if a caller bypasses it.
        if (payload.query is None) == (payload.template_id is None):
            return self._unavailable(
                "unsupported_request",
                "SQL accepts exactly one of query or template_id",
            )
        parameters = _bound_parameters(getattr(payload, "parameters", None))
        if parameters is None:
            return self._unavailable(
                "unsupported_request",
                "SQL parameters must be bounded finite JSON scalars",
            )
        if self._queries:
            if payload.template_id is None:
                return self._unavailable(
                    "unsupported_request", "SQL requires one registered template_id"
                )
            template = self._queries.get(payload.template_id)
            if template is None:
                return self._unavailable(
                    "unsupported_request", "SQL template is not registered"
                )
            query = template.sql
            if len(parameters) != template.parameter_count:
                return self._unavailable(
                    "unsupported_request", "SQL template parameter count does not match"
                )
        elif payload.template_id is not None:
            return self._unavailable(
                "unsupported_request",
                "SQL template registry is not configured for this deployment",
            )
        else:
            assert payload.query is not None
            query = payload.query
            if parameters:
                return self._unavailable(
                    "unsupported_request",
                    "SQL parameters require a registered template",
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
            sql, relations, function_calls, placeholder_count = _validate_statement(
                query,
                set(self._views),
                allow_positional_parameters=bool(self._queries),
            )
        except SqlRejected as error:
            return self._unavailable("unsupported_request", str(error))
        if placeholder_count != len(parameters):
            return self._unavailable(
                "unsupported_request", "SQL template parameter count does not match"
            )
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
            asyncio.to_thread(self._run, connection, sql, relations, parameters)
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

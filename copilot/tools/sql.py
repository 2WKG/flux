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

_FORBIDDEN_TOKENS = frozenset(
    {
        "alter",
        "attach",
        "call",
        "copy",
        "create",
        "delete",
        "detach",
        "drop",
        "export",
        "import",
        "insert",
        "install",
        "load",
        "merge",
        "pragma",
        "prepare",
        "set",
        "transaction",
        "update",
        "vacuum",
    }
)
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
class _Token:
    kind: str
    value: str


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


def _tokens(sql: str) -> list[_Token]:
    """Tokenize SQL while discarding comments and preserving quoted literals.

    DuckDB remains the statement parser.  This small lexer is solely for the
    relation/function policy, so strings and comments cannot spoof a keyword
    check and quoted identifiers remain identifiers rather than raw text.
    """

    result: list[_Token] = []
    index = 0
    size = len(sql)
    while index < size:
        character = sql[index]
        if character.isspace():
            index += 1
        elif sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            index = size if newline == -1 else newline + 1
        elif sql.startswith("/*", index):
            depth = 1
            index += 2
            while index < size and depth:
                if sql.startswith("/*", index):
                    depth += 1
                    index += 2
                elif sql.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
            if depth:
                raise SqlRejected("unterminated block comment")
        elif character == "'":
            index += 1
            closed = False
            while index < size:
                if sql[index] == "'":
                    if index + 1 < size and sql[index + 1] == "'":
                        index += 2
                    else:
                        index += 1
                        closed = True
                        break
                else:
                    index += 1
            if not closed:
                raise SqlRejected("unterminated string literal")
            result.append(_Token("literal", ""))
        elif character == '"':
            index += 1
            content: list[str] = []
            while index < size:
                if sql[index] == '"':
                    if index + 1 < size and sql[index + 1] == '"':
                        content.append('"')
                        index += 2
                    else:
                        index += 1
                        break
                else:
                    content.append(sql[index])
                    index += 1
            else:
                raise SqlRejected("unterminated quoted identifier")
            result.append(_Token("quoted_identifier", "".join(content).lower()))
        elif character.isalpha() or character == "_":
            end = index + 1
            while end < size and (sql[end].isalnum() or sql[end] in "_$"):
                end += 1
            result.append(_Token("identifier", sql[index:end].lower()))
            index = end
        elif character.isdigit():
            end = index + 1
            while end < size and (sql[end].isalnum() or sql[end] in "._"):
                end += 1
            result.append(_Token("literal", ""))
            index = end
        else:
            result.append(_Token("symbol", character))
            index += 1
    return result


def _matching_paren(tokens: list[_Token], start: int) -> int:
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index].value == "(":
            depth += 1
        elif tokens[index].value == ")":
            depth -= 1
            if depth == 0:
                return index
    raise SqlRejected("unbalanced parentheses")


def _looks_like_cte(tokens: list[_Token], index: int) -> bool:
    if index >= len(tokens) or tokens[index].kind not in {
        "identifier",
        "quoted_identifier",
    }:
        return False
    index += 1
    if index < len(tokens) and tokens[index].value == "(":
        index = _matching_paren(tokens, index) + 1
    return index < len(tokens) and tokens[index].value == "as"


def _validate_functions(tokens: list[_Token]) -> None:
    for name in _function_calls(tokens):
        if name in _FORBIDDEN_FUNCTIONS or name.startswith(
            _FORBIDDEN_FUNCTION_PREFIXES
        ):
            raise SqlRejected(f"function {name!r} is not permitted")


def _function_calls(tokens: list[_Token]) -> set[str]:
    """Return unquoted call names for the post-parse macro policy."""

    return {
        token.value
        for index, token in enumerate(tokens[:-1])
        if token.kind in {"identifier", "quoted_identifier"}
        and tokens[index + 1].value == "("
    }


def _parse_source(
    tokens: list[_Token],
    index: int,
    ctes: set[str],
    allowed_views: set[str],
    relations: set[str],
) -> int:
    if index < len(tokens) and tokens[index].value in {"lateral", "only", "table"}:
        raise SqlRejected("only direct approved local views may appear in FROM or JOIN")
    if index >= len(tokens):
        raise SqlRejected("FROM or JOIN is missing a relation")
    if tokens[index].value == "(":
        end = _matching_paren(tokens, index)
        _validate_query_tokens(
            tokens[index + 1 : end], ctes.copy(), allowed_views, relations
        )
        return end + 1
    if tokens[index].kind not in {"identifier", "quoted_identifier"}:
        raise SqlRejected("FROM or JOIN must name an approved local view")
    name = tokens[index].value
    index += 1
    if index < len(tokens) and tokens[index].value == ".":
        raise SqlRejected("schema-qualified relations are not permitted")
    if index < len(tokens) and tokens[index].value == "(":
        raise SqlRejected("table functions and macros are not permitted")
    if name in ctes:
        return index
    if name not in allowed_views:
        raise SqlRejected(f"relation {name!r} is not an approved Minnesota view")
    relations.add(name)
    return index


_FROM_END = frozenset(
    {
        "where",
        "group",
        "having",
        "order",
        "limit",
        "offset",
        "qualify",
        "window",
        "union",
        "except",
        "intersect",
        "returning",
    }
)


def _validate_query_tokens(
    tokens: list[_Token], ctes: set[str], allowed_views: set[str], relations: set[str]
) -> None:
    if not tokens:
        raise SqlRejected("query is empty")
    start = 0
    if tokens[0].value == "with":
        start = 1
        if start < len(tokens) and tokens[start].value == "recursive":
            start += 1
        while _looks_like_cte(tokens, start):
            alias = tokens[start].value
            ctes.add(alias)
            start += 1
            if start < len(tokens) and tokens[start].value == "(":
                start = _matching_paren(tokens, start) + 1
            if start >= len(tokens) or tokens[start].value != "as":
                raise SqlRejected("CTE is missing AS")
            start += 1
            if start >= len(tokens) or tokens[start].value != "(":
                raise SqlRejected("CTE is missing its query")
            end = _matching_paren(tokens, start)
            _validate_query_tokens(
                tokens[start + 1 : end], ctes.copy(), allowed_views, relations
            )
            start = end + 1
            if (
                start < len(tokens)
                and tokens[start].value == ","
                and _looks_like_cte(tokens, start + 1)
            ):
                start += 1
                continue
            break
    if start >= len(tokens) or tokens[start].value != "select":
        raise SqlRejected("only SELECT or WITH ... SELECT statements are permitted")

    index = start
    while index < len(tokens):
        if tokens[index].value == "(":
            end = _matching_paren(tokens, index)
            if index + 1 < end and tokens[index + 1].value in {"select", "with"}:
                _validate_query_tokens(
                    tokens[index + 1 : end], ctes.copy(), allowed_views, relations
                )
            index = end + 1
            continue
        if tokens[index].value in {"from", "join"}:
            index = _parse_source(tokens, index + 1, ctes, allowed_views, relations)
            while index < len(tokens):
                value = tokens[index].value
                if value in _FROM_END:
                    break
                if value == "join" or value == ",":
                    index = _parse_source(
                        tokens, index + 1, ctes, allowed_views, relations
                    )
                elif value == "(":
                    # A parenthesized expression in an ON clause may contain a
                    # scalar subquery; validate it before skipping it.
                    end = _matching_paren(tokens, index)
                    if index + 1 < end and tokens[index + 1].value in {
                        "select",
                        "with",
                    }:
                        _validate_query_tokens(
                            tokens[index + 1 : end],
                            ctes.copy(),
                            allowed_views,
                            relations,
                        )
                    index = end + 1
                else:
                    index += 1
            continue
        index += 1


def _validate_statement(
    query: str, allowed_views: set[str]
) -> tuple[str, set[str], set[str]]:
    tokens = _tokens(query)
    semicolons = [index for index, token in enumerate(tokens) if token.value == ";"]
    if len(semicolons) > 1 or (semicolons and semicolons[0] != len(tokens) - 1):
        raise SqlRejected("only one optional trailing semicolon is permitted")
    if semicolons:
        tokens.pop()
    if not tokens:
        raise SqlRejected("query is empty")
    if tokens[0].value not in {"select", "with"}:
        raise SqlRejected("only SELECT or WITH ... SELECT statements are permitted")
    forbidden = next(
        (
            token.value
            for token in tokens
            if token.kind == "identifier" and token.value in _FORBIDDEN_TOKENS
        ),
        None,
    )
    if forbidden:
        raise SqlRejected(f"keyword {forbidden!r} is not permitted")
    _validate_functions(tokens)
    try:
        statements = duckdb.extract_statements(query)
    except duckdb.ParserException as error:
        raise SqlRejected("query is not valid DuckDB SQL") from error
    if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
        raise SqlRejected("only one SELECT statement is permitted")
    if statements[0].named_parameters or any(token.value == "?" for token in tokens):
        raise SqlRejected(
            "SQL parameters are not available in the fixed query-only tool contract"
        )
    relations: set[str] = set()
    _validate_query_tokens(tokens, set(), allowed_views, relations)
    if not relations:
        raise SqlRejected("query must read at least one approved Minnesota view")
    return (
        _remove_trailing_terminator(statements[0].query),
        relations,
        _function_calls(tokens),
    )


def _remove_trailing_terminator(query: str) -> str:
    """Remove the one validated terminator without touching literal semicolons."""

    index = 0
    while index < len(query):
        if query.startswith("--", index):
            newline = query.find("\n", index + 2)
            index = len(query) if newline == -1 else newline + 1
        elif query.startswith("/*", index):
            end = query.find("*/", index + 2)
            if end == -1:
                raise SqlRejected("unterminated block comment")
            index = end + 2
        elif query[index] == "'":
            index += 1
            while index < len(query):
                if query[index] == "'":
                    if index + 1 < len(query) and query[index + 1] == "'":
                        index += 2
                        continue
                    else:
                        index += 1
                        break
                index += 1
        elif query[index] == '"':
            index += 1
            while index < len(query):
                if query[index] == '"':
                    if index + 1 < len(query) and query[index + 1] == '"':
                        index += 2
                        continue
                    else:
                        index += 1
                        break
                index += 1
        elif query[index] == ";":
            return query[:index].rstrip()
        else:
            index += 1
    return query.rstrip()


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

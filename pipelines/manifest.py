"""Reproducible artifact manifest: schema version, row counts, and row digests.

The manifest is written next to the Parquet export and stored in
``schema_meta`` so downstream consumers can tell which curated release they
are reading. Two builds of the same rows produce byte-identical manifests:

* there is no wall-clock field (the DuckDB ``ingest_log`` already records
  ``loaded_at`` per source file);
* rows are digested in primary-key order using the DDL's full, possibly
  composite, key, so insertion order does not matter;
* every value is encoded with its Python type, so ``1`` and ``"1"`` differ.

``content_sha256`` is a digest of the PK-ordered row projection of each
contract table. It is NOT a digest of the Parquet bytes: DuckDB writes
Parquet in physical insertion order, so those bytes are not reproducible
across builds. ``digest_method`` in the manifest says so explicitly.

A contract table that is missing from the database is an error, never an
omission: the manifest is only authoritative if it covers the whole contract.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipelines.db import CONTRACT_TABLES, SCHEMA_VERSION

DIGEST_METHOD = "sha256(pk-ordered typed row projection); not the Parquet bytes"
_BATCH_ROWS = 10_000

SYNTHETIC_TABLES = frozenset({"buses", "lines", "gens", "loads"})
REAL_TABLES = frozenset(CONTRACT_TABLES) - SYNTHETIC_TABLES


class ManifestError(RuntimeError):
    """The database cannot be described by an authoritative manifest."""


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _table_exists(con, table: str) -> bool:
    return bool(
        con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [table],
        ).fetchone()[0]
    )


def _primary_key(con, table: str) -> tuple[str, ...]:
    """Return the table's declared primary-key columns, in DDL order."""
    row = con.execute(
        """SELECT constraint_column_names FROM duckdb_constraints()
           WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'""",
        [table],
    ).fetchone()
    if row is None or not row[0]:
        raise ManifestError(f"contract table {table!r} declares no primary key")
    return tuple(row[0])


def _encode(value) -> list | None:
    """Type-preserving canonical encoding of one cell."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ["bytes", bytes(value).hex()]
    if isinstance(value, float):
        return ["float", repr(value)]
    if isinstance(value, bool):
        return ["bool", str(value)]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, str):
        return ["str", value]
    return [type(value).__name__, str(value)]


def _table_sha256(con, table: str, primary_key: tuple[str, ...]) -> str:
    """Digest every row of ``table`` in primary-key order.

    Ordering by the complete primary key is a total order, so the digest is
    independent of insertion order. Rows are streamed in batches so hourly
    tables are never materialised in Python all at once.
    """
    order = ", ".join(_quote(column) for column in primary_key)
    digest = hashlib.sha256()
    cursor = con.execute(f"SELECT * FROM {_quote(table)} ORDER BY {order}")
    while rows := cursor.fetchmany(_BATCH_ROWS):
        for row in rows:
            digest.update(
                json.dumps(
                    [_encode(value) for value in row],
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            digest.update(b"\n")
    return digest.hexdigest()


def build_manifest(con, *, state_scope: str) -> dict:
    """Describe every contract table in the current database state.

    Raises ``ManifestError`` when a contract table is absent or has no primary
    key; a partial manifest would misrepresent the release.
    """
    tables: dict[str, dict] = {}
    for table in CONTRACT_TABLES:
        if not _table_exists(con, table):
            raise ManifestError(
                f"contract table {table!r} is missing; the release is incomplete"
            )
        primary_key = _primary_key(con, table)
        row_count = con.execute(f"SELECT count(*) FROM {_quote(table)}").fetchone()[0]
        tables[table] = {
            "row_count": row_count,
            "primary_key": list(primary_key),
            "content_sha256": _table_sha256(con, table, primary_key),
            "classification": "synthetic" if table in SYNTHETIC_TABLES else "real",
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "state_scope": state_scope,
        "digest_method": DIGEST_METHOD,
        "tables": tables,
    }


def write_manifest(manifest: dict, path: str | Path) -> Path:
    """Write the manifest as sorted-key JSON so identical manifests are identical files."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output


def store_manifest(con, manifest: dict) -> None:
    """Persist the manifest inside the database for self-describing artifacts."""
    con.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('manifest', ?)",
        [
            json.dumps(
                manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
        ],
    )

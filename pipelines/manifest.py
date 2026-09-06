"""Reproducible artifact manifest recording row counts, schema version, and hashes.

The manifest is the authoritative record of what was built. It is written
alongside the database and Parquet export so downstream consumers can verify
they are reading the expected artifact without opening the database.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pipelines.db import SCHEMA_VERSION, CONTRACT_TABLES, TABLE_COLUMNS


def _table_sha256(con, table: str) -> str:
    """Deterministic content hash of a contract table.

    Rows are ordered by primary key columns so the hash is stable across
    builds that insert in different orders.
    """
    columns = TABLE_COLUMNS.get(table)
    if columns is None:
        return ""
    pk = columns[0]  # first column is always the primary key in this contract
    # Hash the canonical JSON representation of every row, ordered by PK.
    digest = hashlib.sha256()
    rows = con.execute(
        f'SELECT * FROM "{table}" ORDER BY "{pk}"'
    ).fetchall()
    for row in rows:
        # Use JSON with sorted keys for deterministic hashing
        digest.update(
            json.dumps(
                [str(v) if v is not None else None for v in row],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
    return digest.hexdigest()


SYNTHETIC_TABLES = frozenset({"buses", "lines", "gens", "loads"})
REAL_TABLES = frozenset(CONTRACT_TABLES) - SYNTHETIC_TABLES


def build_manifest(
    con,
    *,
    state_scope: str,
    build_timestamp: datetime | None = None,
) -> dict:
    """Produce a reproducible artifact manifest for the current database state.

    The manifest records every contract table's row count, primary key, content
    SHA-256, and whether it is synthetic topology or real-world observation.
    """
    ts = (build_timestamp or datetime.now(UTC)).replace(tzinfo=None)
    tables: dict[str, dict] = {}
    for table in CONTRACT_TABLES:
        exists = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [table],
        ).fetchone()[0]
        if not exists:
            continue
        row_count = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        content_sha256 = _table_sha256(con, table)
        classification = "synthetic" if table in SYNTHETIC_TABLES else "real"
        columns = TABLE_COLUMNS.get(table, ())
        tables[table] = {
            "row_count": row_count,
            "primary_key": columns[0] if columns else None,
            "content_sha256": content_sha256,
            "classification": classification,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "state_scope": state_scope,
        "build_timestamp": ts.isoformat() + "Z",
        "tables": tables,
    }


def write_manifest(
    manifest: dict,
    path: str | Path,
) -> Path:
    """Write the manifest as sorted-key JSON to a file."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output


def store_manifest(
    con,
    manifest: dict,
) -> None:
    """Persist the manifest inside the database for self-describing artifacts."""
    con.execute(
        """INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('manifest', ?)""",
        [json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)],
    )
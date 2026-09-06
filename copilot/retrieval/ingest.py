"""Deterministic, citation-preserving storage for versioned local corpora.

This adapter writes only the existing Minnesota artifact and citation relations.
It deliberately accepts source documents supplied by the caller: downloading or
claiming a Minnesota corpus is outside this module's scope.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import duckdb

from copilot.retrieval.chunking import (
    CorpusChunk,
    SourceDocument,
    chunk_documents,
    serialize_chunks,
)
from pipelines.fixtures.builder import artifact_id_for
from pipelines.minnesota_schema import SCHEMA_VERSION, ensure_minnesota_schema

_GEOGRAPHY_ID = "MN"
_CORPUS_KINDS = {"source": "citation_corpus", "fixture": "citation_fixture"}


class CorpusIngestError(RuntimeError):
    """The proposed corpus conflicts with persisted evidence."""


@dataclass(frozen=True)
class IngestedCorpus:
    artifact_id: str
    chunks: tuple[CorpusChunk, ...]
    content_kind: Literal["fixture", "source"]


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CorpusIngestError("provenance retrieved_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise CorpusIngestError("provenance retrieved_at must include a UTC offset")
    return parsed.astimezone(UTC).replace(tzinfo=None)


def _provenance(document: SourceDocument) -> tuple[object, ...]:
    """Map explicit document metadata into the existing artifact provenance row."""

    metadata = document.provenance
    retrieved_at = metadata.get("retrieved_at")
    if not isinstance(retrieved_at, str):
        raise CorpusIngestError("every document provenance requires retrieved_at")
    license_or_terms = metadata.get("license_or_terms")
    if not isinstance(license_or_terms, str) or not license_or_terms:
        raise CorpusIngestError("every document provenance requires license_or_terms")
    source_name = metadata.get("source_name", document.document_id)
    if not isinstance(source_name, str) or not source_name:
        raise CorpusIngestError("provenance source_name must be a non-empty string")
    source_record_id = metadata.get("source_record_id", document.document_id)
    if source_record_id != document.document_id:
        raise CorpusIngestError("provenance source_record_id must equal document_id")
    return (
        source_name,
        document.source_uri,
        document.version,
        _utc_timestamp(retrieved_at),
        license_or_terms,
        source_record_id,
        hashlib.sha256(document.text.encode("utf-8")).hexdigest(),
        False,
    )


def _documents_by_id(documents: Iterable[SourceDocument]) -> tuple[SourceDocument, ...]:
    collected = tuple(documents)
    if not collected:
        raise CorpusIngestError("a corpus requires at least one source document")
    if any(document.page is None for document in collected):
        raise CorpusIngestError(
            "citation corpus documents require an exact positive page"
        )
    kinds = {document.content_kind for document in collected}
    if len(kinds) != 1:
        raise CorpusIngestError(
            "a corpus artifact cannot mix fixture and source documents"
        )
    seen: set[str] = set()
    for document in collected:
        if document.document_id in seen:
            raise CorpusIngestError(
                "document_id must be unique within a corpus artifact"
            )
        seen.add(document.document_id)
        _provenance(document)
    return tuple(sorted(collected, key=lambda item: item.document_id))


def _artifact_identity(
    chunks: tuple[CorpusChunk, ...], *, content_kind: str
) -> tuple[str, str]:
    content_sha256 = hashlib.sha256(serialize_chunks(chunks)).hexdigest()
    versions = sorted({chunk.version for chunk in chunks})
    identity = {
        "artifact_kind": _CORPUS_KINDS[content_kind],
        "geography_id": _GEOGRAPHY_ID,
        "model_mode": "not_applicable",
        "source_identity": "versioned-local-corpus",
        "source_version": hashlib.sha256(
            _canonical_json(versions).encode()
        ).hexdigest(),
        "content_sha256": content_sha256,
    }
    return artifact_id_for(identity), _canonical_json(identity)


def ingest_corpus(
    con: duckdb.DuckDBPyConnection,
    documents: Iterable[SourceDocument],
    *,
    created_at: datetime,
    chunk_tokens: int = 800,
    overlap_tokens: int = 150,
) -> IngestedCorpus:
    """Store one fully specified corpus idempotently in the Minnesota namespace.

    A rerun with identical source metadata and normalized text is a no-op. A
    conflicting row for the same stable identity raises before changing stored
    evidence. Repository documents are valid source documents when callers use
    their actual commit/path/date metadata; this function never relabels them
    as external observations.
    """

    if created_at.tzinfo is None:
        raise CorpusIngestError("created_at must include a UTC offset")
    docs = _documents_by_id(documents)
    chunks = tuple(
        chunk_documents(docs, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens)
    )
    content_kind = docs[0].content_kind
    artifact_id, identity_json = _artifact_identity(chunks, content_kind=content_kind)
    created = created_at.astimezone(UTC).replace(tzinfo=None)
    manifest = (
        _CORPUS_KINDS[content_kind],
        SCHEMA_VERSION,
        _GEOGRAPHY_ID,
        "available",
        "not_applicable",
        identity_json,
        created,
        _canonical_json(
            ["Local versioned citation corpus; no external dataset claim is implied."]
        ),
        _canonical_json(
            ["Corpus evidence is limited to the explicitly ingested documents."]
        ),
        _canonical_json([]),
    )
    provenance = [_provenance(document) for document in docs]

    ensure_minnesota_schema(con)
    con.execute("BEGIN")
    try:
        existing = con.execute(
            """SELECT artifact_kind, contract_version, geography_id, availability, model_mode,
            identity_json, created_at, assumptions_json, limitations_json, input_artifact_ids_json
            FROM mn_artifact_manifests WHERE artifact_id = ?""",
            [artifact_id],
        ).fetchone()
        if existing is None:
            con.execute(
                "INSERT INTO mn_artifact_manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [artifact_id, *manifest],
            )
        elif existing != manifest:
            raise CorpusIngestError(
                f"existing corpus artifact {artifact_id!r} conflicts with its manifest"
            )

        existing_provenance = con.execute(
            """SELECT source_name, source_ref, source_version, retrieved_at, license_or_terms,
            source_record_id, content_sha256, is_derived FROM mn_artifact_provenance
            WHERE artifact_id = ? ORDER BY provenance_ordinal""",
            [artifact_id],
        ).fetchall()
        if existing_provenance and existing_provenance != provenance:
            raise CorpusIngestError(
                f"existing corpus artifact {artifact_id!r} conflicts with its provenance"
            )
        if not existing_provenance:
            for ordinal, row in enumerate(provenance):
                con.execute(
                    "INSERT INTO mn_artifact_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [artifact_id, ordinal, *row],
                )

        expected_chunks = [
            (
                chunk.chunk_id,
                artifact_id,
                chunk.document_id,
                chunk.title or chunk.document_id,
                chunk.page,
                chunk.chunk_index,
                chunk.text,
            )
            for chunk in chunks
        ]
        existing_chunks = con.execute(
            """SELECT chunk_id, corpus_artifact_id, doc, title, page, chunk_ordinal, text
            FROM mn_citation_chunks WHERE corpus_artifact_id = ? ORDER BY doc, page, chunk_ordinal""",
            [artifact_id],
        ).fetchall()
        if existing_chunks and existing_chunks != sorted(
            expected_chunks, key=lambda row: (row[2], row[4], row[5])
        ):
            raise CorpusIngestError(
                f"existing corpus artifact {artifact_id!r} conflicts with its chunks"
            )
        if not existing_chunks:
            for row in expected_chunks:
                con.execute(
                    "INSERT INTO mn_citation_chunks VALUES (?, ?, ?, ?, ?, ?, ?)", row
                )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return IngestedCorpus(
        artifact_id=artifact_id, chunks=chunks, content_kind=content_kind
    )


def load_corpus_chunks(
    con: duckdb.DuckDBPyConnection, artifact_id: str
) -> tuple[CorpusChunk, ...]:
    """Load one persisted corpus while restoring its exact source metadata."""

    rows = con.execute(
        """SELECT c.chunk_id, c.doc, p.source_version, p.source_ref, c.text, c.chunk_ordinal,
        m.artifact_kind, p.source_name, p.retrieved_at, p.license_or_terms, p.source_record_id,
        p.content_sha256, c.title, c.page
        FROM mn_citation_chunks c
        JOIN mn_artifact_manifests m ON m.artifact_id = c.corpus_artifact_id
        JOIN mn_artifact_provenance p ON p.artifact_id = c.corpus_artifact_id
            AND p.source_record_id = c.doc
        WHERE c.corpus_artifact_id = ? ORDER BY c.doc, c.page, c.chunk_ordinal""",
        [artifact_id],
    ).fetchall()
    if not rows:
        return ()
    chunks: list[CorpusChunk] = []
    for row in rows:
        content_kind: Literal["fixture", "source"] = (
            "fixture" if row[6] == "citation_fixture" else "source"
        )
        chunks.append(
            CorpusChunk(
                chunk_id=row[0],
                document_id=row[1],
                version=row[2],
                source_uri=row[3],
                text=row[4],
                chunk_index=row[5],
                content_kind=content_kind,
                provenance={
                    "source_name": row[7],
                    "retrieved_at": row[8].replace(tzinfo=UTC).isoformat(),
                    "license_or_terms": row[9],
                    "source_record_id": row[10],
                    "content_sha256": row[11],
                },
                title=row[12],
                page=row[13],
            )
        )
    return tuple(chunks)

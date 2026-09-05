"""Deterministic, provenance-preserving chunks for the regulatory corpus.

This module deliberately has no PDF, database, or embedding dependency.  A
future ingest adapter can turn one extracted page into :class:`SourceDocument`
and persist the resulting records unchanged.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal

_TOKEN_RE = re.compile(r"\S+")
_DEHYPHENATE_LINE_BREAK_RE = re.compile(r"(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)")


def normalize_text(text: str) -> str:
    """Normalize extracted page text without changing meaningful token order.

    PDF extractors commonly split a word at a line-ending hyphen.  Removing
    that artifact before whitespace collapsing makes repeated ingestion of the
    same source stable even when line wrapping differs.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _DEHYPHENATE_LINE_BREAK_RE.sub("", text)
    return " ".join(text.split())


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class SourceDocument:
    """One source unit, normally one extracted PDF page.

    ``content_kind`` has no default on purpose: fixtures must be identified at
    construction time rather than being indistinguishable from sourced corpus
    content later in the pipeline.
    """

    document_id: str
    version: str
    source_uri: str
    text: str
    content_kind: Literal["fixture", "source"]
    provenance: Mapping[str, str] = field(default_factory=dict)
    title: str = ""
    page: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("document_id", self.document_id),
            ("version", self.version),
            ("source_uri", self.source_uri),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.content_kind not in {"fixture", "source"}:
            raise ValueError("content_kind must be 'fixture' or 'source'")
        if self.page is not None and (not isinstance(self.page, int) or self.page < 1):
            raise ValueError("page must be a positive integer when provided")
        if not isinstance(self.provenance, Mapping):
            raise TypeError("provenance must be a mapping of strings")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in self.provenance.items()):
            raise TypeError("provenance keys and values must be strings")
        if not normalize_text(self.text):
            raise ValueError("text must contain at least one non-whitespace token")

    def metadata(self) -> dict[str, object]:
        """Return canonical source linkage copied into every derived chunk."""

        return {
            "content_kind": self.content_kind,
            "document_id": self.document_id,
            "is_fixture": self.content_kind == "fixture",
            "page": self.page,
            "provenance": dict(sorted(self.provenance.items())),
            "source_uri": self.source_uri,
            "title": self.title,
            "version": self.version,
        }


@dataclass(frozen=True)
class CorpusChunk:
    """An immutable normalized chunk and the source metadata required to audit it."""

    chunk_id: str
    document_id: str
    version: str
    source_uri: str
    text: str
    chunk_index: int
    content_kind: Literal["fixture", "source"]
    provenance: Mapping[str, str]
    title: str = ""
    page: int | None = None

    @property
    def is_fixture(self) -> bool:
        return self.content_kind == "fixture"

    def record(self) -> dict[str, object]:
        """Return a JSON-safe record with an explicit fixture marker."""

        return {
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "content_kind": self.content_kind,
            "document_id": self.document_id,
            "is_fixture": self.is_fixture,
            "page": self.page,
            "provenance": dict(sorted(self.provenance.items())),
            "source_uri": self.source_uri,
            "text": self.text,
            "title": self.title,
            "version": self.version,
        }


def chunk_document(
    document: SourceDocument,
    *,
    chunk_tokens: int = 800,
    overlap_tokens: int = 150,
) -> list[CorpusChunk]:
    """Chunk one source unit using stable token boundaries and metadata hashes."""

    if chunk_tokens < 1:
        raise ValueError("chunk_tokens must be at least 1")
    if overlap_tokens < 0 or overlap_tokens >= chunk_tokens:
        raise ValueError("overlap_tokens must be non-negative and smaller than chunk_tokens")

    tokens = _TOKEN_RE.findall(normalize_text(document.text))
    metadata = document.metadata()
    chunks: list[CorpusChunk] = []
    step = chunk_tokens - overlap_tokens
    for chunk_index, start in enumerate(range(0, len(tokens), step)):
        text = " ".join(tokens[start : start + chunk_tokens])
        if not text:
            break
        chunk_id = sha256(
            _canonical_json({"chunk_index": chunk_index, "metadata": metadata, "text": text}).encode("utf-8")
        ).hexdigest()
        chunks.append(
            CorpusChunk(
                chunk_id=chunk_id,
                chunk_index=chunk_index,
                content_kind=document.content_kind,
                document_id=document.document_id,
                page=document.page,
                provenance=dict(sorted(document.provenance.items())),
                source_uri=document.source_uri,
                text=text,
                title=document.title,
                version=document.version,
            )
        )
        if start + chunk_tokens >= len(tokens):
            break
    return chunks


def chunk_documents(
    documents: Iterable[SourceDocument],
    *,
    chunk_tokens: int = 800,
    overlap_tokens: int = 150,
) -> list[CorpusChunk]:
    """Chunk an iterable deterministically and reject conflicting re-ingestion.

    Exact duplicate documents are folded, which makes an idempotent ingest
    produce the same chunk set.  The same source/version/page with different
    normalized contents is a provenance conflict and is rejected instead of
    silently replacing evidence.
    """

    unique: dict[tuple[object, ...], SourceDocument] = {}
    fingerprints: dict[tuple[str, str, str, int | None], str] = {}
    for document in documents:
        if not isinstance(document, SourceDocument):
            raise TypeError("documents must contain SourceDocument instances")
        source_key = (document.document_id, document.version, document.source_uri, document.page)
        fingerprint = sha256(normalize_text(document.text).encode("utf-8")).hexdigest()
        previous = fingerprints.setdefault(source_key, fingerprint)
        if previous != fingerprint:
            raise ValueError("conflicting normalized text for the same document, version, source, and page")
        unique_key = (
            document.document_id,
            document.version,
            document.source_uri,
            document.page,
            document.content_kind,
            document.title,
            tuple(sorted(document.provenance.items())),
            fingerprint,
        )
        unique[unique_key] = document

    chunks = [
        chunk
        for _, document in sorted(unique.items(), key=lambda item: _canonical_json(item[0]))
        for chunk in chunk_document(document, chunk_tokens=chunk_tokens, overlap_tokens=overlap_tokens)
    ]
    return sorted(
        chunks,
        key=lambda chunk: (
            chunk.document_id,
            chunk.version,
            chunk.source_uri,
            chunk.page is None,
            chunk.page or 0,
            chunk.chunk_index,
            chunk.chunk_id,
        ),
    )


def serialize_chunks(chunks: Iterable[CorpusChunk]) -> bytes:
    """Serialize chunks canonically for byte-for-byte re-ingestion checks."""

    collected = list(chunks)
    if not all(isinstance(chunk, CorpusChunk) for chunk in collected):
        raise TypeError("chunks must contain CorpusChunk instances")
    ordered = sorted(
        collected,
        key=lambda chunk: (
            chunk.document_id,
            chunk.version,
            chunk.source_uri,
            chunk.page is None,
            chunk.page or 0,
            chunk.chunk_index,
            chunk.chunk_id,
        ),
    )
    return ("\n".join(_canonical_json(chunk.record()) for chunk in ordered) + ("\n" if ordered else "")).encode("utf-8")

"""Bounded, deterministic sparse retrieval over :mod:`copilot.retrieval` chunks.

The ingest lane provides immutable :class:`~copilot.retrieval.chunking.CorpusChunk`
objects.  This module deliberately stays in-memory and side-effect free so an
HTTP or DuckDB adapter can call it without changing ranking semantics.

Ties are ordered by source identity, then page, chunk index, and chunk id.  That
ordering is part of the contract: Python container order and equal BM25 scores
must never change the citations returned to a user.

Only chunks with a strictly positive BM25 score are results.  A chunk that
shares no token with the query is not evidence, and ``rank_bm25.BM25Okapi``
floors the idf of a term that appears in most of the corpus at
``epsilon * average_idf`` (which is ``<= 0`` on tiny or degenerate corpora), so
a non-positive score is treated as "no discriminative match" rather than
being presented as a citation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Final

from rank_bm25 import BM25Okapi

from copilot.retrieval.chunking import CorpusChunk

MAX_QUERY_CHARACTERS: Final = 2_000
MAX_RESULTS: Final = 20
MAX_EXCERPT_CHARACTERS: Final = 1_200
DEFAULT_RESULT_LIMIT: Final = 5
BM25_K1: Final = 1.5
BM25_B: Final = 0.75
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


class CorpusNotIndexable(ValueError):
    """Raised when a non-empty corpus contains no chunk with an indexable token.

    ``rank_bm25`` divides by the vocabulary size while computing idf, so a
    corpus whose every chunk tokenizes to nothing would otherwise surface as a
    raw ``ZeroDivisionError``.  This named failure lets an adapter report the
    corpus as unavailable instead of crashing or inventing results.
    """


def tokenize(text: str) -> list[str]:
    """Return the stable, case-normalized tokens used by sparse retrieval."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return _TOKEN_RE.findall(text.casefold())


@dataclass(frozen=True)
class RetrievalResult:
    """A bounded citation-ready retrieval result.

    ``doc`` and ``page`` are the typed citation identity a ``cite`` adapter
    needs to emit ``[doc p.N]`` without parsing strings.  ``page`` is ``None``
    only when the source chunk carries no page; ``locator`` then says
    ``"page unavailable"`` and :meth:`hit` refuses to invent one.

    ``version`` identifies the exact source revision.  ``date`` is populated
    only when the revision is a valid ISO calendar date; callers still receive
    the original version string for non-date versions.
    """

    doc: str
    source: str
    title: str
    page: int | None
    locator: str
    excerpt: str
    version: str
    date: str | None
    relevance: float
    relevance_rationale: str
    chunk_id: str

    def record(self) -> dict[str, object]:
        """Return the JSON-safe public representation."""

        return {
            "chunk_id": self.chunk_id,
            "date": self.date,
            "doc": self.doc,
            "excerpt": self.excerpt,
            "locator": self.locator,
            "page": self.page,
            "relevance": self.relevance,
            "relevance_rationale": self.relevance_rationale,
            "source": self.source,
            "title": self.title,
            "version": self.version,
        }

    def hit(self) -> dict[str, object]:
        """Return the ``cite`` tool hit shape ``{doc, title, page, chunk_id, score, text}``.

        The field names conform to ``copilot.tools.schemas.RetrievalHit``.  A
        page-less chunk cannot be a ``RetrievalHit`` (``page`` is a required
        positive integer there), so this raises a named error instead of
        defaulting the page.
        """

        if self.page is None:
            raise ValueError(f"chunk {self.chunk_id} has no page and cannot be cited")
        return {
            "doc": self.doc,
            "title": self.title,
            "page": self.page,
            "chunk_id": self.chunk_id,
            "score": self.relevance,
            "text": self.excerpt,
        }


def _date_from_version(version: str) -> str | None:
    """Expose a valid ISO date revision without guessing dates for other versions."""

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", version):
        return None
    try:
        date.fromisoformat(version)
    except ValueError:
        return None
    return version


def _excerpt(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    # Preserve the promised hard cap, including the ellipsis.
    return text[: limit - 1].rstrip() + "…"


def _locator(chunk: CorpusChunk) -> str:
    page = f"page {chunk.page}" if chunk.page is not None else "page unavailable"
    return f"{page}; chunk {chunk.chunk_index}"


def _tie_key(chunk: CorpusChunk) -> tuple[object, ...]:
    """Return the documented stable ordering for otherwise equal scores."""

    return (
        chunk.document_id,
        chunk.version,
        chunk.source_uri,
        chunk.page is None,
        chunk.page or 0,
        chunk.chunk_index,
        chunk.chunk_id,
    )


def _validate_bounds(query: str, limit: int, excerpt_characters: int) -> None:
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    if len(query) > MAX_QUERY_CHARACTERS:
        raise ValueError(f"query must be at most {MAX_QUERY_CHARACTERS} characters")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_RESULTS
    ):
        raise ValueError(f"limit must be an integer from 1 to {MAX_RESULTS}")
    if (
        not isinstance(excerpt_characters, int)
        or isinstance(excerpt_characters, bool)
        or not 1 <= excerpt_characters <= MAX_EXCERPT_CHARACTERS
    ):
        raise ValueError(
            f"excerpt_characters must be an integer from 1 to {MAX_EXCERPT_CHARACTERS}"
        )


def _ordered_corpus(chunks: Iterable[CorpusChunk]) -> list[CorpusChunk]:
    """Validate and order a corpus so ranking never depends on container order."""

    collected = list(chunks)
    if not all(isinstance(chunk, CorpusChunk) for chunk in collected):
        raise TypeError("chunks must contain CorpusChunk instances")
    seen: set[str] = set()
    for chunk in collected:
        if chunk.chunk_id in seen:
            # A duplicate primary key is a data-integrity failure, not a tie.
            raise ValueError(f"duplicate chunk_id: {chunk.chunk_id}")
        seen.add(chunk.chunk_id)
    # Sorting before scoring makes both the BM25 input and equal-score ordering
    # independent of database iteration order.
    return sorted(collected, key=_tie_key)


def search(
    query: str,
    chunks: Iterable[CorpusChunk],
    *,
    limit: int = DEFAULT_RESULT_LIMIT,
    excerpt_characters: int = MAX_EXCERPT_CHARACTERS,
) -> list[RetrievalResult]:
    """Return bounded BM25 results with explicit, deterministic tie handling.

    Queries must fit within :data:`MAX_QUERY_CHARACTERS`; result count is
    capped at :data:`MAX_RESULTS`; and every excerpt is hard-capped.  Chunks
    whose BM25 score is not strictly positive are dropped *before* the limit
    is applied, so a query with no token overlap returns ``[]`` rather than
    ``limit`` irrelevant passages.  Equal scores are sorted by ``document_id,
    version, source_uri, page, chunk_index, chunk_id`` ascending, after the
    score descending.

    Raises :class:`CorpusNotIndexable` when the corpus is non-empty but no
    chunk tokenizes to anything, and ``ValueError`` for duplicate chunk ids.
    """

    _validate_bounds(query, limit, excerpt_characters)
    query_tokens = tokenize(query)
    ordered_chunks = _ordered_corpus(chunks)
    if not ordered_chunks:
        return []
    corpus_tokens = [tokenize(chunk.text) for chunk in ordered_chunks]
    if not any(corpus_tokens):
        raise CorpusNotIndexable("corpus contains no indexable tokens")
    if not query_tokens:
        return []

    scorer = BM25Okapi(corpus_tokens, k1=BM25_K1, b=BM25_B)
    scored = sorted(
        (
            (float(score), chunk, chunk_tokens)
            for score, chunk, chunk_tokens in zip(
                scorer.get_scores(query_tokens),
                ordered_chunks,
                corpus_tokens,
                strict=True,
            )
            if float(score) > 0.0
        ),
        key=lambda item: (-item[0], _tie_key(item[1])),
    )[:limit]

    matched_terms = set(query_tokens)
    results: list[RetrievalResult] = []
    for score, chunk, chunk_tokens in scored:
        shared = sorted(matched_terms & set(chunk_tokens))
        results.append(
            RetrievalResult(
                doc=chunk.document_id,
                source=chunk.source_uri,
                title=chunk.title or chunk.document_id,
                page=chunk.page,
                locator=_locator(chunk),
                excerpt=_excerpt(chunk.text, limit=excerpt_characters),
                version=chunk.version,
                date=_date_from_version(chunk.version),
                relevance=score,
                relevance_rationale="BM25 sparse match for " + ", ".join(shared),
                chunk_id=chunk.chunk_id,
            )
        )
    return results

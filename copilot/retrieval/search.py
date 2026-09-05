"""Bounded, deterministic sparse retrieval over :mod:`copilot.retrieval` chunks.

The ingest lane provides immutable :class:`~copilot.retrieval.chunking.CorpusChunk`
objects.  This module deliberately stays in-memory and side-effect free so an
HTTP or DuckDB adapter can call it without changing ranking semantics.

Ties are ordered by source identity, then page, chunk index, and chunk id.  That
ordering is part of the contract: Python container order and equal BM25 scores
must never change the citations returned to a user.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

from rank_bm25 import BM25Okapi

from copilot.retrieval.chunking import CorpusChunk

MAX_QUERY_CHARACTERS: Final = 2_000
MAX_RESULTS: Final = 20
MAX_EXCERPT_CHARACTERS: Final = 1_200
DEFAULT_RESULT_LIMIT: Final = 5
_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Return the stable, case-normalized tokens used by sparse retrieval."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return _TOKEN_RE.findall(text.casefold())


@dataclass(frozen=True)
class RetrievalResult:
    """A bounded citation-ready retrieval result.

    ``version`` identifies the exact source revision.  ``date`` is populated
    only when the revision is an ISO calendar date; callers still receive the
    original version string for non-date versions.
    """

    source: str
    title: str
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
            "excerpt": self.excerpt,
            "locator": self.locator,
            "relevance": self.relevance,
            "relevance_rationale": self.relevance_rationale,
            "source": self.source,
            "title": self.title,
            "version": self.version,
        }


UnavailableReason = Literal["corpus_unavailable", "index_unavailable"]


@dataclass(frozen=True)
class RetrievalResponse:
    """A retrieval result or an explicit, citation-free unavailable outcome.

    An unavailable response deliberately carries no ``RetrievalResult`` values.
    That makes it impossible for a caller to mistake a missing corpus or index
    for a valid citation with a plausible-looking fallback excerpt.
    """

    status: Literal["available", "unavailable"]
    hits: tuple[RetrievalResult, ...]
    reason: UnavailableReason | None = None

    def __post_init__(self) -> None:
        if self.status == "available" and self.reason is not None:
            raise ValueError(
                "available retrieval responses cannot have an unavailable reason"
            )
        if self.status == "unavailable" and self.reason is None:
            raise ValueError("unavailable retrieval responses require a named reason")
        if self.status == "unavailable" and self.hits:
            raise ValueError("unavailable retrieval responses cannot contain citations")

    def record(self) -> dict[str, object]:
        """Return the public payload without inventing a citation on failure."""

        return {
            "hits": [hit.record() for hit in self.hits],
            "reason": self.reason,
            "status": self.status,
        }


def _date_from_version(version: str) -> str | None:
    """Expose an ISO date revision without guessing dates for other versions."""

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", version):
        return version
    return None


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


def search(
    query: str,
    chunks: Iterable[CorpusChunk],
    *,
    limit: int = DEFAULT_RESULT_LIMIT,
    excerpt_characters: int = MAX_EXCERPT_CHARACTERS,
) -> list[RetrievalResult]:
    """Return bounded BM25 results with explicit, deterministic tie handling.

    Queries must fit within :data:`MAX_QUERY_CHARACTERS`; result count is
    capped at :data:`MAX_RESULTS`; and every excerpt is hard-capped.  Equal
    scores are sorted by ``document_id, version, source_uri, page,
    chunk_index, chunk_id`` ascending, after the score descending.
    """

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

    query_tokens = tokenize(query)
    collected = list(chunks)
    if not all(isinstance(chunk, CorpusChunk) for chunk in collected):
        raise TypeError("chunks must contain CorpusChunk instances")
    if not query_tokens or not collected:
        return []

    # Sorting before scoring makes both the BM25 input and equal-score ordering
    # independent of database iteration order.
    ordered_chunks = sorted(collected, key=_tie_key)
    scorer = BM25Okapi(
        [tokenize(chunk.text) for chunk in ordered_chunks], k1=1.5, b=0.75
    )
    scored = sorted(
        zip(scorer.get_scores(query_tokens), ordered_chunks, strict=True),
        key=lambda item: (-float(item[0]), _tie_key(item[1])),
    )[:limit]

    matched_terms = set(query_tokens)
    results: list[RetrievalResult] = []
    for score, chunk in scored:
        chunk_terms = set(tokenize(chunk.text))
        shared = sorted(matched_terms & chunk_terms)
        results.append(
            RetrievalResult(
                source=chunk.source_uri,
                title=chunk.title or chunk.document_id,
                locator=_locator(chunk),
                excerpt=_excerpt(chunk.text, limit=excerpt_characters),
                version=chunk.version,
                date=_date_from_version(chunk.version),
                relevance=float(score),
                relevance_rationale=(
                    "BM25 sparse match for " + ", ".join(shared)
                    if shared
                    else "BM25 score has no token overlap"
                ),
                chunk_id=chunk.chunk_id,
            )
        )
    return results


def retrieve(
    query: str,
    corpus: Iterable[CorpusChunk] | None,
    *,
    index_available: bool = True,
    limit: int = DEFAULT_RESULT_LIMIT,
    excerpt_characters: int = MAX_EXCERPT_CHARACTERS,
) -> RetrievalResponse:
    """Retrieve citations or report why retrieval is unavailable.

    ``search`` remains the low-level ranking primitive for callers that
    already have a populated corpus.  Adapters should use this boundary so a
    missing persisted index or an absent/empty corpus is visible to the user
    as a named, citation-free unavailable response.
    """

    if not isinstance(index_available, bool):
        raise TypeError("index_available must be a boolean")
    if not index_available:
        return RetrievalResponse(
            status="unavailable", hits=(), reason="index_unavailable"
        )
    if corpus is None:
        return RetrievalResponse(
            status="unavailable", hits=(), reason="corpus_unavailable"
        )

    collected = list(corpus)
    if not collected:
        return RetrievalResponse(
            status="unavailable", hits=(), reason="corpus_unavailable"
        )
    return RetrievalResponse(
        status="available",
        hits=tuple(
            search(
                query,
                collected,
                limit=limit,
                excerpt_characters=excerpt_characters,
            )
        ),
    )

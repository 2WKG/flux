"""Bounded, deterministic sparse retrieval over :mod:`copilot.retrieval` chunks.

The ingest lane provides immutable :class:`~copilot.retrieval.chunking.CorpusChunk`
objects.  This module deliberately stays in-memory and side-effect free so an
HTTP or DuckDB adapter can call it without changing ranking semantics.

Ties are ordered by source identity, then page, chunk index, and chunk id.  That
ordering is part of the contract: Python container order and equal BM25 scores
must never change the citations returned to a user.

A chunk is eligible only when it shares a token with the query.  BM25 orders
those lexical matches, but ``rank_bm25.BM25Okapi`` can produce zero or negative
scores when an otherwise valid term appears throughout a tiny or degenerate
corpus.  Those scores are not evidence of no match, so they remain eligible;
zero-overlap chunks never become citations.

Two boundaries are exposed.  :func:`search` and :class:`SparseIndex` are the
ranking primitives: malformed *inputs* (bounds, types, duplicate ids, a corpus
with nothing to index) raise named Python errors.  :func:`retrieve` is the
adapter boundary: every *unavailability* of evidence is returned as a
:class:`RetrievalResponse` whose ``unavailable`` field uses the closed
``copilot.tools.schemas.UnavailableCode`` vocabulary, never as a plausible
empty success.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Literal

from rank_bm25 import BM25Okapi

from copilot.retrieval.chunking import CorpusChunk
from copilot.tools.schemas import Unavailable

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
    content_kind: Literal["fixture", "source"]
    provenance: dict[str, str]

    def record(self) -> dict[str, object]:
        """Return the JSON-safe public representation."""

        return {
            "chunk_id": self.chunk_id,
            "content_kind": self.content_kind,
            "date": self.date,
            "doc": self.doc,
            "excerpt": self.excerpt,
            "locator": self.locator,
            "page": self.page,
            "relevance": self.relevance,
            "relevance_rationale": self.relevance_rationale,
            "provenance": dict(sorted(self.provenance.items())),
            "source": self.source,
            "title": self.title,
            "version": self.version,
        }

    def hit(self) -> dict[str, object]:
        """Return a complete citation-preserving ``cite`` tool hit shape.

        The field names conform to ``copilot.tools.schemas.RetrievalHit``.  A
        page-less chunk cannot be a ``RetrievalHit`` (``page`` is a required
        positive integer there), so this raises a named error instead of
        defaulting the page.
        """

        if self.page is None:
            raise ValueError(f"chunk {self.chunk_id} has no page and cannot be cited")
        return {
            "content_kind": self.content_kind,
            "date": self.date,
            "doc": self.doc,
            "locator": self.locator,
            "provenance": dict(sorted(self.provenance.items())),
            "source": self.source,
            "title": self.title,
            "version": self.version,
            "page": self.page,
            "chunk_id": self.chunk_id,
            "score": self.relevance,
            "text": self.excerpt,
        }


def _date_from_provenance(provenance: dict[str, str]) -> str | None:
    """Return the source retrieval date when a version is not calendar-dated."""

    value = provenance.get("retrieved_at")
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


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


class SparseIndex:
    """A BM25 index built once over an ordered, validated corpus.

    Spec 05 builds the sparse index at startup from ``corpus_chunks``; this
    object is that built artifact.  Its *existence* is what :func:`retrieve`
    checks — an adapter that has not built (or failed to load) the index holds
    ``None`` and gets a named ``invalid_prerequisite`` result rather than
    asserting availability through a flag.

    Building an index over an empty corpus is allowed (the table may exist and
    be empty); building one over a non-empty corpus with no indexable token
    raises :class:`CorpusNotIndexable`.
    """

    __slots__ = ("_chunks", "_scorer", "_tokens")

    def __init__(self, chunks: Iterable[CorpusChunk]) -> None:
        self._chunks: tuple[CorpusChunk, ...] = tuple(_ordered_corpus(chunks))
        self._tokens: tuple[list[str], ...] = tuple(
            tokenize(chunk.text) for chunk in self._chunks
        )
        if self._chunks and not any(self._tokens):
            raise CorpusNotIndexable("corpus contains no indexable tokens")
        self._scorer: BM25Okapi | None = (
            BM25Okapi(list(self._tokens), k1=BM25_K1, b=BM25_B)
            if self._chunks
            else None
        )

    @property
    def size(self) -> int:
        """Number of indexed chunks."""

        return len(self._chunks)

    @property
    def chunks(self) -> tuple[CorpusChunk, ...]:
        """The indexed chunks in the documented deterministic order."""

        return self._chunks

    def search(
        self,
        query: str,
        *,
        limit: int = DEFAULT_RESULT_LIMIT,
        excerpt_characters: int = MAX_EXCERPT_CHARACTERS,
    ) -> list[RetrievalResult]:
        """Return bounded lexical matches ranked by BM25 deterministically.

        See :func:`search` for the contract; this method does not rebuild the
        index per query.
        """

        _validate_bounds(query, limit, excerpt_characters)
        query_tokens = tokenize(query)
        if self._scorer is None or not query_tokens:
            return []

        scored = sorted(
            (
                (float(score), chunk, chunk_tokens)
                for score, chunk, chunk_tokens in zip(
                    self._scorer.get_scores(query_tokens),
                    self._chunks,
                    self._tokens,
                    strict=True,
                )
                if set(query_tokens) & set(chunk_tokens)
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
                    date=_date_from_version(chunk.version)
                    or _date_from_provenance(dict(chunk.provenance)),
                    relevance=score,
                    relevance_rationale="BM25 sparse match for " + ", ".join(shared),
                    chunk_id=chunk.chunk_id,
                    content_kind=chunk.content_kind,
                    provenance=dict(sorted(chunk.provenance.items())),
                )
            )
        return results


def search(
    query: str,
    chunks: Iterable[CorpusChunk],
    *,
    limit: int = DEFAULT_RESULT_LIMIT,
    excerpt_characters: int = MAX_EXCERPT_CHARACTERS,
) -> list[RetrievalResult]:
    """Return bounded lexical matches ranked by BM25 with deterministic ties.

    Queries must fit within :data:`MAX_QUERY_CHARACTERS`; result count is
    capped at :data:`MAX_RESULTS`; and every excerpt is hard-capped.  Only
    chunks sharing at least one token with the query are eligible, so a query
    with no token overlap returns ``[]`` rather than ``limit`` irrelevant
    passages.  Zero and negative BM25 scores remain eligible because they
    occur for valid all-match or tiny corpora.  Equal scores are sorted by ``document_id,
    version, source_uri, page, chunk_index, chunk_id`` ascending, after the
    score descending.

    Raises :class:`CorpusNotIndexable` when the corpus is non-empty but no
    chunk tokenizes to anything, and ``ValueError`` for duplicate chunk ids.
    This convenience builds a :class:`SparseIndex` per call; adapters that
    serve many queries should build the index once.
    """

    _validate_bounds(query, limit, excerpt_characters)
    return SparseIndex(chunks).search(
        query, limit=limit, excerpt_characters=excerpt_characters
    )


@dataclass(frozen=True)
class RetrievalResponse:
    """Ranked citations, or an explicit citation-free unavailable outcome.

    ``unavailable`` carries the shared ``{code, reason, retryable}`` contract
    from ``copilot.tools.schemas`` (closed ``UnavailableCode`` vocabulary; the
    specific cause lives in ``reason``).  The invariants make the two states
    mutually exclusive: an unavailable response never carries a citation, and
    an available response always carries at least one — "available but
    empty" is not a state this type can represent.
    """

    status: Literal["available", "unavailable"]
    hits: tuple[RetrievalResult, ...]
    unavailable: Unavailable | None = None

    def __post_init__(self) -> None:
        if self.status == "available" and self.unavailable is not None:
            raise ValueError(
                "available retrieval responses cannot carry an unavailable reason"
            )
        if self.status == "available" and not self.hits:
            raise ValueError(
                "available retrieval responses require at least one citation"
            )
        if self.status == "unavailable" and self.unavailable is None:
            raise ValueError("unavailable retrieval responses require a named reason")
        if self.status == "unavailable" and self.hits:
            raise ValueError("unavailable retrieval responses cannot contain citations")

    def record(self) -> dict[str, object]:
        """Return the public payload without inventing a citation on failure."""

        return {
            "hits": [hit.record() for hit in self.hits],
            "status": self.status,
            "unavailable": (
                None
                if self.unavailable is None
                else self.unavailable.model_dump(mode="json")
            ),
        }


def _unavailable(
    code: Literal[
        "artifact_unavailable",
        "invalid_prerequisite",
        "unsupported_request",
        "insufficient_evidence",
    ],
    reason: str,
    *,
    retryable: bool,
) -> RetrievalResponse:
    return RetrievalResponse(
        status="unavailable",
        hits=(),
        unavailable=Unavailable(code=code, reason=reason, retryable=retryable),
    )


def retrieve(
    query: str,
    index: SparseIndex | None,
    *,
    limit: int = DEFAULT_RESULT_LIMIT,
    excerpt_characters: int = MAX_EXCERPT_CHARACTERS,
) -> RetrievalResponse:
    """Retrieve citations or report, in the shared vocabulary, why there are none.

    Unavailability is *detected*, in this precedence:

    1. ``index is None`` — the sparse index was never built or failed to load:
       ``invalid_prerequisite`` (retryable once ingest builds it).
    2. The index holds zero chunks — the corpus artifact is empty:
       ``artifact_unavailable`` (retryable once ingest populates it).
    3. The query has no searchable token (whitespace/punctuation only):
       ``unsupported_request`` (not retryable as-is).
    4. No chunk shares a searchable token with the query:
       ``insufficient_evidence`` (not retryable as-is).

    Malformed *inputs* (bounds, non-index argument) raise as they do for
    :func:`search`; those are programming errors at the call site, not
    evidence states.
    """

    if index is not None and not isinstance(index, SparseIndex):
        raise TypeError("index must be a SparseIndex or None")
    _validate_bounds(query, limit, excerpt_characters)

    if index is None:
        return _unavailable(
            "invalid_prerequisite",
            "sparse retrieval index is not built",
            retryable=True,
        )
    if index.size == 0:
        return _unavailable(
            "artifact_unavailable",
            "corpus has no chunks",
            retryable=True,
        )
    if not tokenize(query):
        return _unavailable(
            "unsupported_request",
            "query has no searchable tokens",
            retryable=False,
        )

    hits = index.search(query, limit=limit, excerpt_characters=excerpt_characters)
    if not hits:
        return _unavailable(
            "insufficient_evidence",
            "no corpus chunk shares a token with the query",
            retryable=False,
        )
    return RetrievalResponse(status="available", hits=tuple(hits))

import pytest
from pydantic import ValidationError

from copilot.retrieval.chunking import CorpusChunk
from copilot.retrieval.search import (
    MAX_EXCERPT_CHARACTERS,
    MAX_QUERY_CHARACTERS,
    MAX_RESULTS,
    CorpusNotIndexable,
    RetrievalResponse,
    SparseIndex,
    retrieve,
    search,
)
from copilot.tools.schemas import RetrievalHit, Unavailable


def _chunk(
    chunk_id: str,
    text: str,
    *,
    document_id: str = "regulation",
    version: str = "2026-09-05",
    source_uri: str = "https://example.test/regulation.pdf",
    title: str = "Example regulation",
    page: int | None = 1,
    chunk_index: int = 0,
) -> CorpusChunk:
    return CorpusChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        version=version,
        source_uri=source_uri,
        text=text,
        chunk_index=chunk_index,
        content_kind="source",
        provenance={"sha256": "test"},
        title=title,
        page=page,
    )


# rank_bm25 floors the idf of a term found in most of a corpus at a value that
# is <= 0 on tiny corpora, so tests that need positive scores for a shared term
# pad the corpus with unrelated chunks the way a real corpus would.
_FILLER = [
    _chunk("filler-1", "county outage report", document_id="filler", chunk_index=10),
    _chunk("filler-2", "hospital water supply", document_id="filler", chunk_index=11),
    _chunk("filler-3", "storm ice accumulation", document_id="filler", chunk_index=12),
]


def test_results_are_bounded_and_include_auditable_citation_fields() -> None:
    chunks = [
        _chunk("low", "power outlook", chunk_index=2),
        _chunk("high", "power transmission upgrade", chunk_index=1),
        _chunk("none", "unrelated storm report", chunk_index=3),
    ]

    [result] = search("power transmission", chunks, limit=1, excerpt_characters=12)

    assert result.doc == "regulation"
    assert result.source == "https://example.test/regulation.pdf"
    assert result.title == "Example regulation"
    assert result.page == 1
    assert result.locator == "page 1; chunk 1"
    assert result.excerpt == "power trans…"
    assert result.version == "2026-09-05"
    assert result.date == "2026-09-05"
    assert result.relevance > 0
    assert result.relevance_rationale == "BM25 sparse match for power, transmission"
    assert result.record() == {
        "chunk_id": "high",
        "content_kind": "source",
        "date": "2026-09-05",
        "doc": "regulation",
        "excerpt": "power trans…",
        "locator": "page 1; chunk 1",
        "page": 1,
        "relevance": result.relevance,
        "relevance_rationale": "BM25 sparse match for power, transmission",
        "provenance": {"sha256": "test"},
        "source": "https://example.test/regulation.pdf",
        "title": "Example regulation",
        "version": "2026-09-05",
    }


def test_rationale_names_only_the_terms_each_result_actually_shares() -> None:
    chunks = [
        _chunk("low", "power outlook", chunk_index=2),
        _chunk("high", "power transmission upgrade", chunk_index=1),
        _chunk("none", "unrelated storm report", chunk_index=3),
    ]

    results = search("power transmission", chunks)

    assert [result.chunk_id for result in results] == ["high", "low"]
    assert results[0].relevance_rationale == "BM25 sparse match for power, transmission"
    assert results[1].relevance_rationale == "BM25 sparse match for power"
    assert results[0].relevance > results[1].relevance > 0


def test_result_round_trips_into_the_cite_tool_hit_contract() -> None:
    [result] = search(
        "population center distance",
        [
            _chunk(
                "10cfr100-p12-c3",
                "Population center distance requirements apply.",
                document_id="10cfr100",
                title="10 CFR Part 100",
                page=12,
                chunk_index=3,
            ),
            *_FILLER,
        ],
    )

    hit = RetrievalHit.model_validate(result.hit())

    assert hit.doc == "10cfr100"
    assert hit.title == "10 CFR Part 100"
    assert hit.page == 12
    assert hit.chunk_id == "10cfr100-p12-c3"
    assert hit.score == result.relevance
    assert hit.text == "Population center distance requirements apply."


def test_page_less_result_refuses_to_become_a_cite_hit() -> None:
    [result] = search(
        "capacity",
        [_chunk("id", "capacity planning", page=None), *_FILLER],
    )

    assert result.page is None
    with pytest.raises(ValueError, match="has no page and cannot be cited"):
        result.hit()


def test_no_token_overlap_returns_no_results_instead_of_zero_score_citations() -> None:
    chunks = [
        _chunk("a", "grid capacity", chunk_index=0),
        _chunk("b", "storm outage", chunk_index=1),
        _chunk("c", "hospital water", chunk_index=2),
    ]

    assert search("zzzz qqqq", chunks, limit=3) == []


def test_zero_overlap_chunks_are_dropped_before_the_limit_is_applied() -> None:
    chunks = [
        _chunk("match", "transmission upgrade", chunk_index=0),
        _chunk("miss-1", "county outage report", chunk_index=1),
        _chunk("miss-2", "hospital water supply", chunk_index=2),
        _chunk("miss-3", "storm ice accumulation", chunk_index=3),
    ]

    results = search("transmission", chunks, limit=3)

    assert [result.chunk_id for result in results] == ["match"]
    assert all(result.relevance > 0 for result in results)


def test_small_corpus_keeps_a_lexical_match_when_bm25_idf_is_negative() -> None:
    index = SparseIndex([_chunk("only", "capacity planning")])

    response = retrieve("capacity", index)

    assert response.status == "available"
    assert [hit.chunk_id for hit in response.hits] == ["only"]
    assert response.hits[0].relevance <= 0


def test_all_match_corpus_keeps_only_overlaps_and_uses_bm25_ordering() -> None:
    chunks = [
        _chunk("short", "capacity", document_id="a", chunk_index=0),
        _chunk("long", "capacity capacity planning", document_id="b", chunk_index=1),
    ]

    results = search("capacity", chunks, limit=3)

    assert [result.chunk_id for result in results] == ["long", "short"]
    assert all(result.relevance <= 0 for result in results)
    assert all("capacity" in result.relevance_rationale for result in results)


def test_equal_scores_use_documented_source_identity_tie_breaking() -> None:
    first = _chunk("z-chunk", "grid capacity", document_id="z-doc", page=2)
    second = _chunk("a-chunk", "grid capacity", document_id="a-doc", page=9)

    forward = search("grid", [first, second, *_FILLER])
    reverse = search("grid", [second, first, *_FILLER])

    assert [result.chunk_id for result in forward] == ["a-chunk", "z-chunk"]
    assert [result.chunk_id for result in reverse] == ["a-chunk", "z-chunk"]
    assert forward[0].relevance == forward[1].relevance > 0


def test_no_title_or_page_returns_document_id_and_explicit_locator() -> None:
    [result] = search(
        "capacity",
        [
            _chunk(
                "id", "capacity planning", document_id="plain-doc", title="", page=None
            ),
            *_FILLER,
        ],
    )

    assert result.title == "plain-doc"
    assert result.page is None
    assert result.locator == "page unavailable; chunk 0"


@pytest.mark.parametrize(
    ("version", "expected_date"),
    [
        ("2026-09-05", "2026-09-05"),
        ("v3-final", None),
        ("2026-99-99", None),
        ("20260905", None),
    ],
)
def test_date_is_only_populated_for_a_valid_iso_calendar_version(
    version: str, expected_date: str | None
) -> None:
    [result] = search(
        "capacity", [_chunk("id", "capacity planning", version=version), *_FILLER]
    )

    assert result.version == version
    assert result.date == expected_date


def test_empty_query_and_empty_corpus_return_no_results() -> None:
    assert search("   ", [_chunk("id", "capacity planning")]) == []
    assert search("!!! ???", [_chunk("id", "capacity planning")]) == []
    assert search("capacity", []) == []


def test_corpus_without_indexable_tokens_is_a_named_failure() -> None:
    degenerate = [
        _chunk("a", "!!! ---", chunk_index=0),
        _chunk("b", "???", chunk_index=1),
    ]

    with pytest.raises(CorpusNotIndexable, match="no indexable tokens"):
        search("capacity", degenerate)


def test_duplicate_chunk_ids_are_rejected_rather_than_ordered_by_container() -> None:
    duplicate = [_chunk("same", "grid capacity"), _chunk("same", "grid capacity")]

    with pytest.raises(ValueError, match="duplicate chunk_id: same"):
        search("grid", duplicate)


@pytest.mark.parametrize(
    ("query", "kwargs", "message"),
    [
        ("x" * (MAX_QUERY_CHARACTERS + 1), {}, "query must be at most"),
        ("capacity", {"limit": 0}, "limit must be an integer"),
        ("capacity", {"limit": MAX_RESULTS + 1}, "limit must be an integer"),
        ("capacity", {"limit": True}, "limit must be an integer"),
        (
            "capacity",
            {"excerpt_characters": MAX_EXCERPT_CHARACTERS + 1},
            "excerpt_characters must be an integer",
        ),
    ],
)
def test_input_and_output_bounds_are_enforced(
    query: str, kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        search(query, [_chunk("id", "capacity planning")], **kwargs)  # type: ignore[arg-type]


def _result(chunk_id: str = "id"):
    [result] = search("capacity", [_chunk(chunk_id, "capacity planning"), *_FILLER])
    return result


@pytest.mark.parametrize(
    ("index", "code", "reason", "retryable"),
    [
        (None, "invalid_prerequisite", "sparse retrieval index is not built", True),
        (SparseIndex([]), "artifact_unavailable", "corpus has no chunks", True),
    ],
)
def test_missing_index_and_empty_corpus_are_detected_not_asserted(
    index: SparseIndex | None, code: str, reason: str, retryable: bool
) -> None:
    response = retrieve("capacity", index)

    assert isinstance(response, RetrievalResponse)
    assert response.status == "unavailable"
    assert response.hits == ()
    assert response.unavailable == Unavailable(
        code=code, reason=reason, retryable=retryable
    )
    assert response.record() == {
        "hits": [],
        "status": "unavailable",
        "unavailable": {"code": code, "reason": reason, "retryable": retryable},
    }


def test_index_availability_is_not_a_caller_supplied_flag() -> None:
    with pytest.raises(TypeError, match="SparseIndex or None"):
        retrieve("capacity", True)  # type: ignore[arg-type]


def test_missing_index_wins_over_every_later_check() -> None:
    assert retrieve("   ", None).unavailable.code == "invalid_prerequisite"
    assert retrieve("   ", SparseIndex([])).unavailable.code == "artifact_unavailable"


@pytest.mark.parametrize("query", ["   ", "!!! ???", "- - -"])
def test_query_without_searchable_tokens_is_unsupported_not_an_empty_success(
    query: str,
) -> None:
    index = SparseIndex([_chunk("id", "capacity planning"), *_FILLER])

    response = retrieve(query, index)

    assert response.status == "unavailable"
    assert response.hits == ()
    assert response.unavailable == Unavailable(
        code="unsupported_request",
        reason="query has no searchable tokens",
        retryable=False,
    )


def test_zero_overlap_query_is_insufficient_evidence_not_zero_score_hits() -> None:
    index = SparseIndex(
        [
            _chunk("a", "grid capacity", chunk_index=0),
            _chunk("b", "storm outage", chunk_index=1),
            _chunk("c", "hospital water", chunk_index=2),
        ]
    )

    response = retrieve("zzzz qqqq", index, limit=3)

    assert response.status == "unavailable"
    assert response.hits == ()
    assert response.unavailable == Unavailable(
        code="insufficient_evidence",
        reason="no corpus chunk shares a token with the query",
        retryable=False,
    )


def test_available_response_preserves_real_ranked_citation() -> None:
    index = SparseIndex([_chunk("id", "capacity planning"), *_FILLER])

    response = retrieve("capacity", index)

    assert response.status == "available"
    assert response.unavailable is None
    assert [hit.chunk_id for hit in response.hits] == ["id"]
    assert response.hits[0].relevance > 0
    assert response.record() == {
        "hits": [response.hits[0].record()],
        "status": "available",
        "unavailable": None,
    }


def test_index_search_matches_the_per_call_convenience_and_is_reusable() -> None:
    chunks = [
        _chunk("low", "power outlook", chunk_index=2),
        _chunk("high", "power transmission upgrade", chunk_index=1),
        _chunk("none", "unrelated storm report", chunk_index=3),
    ]
    index = SparseIndex(chunks)

    assert index.size == 3
    assert index.search("power transmission") == search("power transmission", chunks)
    assert index.search("storm") == search("storm", chunks)
    assert [chunk.chunk_id for chunk in index.chunks] == ["high", "low", "none"]


def test_index_over_degenerate_corpus_fails_loudly_at_build_time() -> None:
    with pytest.raises(CorpusNotIndexable, match="no indexable tokens"):
        SparseIndex([_chunk("a", "!!! ---"), _chunk("b", "???", chunk_index=1)])


def test_retrieve_still_raises_for_malformed_inputs() -> None:
    index = SparseIndex([_chunk("id", "capacity planning"), *_FILLER])

    with pytest.raises(ValueError, match="limit must be an integer"):
        retrieve("capacity", index, limit=0)
    with pytest.raises(ValueError, match="query must be at most"):
        retrieve("x" * (MAX_QUERY_CHARACTERS + 1), index)


def test_response_invariants_reject_contradictory_states() -> None:
    reason = Unavailable(
        code="artifact_unavailable", reason="corpus has no chunks", retryable=True
    )

    with pytest.raises(ValueError, match="cannot carry an unavailable reason"):
        RetrievalResponse(status="available", hits=(_result(),), unavailable=reason)
    with pytest.raises(ValueError, match="require at least one citation"):
        RetrievalResponse(status="available", hits=())
    with pytest.raises(ValueError, match="require a named reason"):
        RetrievalResponse(status="unavailable", hits=())
    with pytest.raises(ValueError, match="cannot contain citations"):
        RetrievalResponse(status="unavailable", hits=(_result(),), unavailable=reason)


def test_unavailable_reasons_use_the_shared_closed_vocabulary_only() -> None:
    for code in (
        "artifact_unavailable",
        "invalid_prerequisite",
        "unsupported_request",
        "insufficient_evidence",
    ):
        Unavailable(code=code, reason="named cause", retryable=False)

    with pytest.raises(ValidationError):
        Unavailable(code="corpus_unavailable", reason="x", retryable=False)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Unavailable(code="index_unavailable", reason="x", retryable=False)  # type: ignore[arg-type]


def test_cite_hit_preserves_source_version_date_and_provenance() -> None:
    [result] = search(
        "Minnesota evidence",
        [
            CorpusChunk(
                chunk_id="mn-1",
                document_id="mn-project-note",
                version="2026-09-05",
                source_uri="docs/research/minnesota/source-citation-inventory.md",
                text="Minnesota evidence remains bounded by documented sources.",
                chunk_index=0,
                content_kind="source",
                provenance={"retrieved_at": "2026-09-05T18:01:41+00:00", "source_name": "Flux project document"},
                title="Minnesota source citation inventory",
                page=1,
            ),
            *_FILLER,
        ],
    )

    hit = RetrievalHit.model_validate(result.hit())

    assert hit.content_kind == "source"
    assert hit.source == "docs/research/minnesota/source-citation-inventory.md"
    assert hit.version == "2026-09-05"
    assert hit.date == "2026-09-05"
    assert hit.provenance == {
        "retrieved_at": "2026-09-05T18:01:41+00:00",
        "source_name": "Flux project document",
    }
    assert hit.locator == "page 1; chunk 0"

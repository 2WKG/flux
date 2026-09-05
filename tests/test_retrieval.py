import pytest

from copilot.retrieval.chunking import CorpusChunk
from copilot.retrieval.search import (
    MAX_EXCERPT_CHARACTERS,
    MAX_QUERY_CHARACTERS,
    MAX_RESULTS,
    RetrievalResponse,
    retrieve,
    search,
)


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


def test_results_are_bounded_and_include_auditable_citation_fields() -> None:
    chunks = [
        _chunk("low", "power outlook", chunk_index=2),
        _chunk("high", "power transmission upgrade", chunk_index=1),
        _chunk("none", "unrelated storm report", chunk_index=3),
    ]

    [result] = search("power transmission", chunks, limit=1, excerpt_characters=12)

    assert result.source == "https://example.test/regulation.pdf"
    assert result.title == "Example regulation"
    assert result.locator == "page 1; chunk 1"
    assert result.excerpt == "power trans…"
    assert result.version == "2026-09-05"
    assert result.date == "2026-09-05"
    assert result.relevance > 0
    assert result.relevance_rationale == "BM25 sparse match for power, transmission"
    assert result.record()["chunk_id"] == "high"


def test_equal_scores_use_documented_source_identity_tie_breaking() -> None:
    first = _chunk("z-chunk", "grid capacity", document_id="z-doc", page=2)
    second = _chunk("a-chunk", "grid capacity", document_id="a-doc", page=9)

    forward = search("grid", [first, second])
    reverse = search("grid", [second, first])

    assert [result.chunk_id for result in forward] == ["a-chunk", "z-chunk"]
    assert [result.chunk_id for result in reverse] == ["a-chunk", "z-chunk"]


def test_no_title_or_page_returns_document_id_and_explicit_locator() -> None:
    [result] = search(
        "capacity",
        [
            _chunk(
                "id", "capacity planning", document_id="plain-doc", title="", page=None
            )
        ],
    )

    assert result.title == "plain-doc"
    assert result.locator == "page unavailable; chunk 0"


def test_empty_query_and_empty_corpus_return_no_results() -> None:
    assert search("   ", [_chunk("id", "capacity planning")]) == []
    assert search("capacity", []) == []


@pytest.mark.parametrize(
    ("corpus", "index_available", "reason"),
    [
        (None, True, "corpus_unavailable"),
        ([], True, "corpus_unavailable"),
        ([_chunk("id", "capacity planning")], False, "index_unavailable"),
    ],
)
def test_unavailable_corpus_or_index_returns_named_citation_free_response(
    corpus: list[CorpusChunk] | None,
    index_available: bool,
    reason: str,
) -> None:
    response = retrieve("capacity", corpus, index_available=index_available)

    assert isinstance(response, RetrievalResponse)
    assert response.status == "unavailable"
    assert response.reason == reason
    assert response.hits == ()
    assert response.record() == {"hits": [], "reason": reason, "status": "unavailable"}


def test_available_response_preserves_real_ranked_citation() -> None:
    response = retrieve("capacity", [_chunk("id", "capacity planning")])

    assert response.status == "available"
    assert response.reason is None
    assert [hit.chunk_id for hit in response.hits] == ["id"]


@pytest.mark.parametrize(
    ("query", "kwargs", "message"),
    [
        ("x" * (MAX_QUERY_CHARACTERS + 1), {}, "query must be at most"),
        ("capacity", {"limit": 0}, "limit must be an integer"),
        ("capacity", {"limit": MAX_RESULTS + 1}, "limit must be an integer"),
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

"""Offline lineage checks for citation-ready retrieval results."""

from copilot.retrieval.chunking import CorpusChunk
from copilot.retrieval.search import RetrievalResult, retrieve, search


def _chunk(
    chunk_id: str,
    *,
    document_id: str,
    source_uri: str,
    title: str,
    version: str,
    page: int,
    chunk_index: int,
    text: str,
) -> CorpusChunk:
    return CorpusChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        version=version,
        source_uri=source_uri,
        text=text,
        chunk_index=chunk_index,
        content_kind="source",
        provenance={"fixture": "citation-lineage"},
        title=title,
        page=page,
    )


def _assert_exact_lineage(result: RetrievalResult, chunk: CorpusChunk) -> None:
    """Assert that a public result is traceable to its exact source chunk."""

    assert result.chunk_id == chunk.chunk_id
    assert result.source == chunk.source_uri
    assert result.title == chunk.title
    assert result.version == chunk.version
    assert result.date == chunk.version
    assert result.locator == f"page {chunk.page}; chunk {chunk.chunk_index}"
    assert result.excerpt == chunk.text
    assert result.record()["chunk_id"] == chunk.chunk_id


def test_each_citation_is_traceable_to_the_exact_ranked_chunk() -> None:
    exact_match = _chunk(
        "10cfr100-p12-c3",
        document_id="10cfr100",
        source_uri="https://example.test/10-cfr-part-100.pdf",
        title="10 CFR Part 100",
        version="2026-07-16",
        page=12,
        chunk_index=3,
        text="Population center distance and exclusion area requirements apply.",
    )
    distractor = _chunk(
        "ferc-p4-c0",
        document_id="ferc-dlr",
        source_uri="https://example.test/ferc-dlr.pdf",
        title="FERC DLR ANOPR",
        version="2026-05-01",
        page=4,
        chunk_index=0,
        text="Dynamic line ratings improve transmission operations.",
    )

    [result] = search(
        "population center exclusion area", [distractor, exact_match], limit=1
    )

    _assert_exact_lineage(result, exact_match)


def test_response_citations_keep_independent_source_page_and_version_lineage() -> None:
    chunks = [
        _chunk(
            "doe-p8-c2",
            document_id="doe-c2n-2024",
            source_uri="https://example.test/doe-coal-to-nuclear-2024.pdf",
            title="DOE Coal to Nuclear Update",
            version="2024-09-01",
            page=8,
            chunk_index=2,
            text="Coal plant conversion can reuse transmission infrastructure.",
        ),
        _chunk(
            "nrc-p15-c1",
            document_id="nrc-siting-rule-2026",
            source_uri="https://example.test/nrc-siting-rule-2026.pdf",
            title="NRC Siting Rule",
            version="2026-07-16",
            page=15,
            chunk_index=1,
            text="Siting infrastructure must support reactor licensing review.",
        ),
    ]

    response = retrieve("transmission infrastructure", list(reversed(chunks)), limit=2)

    assert response.status == "available"
    assert response.reason is None
    expected_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    assert {hit.chunk_id for hit in response.hits} == set(expected_by_id)
    for hit in response.hits:
        _assert_exact_lineage(hit, expected_by_id[hit.chunk_id])

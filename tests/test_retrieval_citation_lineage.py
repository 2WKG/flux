"""Offline lineage checks for citation-ready retrieval results.

Two layers are proven here.  The ranking layer: every public field of a
``RetrievalResult`` (attribute *and* ``record()`` payload) is copied from the
exact chunk that was ranked, never from a neighbour or a default.  The ingest
layer: chunks produced by the real ``chunk_documents()`` from
``copilot.retrieval.chunking`` (sha256 ids) survive the search unchanged.
"""

from __future__ import annotations

import re

from copilot.retrieval.chunking import CorpusChunk, SourceDocument, chunk_documents
from copilot.retrieval.search import (
    RetrievalResult,
    SparseIndex,
    retrieve,
    search,
)
from copilot.tools.schemas import RetrievalHit

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


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
        content_kind="fixture",
        provenance={"fixture": "citation-lineage"},
        title=title,
        page=page,
    )


def _expected_date(version: str) -> str | None:
    return version if re.fullmatch(r"\d{4}-\d{2}-\d{2}", version) else None


def _assert_exact_lineage(result: RetrievalResult, chunk: CorpusChunk) -> None:
    """Assert that a public result is traceable, field by field, to its chunk."""

    assert result.chunk_id == chunk.chunk_id
    assert result.doc == chunk.document_id
    assert result.source == chunk.source_uri
    assert result.title == chunk.title
    assert result.version == chunk.version
    assert result.date == _expected_date(chunk.version)
    assert result.page == chunk.page
    assert result.locator == f"page {chunk.page}; chunk {chunk.chunk_index}"
    assert result.excerpt == chunk.text
    assert result.relevance > 0
    assert result.relevance_rationale.startswith("BM25 sparse match for ")

    # The full JSON payload, not a single key: an adapter or SSE ``citation``
    # event emits this dict, so dropping or swapping any field must fail here.
    assert result.record() == {
        "chunk_id": chunk.chunk_id,
        "date": _expected_date(chunk.version),
        "doc": chunk.document_id,
        "excerpt": chunk.text,
        "locator": f"page {chunk.page}; chunk {chunk.chunk_index}",
        "page": chunk.page,
        "relevance": result.relevance,
        "relevance_rationale": result.relevance_rationale,
        "source": chunk.source_uri,
        "title": chunk.title,
        "version": chunk.version,
    }

    # And the ``cite`` tool shape validates against the shared contract.
    hit = RetrievalHit.model_validate(result.hit())
    assert (hit.doc, hit.title, hit.page, hit.chunk_id, hit.text) == (
        chunk.document_id,
        chunk.title,
        chunk.page,
        chunk.chunk_id,
        chunk.text,
    )
    assert hit.score == result.relevance


# Unrelated chunks so a term shared by the fixtures of interest is not in more
# than half of the corpus (rank_bm25 floors such idf at <= 0 on tiny corpora).
_FILLER = [
    _chunk(
        f"filler-{index}",
        document_id="filler",
        source_uri="https://example.test/filler.pdf",
        title="Filler",
        version="2026-01-01",
        page=index + 1,
        chunk_index=0,
        text=text,
    )
    for index, text in enumerate(
        ["county outage report", "hospital water supply", "storm ice accumulation"]
    )
]


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
        version="rev-3",
        page=4,
        chunk_index=0,
        text="Dynamic line ratings improve transmission operations.",
    )

    [result] = search(
        "population center exclusion area",
        [distractor, exact_match, *_FILLER],
        limit=1,
    )

    _assert_exact_lineage(result, exact_match)


def test_non_iso_version_keeps_the_version_and_reports_no_date() -> None:
    revision = _chunk(
        "ferc-p4-c0",
        document_id="ferc-dlr",
        source_uri="https://example.test/ferc-dlr.pdf",
        title="FERC DLR ANOPR",
        version="rev-3",
        page=4,
        chunk_index=0,
        text="Dynamic line ratings improve transmission operations.",
    )

    [result] = search("dynamic line ratings", [revision, *_FILLER], limit=1)

    _assert_exact_lineage(result, revision)
    assert result.version == "rev-3"
    assert result.date is None
    assert result.record()["date"] is None


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

    response = retrieve(
        "transmission infrastructure",
        SparseIndex([*reversed(chunks), *_FILLER]),
        limit=2,
    )

    assert response.status == "available"
    assert response.unavailable is None
    expected_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    assert {hit.chunk_id for hit in response.hits} == set(expected_by_id)
    for hit in response.hits:
        _assert_exact_lineage(hit, expected_by_id[hit.chunk_id])
    # Different documents, pages, and versions did not bleed into each other.
    assert len({hit.doc for hit in response.hits}) == 2
    assert len({hit.page for hit in response.hits}) == 2
    assert len({hit.version for hit in response.hits}) == 2


def test_end_to_end_lineage_from_source_documents_through_real_chunking() -> None:
    """SourceDocument -> chunk_documents() (sha256 ids) -> SparseIndex -> hit."""

    documents = [
        SourceDocument(
            document_id="10cfr100",
            version="2026-07-16",
            source_uri="https://example.test/10-cfr-part-100.pdf",
            text=(
                "Reactor sites shall have an exclusion area. Population center "
                "distance is measured from the reactor. Low population zone "
                "boundaries consider evacuation. Seismic hazard analysis is "
                "required for every applicant."
            ),
            content_kind="source",
            provenance={"sha256": "abc"},
            title="10 CFR Part 100",
            page=12,
        ),
        SourceDocument(
            document_id="ferc-dlr-anopr-rm24-6",
            version="2024-06-27",
            source_uri="https://example.test/ferc-dlr.pdf",
            text=(
                "Dynamic line ratings adjust transmission capacity with ambient "
                "conditions. Transmission providers would implement ratings "
                "hourly. Congestion costs fall when ratings reflect weather."
            ),
            content_kind="source",
            provenance={"sha256": "def"},
            title="FERC DLR ANOPR",
            page=4,
        ),
    ]

    produced = chunk_documents(documents, chunk_tokens=6, overlap_tokens=1)
    by_id = {chunk.chunk_id: chunk for chunk in produced}

    assert len(produced) >= 6, [chunk.text for chunk in produced]
    assert all(_SHA256_HEX.fullmatch(chunk_id) for chunk_id in by_id)
    assert len(by_id) == len(produced)

    index = SparseIndex(produced)
    assert index.chunks == tuple(produced)

    seismic = [chunk for chunk in produced if "seismic" in chunk.text.casefold()]
    assert len(seismic) == 1
    [result] = index.search("seismic hazard analysis", limit=1)
    _assert_exact_lineage(result, seismic[0])
    assert result.doc == "10cfr100"
    assert result.page == 12
    assert result.excerpt == seismic[0].text

    # Overlapping windows legitimately repeat a term across adjacent chunks;
    # the hit must still resolve to one of the chunks ingest actually produced.
    congestion = {
        chunk.chunk_id: chunk
        for chunk in produced
        if "congestion" in chunk.text.casefold()
    }
    assert congestion
    response = retrieve("congestion costs", index, limit=1)
    assert response.status == "available"
    [hit] = response.hits
    assert hit.chunk_id in congestion
    _assert_exact_lineage(hit, congestion[hit.chunk_id])
    assert hit.doc == "ferc-dlr-anopr-rm24-6"
    assert hit.page == 4

    # Every citation an adapter could emit resolves to a chunk that ingest
    # actually produced, and to nothing else.
    for hit in index.search("transmission ratings population", limit=5):
        assert hit.chunk_id in by_id
        _assert_exact_lineage(hit, by_id[hit.chunk_id])

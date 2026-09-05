from copilot.retrieval.chunking import (
    SourceDocument,
    chunk_document,
    chunk_documents,
    normalize_text,
    serialize_chunks,
)


def test_normalization_and_fixture_provenance_are_preserved() -> None:
    document = SourceDocument(
        document_id="fixture-regulation",
        version="fixture-v1",
        source_uri="fixture://regulations/example",
        text="Inter-\n national\n\nGrid   standard.",
        content_kind="fixture",
        provenance={"origin": "unit-test", "scenario": "retrieval"},
        page=1,
    )

    assert normalize_text(document.text) == "International Grid standard."
    [chunk] = chunk_document(document, chunk_tokens=10, overlap_tokens=0)

    assert chunk.text == "International Grid standard."
    assert chunk.record() == {
        "chunk_id": chunk.chunk_id,
        "chunk_index": 0,
        "content_kind": "fixture",
        "document_id": "fixture-regulation",
        "is_fixture": True,
        "page": 1,
        "provenance": {"origin": "unit-test", "scenario": "retrieval"},
        "source_uri": "fixture://regulations/example",
        "text": "International Grid standard.",
        "title": "",
        "version": "fixture-v1",
    }


def test_reingestion_is_byte_identical_and_sorted_independent_of_input_order() -> None:
    source = SourceDocument(
        document_id="regulation-a",
        version="2026-09-05",
        source_uri="https://example.test/regulation-a.pdf",
        text="one two three four five six",
        content_kind="source",
        provenance={"sha256": "abc123"},
        title="Regulation A",
        page=2,
    )
    fixture = SourceDocument(
        document_id="fixture-b",
        version="v1",
        source_uri="fixture://retrieval/b",
        text="alpha beta gamma delta",
        content_kind="fixture",
        provenance={"origin": "checked-in fixture"},
    )

    first = chunk_documents([source, fixture, source], chunk_tokens=3, overlap_tokens=1)
    second = chunk_documents([fixture, source], chunk_tokens=3, overlap_tokens=1)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert serialize_chunks(first) == serialize_chunks(second)
    assert [chunk.document_id for chunk in first] == ["fixture-b", "fixture-b", "regulation-a", "regulation-a", "regulation-a"]


def test_conflicting_content_for_an_existing_source_version_is_rejected() -> None:
    common = {
        "document_id": "regulation-a",
        "version": "1",
        "source_uri": "https://example.test/a.pdf",
        "content_kind": "source",
    }
    original = SourceDocument(text="first version", **common)
    conflicting = SourceDocument(text="different body", **common)

    try:
        chunk_documents([original, conflicting])
    except ValueError as error:
        assert "conflicting normalized text" in str(error)
    else:
        raise AssertionError("expected a conflicting re-ingestion error")

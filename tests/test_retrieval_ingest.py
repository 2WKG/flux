from datetime import datetime

import duckdb
import pytest

from copilot.retrieval.chunking import SourceDocument
from copilot.retrieval.ingest import (
    CorpusIngestError,
    ingest_corpus,
    load_corpus_chunks,
)
from copilot.retrieval.search import search

SOURCE = SourceDocument(
    document_id="mn-project-decision",
    version="b50f731163c5d8fac84a9d20d79785a25c7d763b",
    source_uri="docs/research/minnesota/source-citation-inventory.md",
    text="Minnesota project documentation distinguishes aggregate evidence from topology evidence.",
    content_kind="source",
    provenance={
        "source_name": "Flux Minnesota source inventory",
        "retrieved_at": "2026-09-05T18:01:41-04:00",
        "license_or_terms": "Project repository documentation",
    },
    title="Minnesota primary-source and citation inventory",
    page=1,
)


def test_ingest_is_idempotent_and_preserves_project_document_provenance() -> None:
    con = duckdb.connect(":memory:")
    try:
        created_at = datetime.fromisoformat("2026-09-05T19:00:00+00:00")
        first = ingest_corpus(con, [SOURCE], created_at=created_at, chunk_tokens=20, overlap_tokens=2)
        second = ingest_corpus(con, [SOURCE], created_at=created_at, chunk_tokens=20, overlap_tokens=2)

        assert first == second
        assert con.execute("SELECT count(*) FROM mn_citation_chunks").fetchone() == (1,)
        assert con.execute(
            "SELECT source_ref, source_version, source_record_id FROM mn_artifact_provenance"
        ).fetchone() == (
            "docs/research/minnesota/source-citation-inventory.md",
            "b50f731163c5d8fac84a9d20d79785a25c7d763b",
            "mn-project-decision",
        )
        [chunk] = load_corpus_chunks(con, first.artifact_id)
        assert chunk.content_kind == "source"
        assert chunk.source_uri == SOURCE.source_uri
        assert chunk.version == SOURCE.version
        assert chunk.provenance["source_name"] == "Flux Minnesota source inventory"
        assert chunk.provenance["license_or_terms"] == "Project repository documentation"
        [result] = search("topology evidence", [chunk])
        assert result.date == "2026-09-05"
        assert result.hit()["version"] == SOURCE.version
    finally:
        con.close()


def test_ingest_rejects_page_less_or_mixed_evidence_instead_of_inventing_citations() -> None:
    con = duckdb.connect(":memory:")
    try:
        page_less = SourceDocument(
            document_id="page-less", version="v1", source_uri="file.md", text="Evidence.",
            content_kind="source", provenance=SOURCE.provenance, page=None,
        )
        with pytest.raises(CorpusIngestError, match="exact positive page"):
            ingest_corpus(con, [page_less], created_at=datetime.fromisoformat("2026-09-05T19:00:00+00:00"))

        fixture = SourceDocument(
            document_id="fixture", version="v1", source_uri="fixture.md", text="Fixture evidence.",
            content_kind="fixture", provenance=SOURCE.provenance, page=1,
        )
        with pytest.raises(CorpusIngestError, match="cannot mix fixture and source"):
            ingest_corpus(con, [SOURCE, fixture], created_at=datetime.fromisoformat("2026-09-05T19:00:00+00:00"))
    finally:
        con.close()

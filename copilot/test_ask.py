"""End-to-end local proof for the POST /ask v1 stream boundary."""

from __future__ import annotations

import asyncio
import importlib
import json
from asyncio import CancelledError
from collections.abc import AsyncIterator
from pathlib import Path
from types import MappingProxyType

import duckdb
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.narration import GroundedNarration, narrate
from copilot.retrieval.chunking import SourceDocument, chunk_document
from copilot.retrieval.search import SparseIndex, retrieve
from copilot.routes.ask import HEARTBEAT_SECONDS, AskRequest, _heartbeat
from copilot.routes.interventions import SiteScoreRequest, read_site
from copilot.runtime import AsyncNarrationProvider, ToolTurn
from copilot.tools.schemas import (
    ArtifactRef,
    CiteData,
    RetrievalHit,
    unavailable_output,
)
from copilot.tools.sql import ApprovedMinnesotaView, MinnesotaSqlExecutor

ATTEMPT = "attempt_0123456789"


def _events(response) -> list[tuple[int, str, dict[str, object]]]:
    assert response.headers["content-type"].startswith("text/event-stream")
    parsed = []
    for block in response.text.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if ": " in line
        )
        if "event" in fields:
            parsed.append(
                (int(fields["id"]), fields["event"], json.loads(fields["data"]))
            )
    return parsed


class _Provider:
    def __init__(self) -> None:
        self.evidence: list[object] = []

    async def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        self.evidence.append(narration.evidence)
        yield "Grounded local answer."


class _FailingProvider:
    async def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        if False:
            yield "unreachable"
        raise RuntimeError("provider secret must not reach the stream")


class _CitationLineageProvider(_Provider):
    async def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        self.evidence.append(narration.evidence)
        yield "The stored fixture supports this statement [mn-regulation p.3]."


class _UncitedRegulatoryProvider(_Provider):
    async def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        self.evidence.append(narration.evidence)
        yield "The NRC requires a review."


class _CancelledProvider:
    async def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        if False:
            yield "unreachable"
        raise CancelledError


class _SqlBackend:
    def __init__(
        self,
        path: Path,
        provider: _Provider | None,
        *,
        query: str = "SELECT id, label FROM mn_summary",
    ) -> None:
        self.path = path
        self.provider = provider
        self.query = query

    async def turn(self, payload: AskRequest) -> ToolTurn:
        view = ApprovedMinnesotaView(
            "mn_summary",
            (
                ArtifactRef(
                    artifact_id="mn:fixture:ask-sql",
                    artifact_version="v1",
                    source_kind="fixture",
                    source_ref="fixture.duckdb",
                ),
            ),
        )
        result = await MinnesotaSqlExecutor(self.path, [view]).execute(self.query)
        return ToolTurn(
            "ask-sql",
            "sql",
            {"query": self.query},
            narrate("sql", result),
        )


class _CitationBackend:
    def __init__(self, provider: _Provider) -> None:
        self.provider = provider

    async def turn(self, payload: AskRequest) -> ToolTurn:
        document = SourceDocument(
            document_id="mn-regulation",
            version="2026-09-05",
            source_uri="https://example.test/mn-regulation",
            title="Minnesota regulation fixture",
            page=3,
            text="Minnesota planning evidence requires an exact cited source.",
            content_kind="fixture",
            provenance={"retrieved_at": "2026-09-05T00:00:00Z"},
        )
        index = SparseIndex(chunk_document(document, chunk_tokens=20, overlap_tokens=0))
        response = retrieve("Minnesota evidence", index, limit=1)
        assert response.status == "available"
        hits = [
            RetrievalHit(
                content_kind=hit.content_kind,
                date=hit.date,
                doc=hit.doc,
                locator=hit.locator,
                provenance=hit.provenance,
                source=hit.source,
                title=hit.title,
                page=hit.page,
                chunk_id=hit.chunk_id,
                score=hit.relevance,
                text=hit.excerpt,
                version=hit.version,
            )
            for hit in response.hits
        ]
        result = CiteData(
            status="available",
            provenance=[
                ArtifactRef(
                    artifact_id="mn:fixture:ask-corpus",
                    artifact_version="2026-09-05",
                    source_kind="fixture",
                    source_ref=document.source_uri,
                )
            ],
            hits=hits,
        )
        return ToolTurn(
            "ask-cite",
            "cite",
            {"query": payload.question, "k": 1},
            narrate("cite", result),
        )


class _UnavailableCitationBackend:
    """A retrieval boundary that explicitly has no admissible evidence."""

    provider = None

    async def turn(self, payload: AskRequest) -> ToolTurn:
        return ToolTurn(
            "ask-cite-unavailable",
            "cite",
            {"query": payload.question, "k": 1},
            narrate(
                "cite",
                unavailable_output("insufficient_evidence", "fixture corpus has no hit"),
            ),
        )


class _ScoreBackend:
    def __init__(self, path: Path, provider: _Provider) -> None:
        self.path = path
        self.provider = provider

    async def turn(self, payload: AskRequest) -> ToolTurn:
        result = read_site(
            str(self.path),
            SiteScoreRequest(site_id="1", unit_mw=300, scenario_id="mn_fixture"),
        )
        provenance = result["provenance"]
        narration = GroundedNarration(
            status="available",
            text="Accepted score evidence is available.",
            evidence=MappingProxyType(
                {key: value for key, value in result.items() if key != "provenance"}
            ),
            provenance=(
                ArtifactRef(
                    artifact_id="mn:fixture:ask-score",
                    artifact_version=str(provenance["source_version"]),
                    source_kind="fixture",
                    source_ref=str(provenance["source_ref"]),
                ),
            ),
            citations=(),
            limitations=("Evidence source kind: fixture.",),
        )
        return ToolTurn(
            "ask-score",
            "score_site",
            {"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
            narration,
        )


def _available_turn() -> ToolTurn:
    return ToolTurn(
        "ask-live",
        "fixture",
        {"source": "fixture"},
        GroundedNarration(
            status="available",
            text="Local fixture evidence is available.",
            evidence=MappingProxyType({"source": "fixture"}),
            provenance=(
                ArtifactRef(
                    artifact_id="mn:fixture:ask-live",
                    artifact_version="v1",
                    source_kind="fixture",
                    source_ref="ask-live.json",
                ),
            ),
            citations=(),
            limitations=("Evidence source kind: fixture.",),
        ),
    )


class _ImmediateBackend:
    def __init__(
        self,
        provider: AsyncNarrationProvider | None,
        lifecycle_sent: asyncio.Event | None = None,
    ) -> None:
        self.provider = provider
        self.lifecycle_sent = lifecycle_sent

    async def turn(self, payload: AskRequest) -> ToolTurn:
        if self.lifecycle_sent is not None:
            assert self.lifecycle_sent.is_set()
        return _available_turn()


class _BlockingProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except CancelledError:
            self.cancelled.set()
            raise
        yield "unreachable"


class _FailingBackend:
    provider = None

    async def turn(self, payload: AskRequest) -> ToolTurn:
        raise RuntimeError("backend secret must not reach the stream")


def _client(path: Path, backend: object | None) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=path), ask_backend=backend))


def _database(path: Path) -> None:
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE rows (id INTEGER, label TEXT)")
        con.execute("INSERT INTO rows VALUES (1, 'evidence-row')")
        con.execute("CREATE VIEW mn_summary AS SELECT * FROM rows")
        con.execute(
            "CREATE TABLE site_candidates (site_id BIGINT,name TEXT,kind TEXT,county_fips TEXT,source_name TEXT,source_ref TEXT,source_version TEXT,source_retrieved_at TIMESTAMP,fixture_batch_id TEXT)"
        )
        con.execute(
            "CREATE TABLE site_scores (site_id BIGINT,scenario_id TEXT,unit_mw INTEGER,safety_score DOUBLE,safety_flags_json JSON,grid_value_score DOUBLE,lol_reduction_mwh DOUBLE,congestion_relief_pct DOUBLE,blackstart_reach_mw DOUBLE)"
        )
        con.execute(
            "INSERT INTO site_candidates VALUES (1, 'fixture site', 'coal_retired', '27001', 'fixture', 'fixture-score.json', 'v1', '2026-01-01', 'batch')"
        )
        con.execute(
            "INSERT INTO site_scores VALUES (1, 'mn_fixture', 300, 10, '[]', 2, 3, 4, 5)"
        )
    finally:
        con.close()


def _body(question: str = "What evidence is available?") -> dict[str, object]:
    return {
        "attempt_id": ATTEMPT,
        "question": question,
        "history": [{"role": "user", "content": "Earlier question"}],
    }


def test_ask_streams_real_sql_evidence_to_an_injected_provider(tmp_path: Path) -> None:
    database = tmp_path / "ask.duckdb"
    _database(database)
    provider = _Provider()

    response = _client(database, _SqlBackend(database, provider)).post(
        "/ask", json=_body()
    )

    events = _events(response)
    assert response.headers["X-Flux-Attempt-Id"] == ATTEMPT
    assert [event for _, event, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "text",
        "done",
    ]
    assert [seq for seq, _, _ in events] == [1, 2, 3, 4, 5]
    assert events[2][2]["result"] == {
        "columns": ["id", "label"],
        "rows": [[1, "evidence-row"]],
        "row_count": 1,
        "truncated": False,
    }
    assert provider.evidence[0]["rows"] == ((1, "evidence-row"),)


def test_ask_streams_real_retrieval_citation_and_score_evidence(tmp_path: Path) -> None:
    database = tmp_path / "ask.duckdb"
    _database(database)
    citations_provider = _Provider()
    citation_response = _client(database, _CitationBackend(citations_provider)).post(
        "/ask", json=_body("Minnesota evidence")
    )
    citation_events = _events(citation_response)
    assert [event for _, event, _ in citation_events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "citation",
        "text",
        "done",
    ]
    assert citation_events[3][2]["doc"] == "mn-regulation"
    assert citations_provider.evidence[0]["hits"][0]["doc"] == "mn-regulation"

    score_provider = _Provider()
    score_response = _client(database, _ScoreBackend(database, score_provider)).post(
        "/ask", json=_body()
    )
    score_events = _events(score_response)
    assert score_events[2][2]["result"]["safety_score"] == 10.0
    assert score_provider.evidence[0]["grid_value_score"] == 2.0


def test_ask_rejects_sql_writes_and_over_limit_tool_inputs_without_db_mutation(
    tmp_path: Path,
) -> None:
    """The real route cannot turn a tool input into a DuckDB side effect."""
    database = tmp_path / "ask.duckdb"
    _database(database)
    before = database.read_bytes()

    for query in (
        "COPY (SELECT id FROM mn_summary) TO 'must-not-exist.csv'",
        "SELECT id FROM mn_summary " + ("x" * 5_000),
    ):
        provider = _Provider()
        events = _events(
            _client(database, _SqlBackend(database, provider, query=query)).post(
                "/ask", json=_body()
            )
        )

        assert [event for _, event, _ in events] == [
            "lifecycle",
            "tool_call",
            "tool_result",
            "error",
        ]
        assert events[2][2]["ok"] is False
        assert events[2][2]["error"]["code"] == "invalid_input"
        assert events[-1][2]["error"]["code"] == "unavailable"
        assert provider.evidence == []
        assert database.read_bytes() == before
    assert not (tmp_path / "must-not-exist.csv").exists()


def test_ask_preserves_citation_lineage_and_marks_uncited_regulatory_text(
    tmp_path: Path,
) -> None:
    database = tmp_path / "ask.duckdb"
    _database(database)

    citation_provider = _CitationLineageProvider()
    citation_events = _events(
        _client(database, _CitationBackend(citation_provider)).post(
            "/ask", json=_body("What does the fixture regulation say?")
        )
    )
    citation = citation_events[3][2]
    assert citation_events[-1][2]["verified"] is True
    hit = citation_provider.evidence[0]["hits"][0]
    assert citation["citation_id"] == "ask-cite:cite:1"
    assert {key: citation[key] for key in ("doc", "title", "page", "chunk_id")} == {
        key: hit[key] for key in ("doc", "title", "page", "chunk_id")
    }
    assert citation["locator"] == hit["locator"]
    assert citation["excerpt"] == hit["text"]
    assert citation["url"] == hit["source"]

    uncited_events = _events(
        _client(database, _ScoreBackend(database, _UncitedRegulatoryProvider())).post(
            "/ask", json=_body()
        )
    )
    done = uncited_events[-1][2]
    assert done["verified"] is False
    assert done["reason"] == "regulatory_claim_without_cite"


def test_ask_failure_modes_are_explicit_and_terminal_once(tmp_path: Path) -> None:
    """Provider, retrieval, database, and tool failures do not fabricate text."""
    database = tmp_path / "ask.duckdb"
    _database(database)
    cases = (
        ("provider", _SqlBackend(database, _FailingProvider()), "upstream_error"),
        ("retrieval", _UnavailableCitationBackend(), "unavailable"),
        (
            "database",
            _SqlBackend(tmp_path / "missing.duckdb", _Provider()),
            "unavailable",
        ),
        (
            "tool",
            _SqlBackend(database, _Provider(), query="DROP TABLE mn_summary"),
            "unavailable",
        ),
    )

    for _, backend, expected_code in cases:
        events = _events(_client(database, backend).post("/ask", json=_body()))
        names = [event for _, event, _ in events]
        assert names[0] == "lifecycle"
        assert names[-1] == "error"
        assert names.count("error") == 1
        assert names.count("done") == 0
        assert "text" not in names
        assert events[-1][2]["error"]["code"] == expected_code


def test_ask_reports_unconfigured_provider_after_real_tool_result(
    tmp_path: Path,
) -> None:
    database = tmp_path / "ask.duckdb"
    _database(database)

    response = _client(database, _SqlBackend(database, None)).post("/ask", json=_body())

    events = _events(response)
    assert [event for _, event, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "error",
    ]
    assert events[-1][2]["error"]["code"] == "unavailable"


def test_ask_converts_an_injected_provider_failure_to_one_safe_terminal(
    tmp_path: Path,
) -> None:
    database = tmp_path / "ask.duckdb"
    _database(database)

    events = _events(
        _client(database, _SqlBackend(database, _FailingProvider())).post(
            "/ask", json=_body()
        )
    )

    assert [event for _, event, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "error",
    ]
    assert events[-1][2]["error"] == {
        "code": "upstream_error",
        "message": "The answer provider is unavailable.",
        "retryable": True,
    }


def test_ask_converts_provider_cancellation_to_one_retryable_terminal(
    tmp_path: Path,
) -> None:
    database = tmp_path / "ask.duckdb"
    _database(database)

    events = _events(
        _client(database, _SqlBackend(database, _CancelledProvider())).post(
            "/ask", json=_body()
        )
    )

    assert [seq for seq, _, _ in events] == [1, 2, 3, 4]
    assert events[-1][2]["error"] == {
        "code": "cancelled",
        "message": "The answer attempt was cancelled before it completed.",
        "retryable": True,
    }


def test_ask_preflight_allows_post_without_changing_sse_headers(tmp_path: Path) -> None:
    response = _client(tmp_path / "missing.duckdb", None).options(
        "/ask",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert "POST" in response.headers["Access-Control-Allow-Methods"]
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"


def test_ask_heartbeat_is_a_comment_and_never_an_application_sequence() -> None:
    # The response is configured to emit the documented comment heartbeat.  Its
    # application data still derives only from SseEvent ids, so heartbeats carry
    # no id and cannot advance or fill a v1 sequence.
    assert HEARTBEAT_SECONDS == 15
    heartbeat = _heartbeat().encode().decode().replace("\r\n", "\n")
    assert heartbeat == ": keepalive\n\n"
    assert "id:" not in heartbeat
    events = _events(_client(Path("missing.duckdb"), None).post("/ask", json=_body()))
    assert [seq for seq, _, _ in events] == [1, 2]


def test_ask_live_stream_heartbeats_and_cancels_a_blocked_provider(
    tmp_path: Path, monkeypatch
) -> None:
    """The ASGI response remains live while cooperative provider work blocks."""
    ask_module = importlib.import_module("copilot.routes.ask")

    monkeypatch.setattr(ask_module, "HEARTBEAT_SECONDS", 0.001)

    async def drive() -> list[bytes]:
        lifecycle_sent = asyncio.Event()
        heartbeat_sent = asyncio.Event()
        provider = _BlockingProvider()
        app = create_app(
            Settings(duckdb_path=tmp_path / "missing.duckdb"),
            ask_backend=_ImmediateBackend(provider, lifecycle_sent),
        )
        sent: list[bytes] = []
        received_body = False

        async def receive() -> dict[str, object]:
            nonlocal received_body
            if not received_body:
                received_body = True
                return {
                    "type": "http.request",
                    "body": json.dumps(_body()).encode(),
                    "more_body": False,
                }
            await asyncio.wait_for(heartbeat_sent.wait(), timeout=0.5)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            if message["type"] != "http.response.body":
                return
            body = message.get("body", b"")
            assert isinstance(body, bytes)
            sent.append(body)
            if b"event: lifecycle" in body:
                lifecycle_sent.set()
            if b": keepalive" in body:
                heartbeat_sent.set()

        scope: dict[str, object] = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/ask",
            "raw_path": b"/ask",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        await asyncio.wait_for(app(scope, receive, send), timeout=1)
        assert lifecycle_sent.is_set()
        assert heartbeat_sent.is_set()
        assert provider.started.is_set()
        assert provider.cancelled.is_set()
        return sent

    sent = asyncio.run(drive())
    assert any(b"event: lifecycle" in body for body in sent)
    assert any(b": keepalive" in body for body in sent)
    assert not any(b"event: done" in body for body in sent)


def test_ask_converts_a_cooperative_backend_failure_after_lifecycle(
    tmp_path: Path,
) -> None:
    events = _events(
        _client(tmp_path / "missing.duckdb", _FailingBackend()).post(
            "/ask", json=_body()
        )
    )

    assert [event for _, event, _ in events] == ["lifecycle", "error"]
    assert events[-1][2]["error"] == {
        "code": "tool_error",
        "message": "The local Copilot backend failed.",
        "retryable": False,
    }


def test_ask_exposes_attempt_acknowledgement_to_an_allowed_browser_origin(
    tmp_path: Path,
) -> None:
    response = _client(tmp_path / "missing.duckdb", None).post(
        "/ask",
        json=_body(),
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.headers["X-Flux-Attempt-Id"] == ATTEMPT
    exposed = response.headers["Access-Control-Expose-Headers"].lower()
    assert "x-flux-attempt-id" in exposed


def test_actual_site_score_api_read_is_fixture_labeled_and_non_mutating(
    tmp_path: Path,
) -> None:
    database = tmp_path / "ask.duckdb"
    _database(database)
    before = database.read_bytes()

    response = _client(database, None).post(
        "/site-score",
        json={"site_id": "1", "unit_mw": 300, "scenario_id": "mn_fixture"},
    )

    assert response.status_code == 200
    assert response.json()["safety_score"] == 10.0
    assert response.json()["provenance"]["source_name"] == "fixture"
    assert database.read_bytes() == before


def test_ask_unconfigured_backend_and_resume_are_explicit(tmp_path: Path) -> None:
    response = _client(tmp_path / "missing.duckdb", None).post("/ask", json=_body())
    assert [event for _, event, _ in _events(response)] == ["lifecycle", "error"]
    assert response.headers["X-Flux-Attempt-Id"] == ATTEMPT

    resumed = _client(tmp_path / "missing.duckdb", None).post(
        "/ask", json=_body(), headers={"Last-Event-ID": "2"}
    )
    assert resumed.status_code == 503
    assert resumed.json()["status"] == "unavailable"


def test_ask_rejects_invalid_attempt_history_and_resume_id(tmp_path: Path) -> None:
    client = _client(tmp_path / "missing.duckdb", None)
    assert (
        client.post("/ask", json={"attempt_id": "short", "question": "x"}).status_code
        == 422
    )
    assert (
        client.post(
            "/ask",
            json={
                "attempt_id": ATTEMPT,
                "question": "x",
                "history": [{"role": "tool", "content": "x"}],
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/ask", json=_body(), headers={"Last-Event-ID": "not-an-id"}
        ).status_code
        == 422
    )

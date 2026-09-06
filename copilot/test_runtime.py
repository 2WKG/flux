from asyncio import CancelledError

from copilot.narration import narrate
from copilot.runtime import ToolTurn, run_turn
from copilot.tools.schemas import ArtifactRef, CiteData, RetrievalHit


class FakeProvider:
    def text(self, narration):
        assert narration.status == "available"
        return ("Grounded answer.",)


class CancelledProvider:
    def text(self, narration):
        raise CancelledError


def _turn():
    result = CiteData(
        status="available",
        provenance=[
            ArtifactRef(
                artifact_id="a",
                artifact_version="v1",
                source_kind="retrieval",
                source_ref="r",
            )
        ],
        hits=[
            RetrievalHit(
                content_kind="source",
                date="2026-01-01",
                doc="d",
                locator="p. 1",
                provenance={"retrieved_at": "2026-01-02T00:00:00Z"},
                source="https://example.test/d",
                title="D",
                page=1,
                chunk_id="c",
                score=1.0,
                text="e",
                version="2026-01-01",
            )
        ],
    )
    return ToolTurn("call-1", "cite", {"query": "q"}, narrate("cite", result), 4)


def test_injected_provider_emits_ordered_tool_citation_text_done():
    events = run_turn(FakeProvider(), _turn())
    assert [event.event for event in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "citation",
        "text",
        "done",
    ]
    assert [event.seq for event in events] == list(range(1, 7))
    assert events[3].data["source"] == "https://example.test/d"


def test_missing_provider_is_explicit_unavailable_terminal():
    events = run_turn(None, _turn())
    assert [event.event for event in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "citation",
        "error",
    ]
    assert events[-1].data["error"]["code"] == "unavailable"


def test_cancelled_provider_emits_cancelled_terminal():
    events = run_turn(CancelledProvider(), _turn())
    assert events[-1].event == "error"
    assert events[-1].data["error"]["code"] == "cancelled"

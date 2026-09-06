import json
from asyncio import CancelledError
from types import MappingProxyType

import pytest

from copilot.narration import narrate
from copilot.runtime import ToolTurn, run_turn
from copilot.tools.schemas import (
    ArtifactRef,
    CiteData,
    RetrievalHit,
    Unavailable,
    UnavailableOutput,
)

CITATION_WIRE_FIELDS = {
    "v",
    "seq",
    "citation_id",
    "doc",
    "title",
    "page",
    "chunk_id",
    "locator",
    "excerpt",
    "url",
}


class FakeProvider:
    def text(self, narration):
        assert narration.status == "available"
        return ("Grounded answer.",)


class CancelledProvider:
    def text(self, narration):
        raise CancelledError


class FailingProvider:
    def text(self, narration):
        raise RuntimeError("token=abc123 /secrets/grid.duckdb Traceback")


class ScriptedProvider:
    def __init__(self, *deltas):
        self.deltas = deltas

    def text(self, narration):
        return self.deltas


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
    assert events[4].data["delta"] == "Grounded answer."
    assert events[-1].data == {
        "v": 1,
        "seq": 6,
        "status": "completed",
        "verified": True,
        "unverified_numbers": [],
    }


def test_citation_event_carries_only_the_documented_wire_fields():
    citation = run_turn(FakeProvider(), _turn())[3]

    assert set(citation.data) == CITATION_WIRE_FIELDS
    assert citation.data["citation_id"] == "call-1:cite:1"
    assert citation.data["page"] == 1
    assert citation.data["excerpt"] == "e"
    assert citation.data["url"] == "https://example.test/d"
    # Backend-only retrieval fields never reach the browser.
    encoded = citation.encode()
    assert all(
        f'"{key}"' not in encoded
        for key in ("score", "provenance", "content_kind", "version", "text", "source")
    )


def test_planted_number_makes_the_done_terminal_unverified():
    """Spec 05 acceptance 8: a made-up ``999 MWh`` cannot ship as verified."""
    events = run_turn(
        ScriptedProvider("reduces loss-of-load by ", "999 MWh per 10 CFR 100."), _turn()
    )

    assert [event.event for event in events][-2:] == ["text", "done"]
    assert events[-1].data["verified"] is False
    assert events[-1].data["unverified_numbers"] == ["999"]
    assert "reason" not in events[-1].data  # a cite hit exists in this attempt


def test_regulatory_claim_without_cite_evidence_is_unverified():
    turn = _turn()
    narration = turn.narration
    assert narration.citations  # the fixture cites; strip that evidence
    stripped = ToolTurn(
        turn.call_id,
        turn.tool,
        turn.input,
        type(narration)(
            status=narration.status,
            text=narration.text,
            evidence=narration.evidence,
            provenance=narration.provenance,
            citations=(),
            limitations=narration.limitations,
        ),
        turn.elapsed_ms,
    )

    events = run_turn(ScriptedProvider("The NRC requires a review."), stripped)

    assert events[-1].event == "done"
    assert events[-1].data["verified"] is False
    assert events[-1].data["reason"] == "regulatory_claim_without_cite"


def test_unknown_citation_marker_is_reported_on_done():
    events = run_turn(ScriptedProvider("See [d p.1] and [other p.9]."), _turn())

    assert events[-1].data["verified"] is False
    assert events[-1].data["unverified_citations"] == ["[other p.9]"]


@pytest.mark.parametrize("deltas", [(), ("",), ("", "")])
def test_empty_provider_answer_is_an_explicit_terminal_not_a_verified_done(deltas):
    events = run_turn(ScriptedProvider(*deltas), _turn())

    assert [event.event for event in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "citation",
        "error",
    ]
    assert events[-1].data["error"] == {
        "code": "upstream_error",
        "message": "The model produced no answer.",
        "retryable": True,
    }


def test_tool_unavailable_is_a_failed_tool_result_then_a_fixed_terminal():
    reason = "artifact missing: /secret/path/db.duckdb token=abc123"
    result = UnavailableOutput(
        status="unavailable",
        unavailable=Unavailable(
            code="artifact_unavailable", reason=reason, retryable=True
        ),
    )
    turn = ToolTurn("call-1", "cite", {"query": "q"}, narrate("cite", result), 4)

    events = run_turn(FakeProvider(), turn)

    assert [event.event for event in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "error",
    ]
    assert [event.seq for event in events] == [1, 2, 3, 4]
    assert events[2].data["ok"] is False
    assert events[2].data["call_id"] == "call-1"
    assert events[2].data["error"] == {
        "code": "unavailable",
        "message": "A required data artifact is not available.",
    }
    assert "result" not in events[2].data
    assert events[3].data["error"] == {
        "code": "unavailable",
        "message": "A required tool result is unavailable, so no answer was produced.",
        "retryable": True,
    }
    wire = "".join(event.encode() for event in events)
    assert all(part not in wire for part in ("/secret/", "abc123", reason))


def test_tool_unavailable_retryable_is_propagated_from_the_tool():
    result = UnavailableOutput(
        status="unavailable",
        unavailable=Unavailable(code="insufficient_evidence", reason="none found"),
    )
    turn = ToolTurn("call-1", "cite", {"query": "q"}, narrate("cite", result), 0)

    events = run_turn(FakeProvider(), turn)

    assert events[2].data["error"]["code"] == "tool_error"
    assert events[-1].data["error"]["retryable"] is False


def test_frozen_nested_evidence_is_thawed_before_json_emit():
    turn = _turn()
    narration = turn.narration
    frozen = ToolTurn(
        turn.call_id,
        turn.tool,
        turn.input,
        type(narration)(
            status=narration.status,
            text=narration.text,
            evidence=MappingProxyType(
                {
                    "hits": (
                        MappingProxyType(
                            {"provenance": MappingProxyType({"k": "v"}), "rows": (1,)}
                        ),
                    )
                }
            ),
            provenance=narration.provenance,
            citations=narration.citations,
            limitations=narration.limitations,
        ),
        turn.elapsed_ms,
    )

    result = run_turn(FakeProvider(), frozen)[2]

    assert result.data["result"] == {"hits": [{"provenance": {"k": "v"}, "rows": [1]}]}
    assert json.loads(result.encode().split("data: ", 1)[1])["result"] == {
        "hits": [{"provenance": {"k": "v"}, "rows": [1]}]
    }


def test_immutable_narration_evidence_is_copied_only_for_the_sse_payload():
    turn = _turn()
    assert type(turn.narration.evidence).__name__ == "mappingproxy"

    event = run_turn(FakeProvider(), turn)[2]

    assert isinstance(event.data["result"], dict)
    assert isinstance(event.data["result"]["hits"], list)
    assert (
        json.loads(event.encode().split("data: ", 1)[1])["result"]["hits"][0]["source"]
        == "https://example.test/d"
    )


def test_missing_provider_is_explicit_unavailable_terminal():
    events = run_turn(None, _turn())
    assert [event.event for event in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "citation",
        "error",
    ]
    assert events[-1].data["error"] == {
        "code": "unavailable",
        "message": "No model provider is configured.",
        "retryable": False,
    }


def test_cancelled_provider_emits_cancelled_terminal():
    events = run_turn(CancelledProvider(), _turn())
    assert [event.event for event in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "citation",
        "error",
    ]
    assert [event.seq for event in events] == list(range(1, 6))
    assert events[-1].event == "error"
    assert events[-1].data["error"]["code"] == "cancelled"
    assert events[-1].data["error"]["retryable"] is True


def test_provider_failure_emits_one_ordered_error_terminal():
    events = run_turn(FailingProvider(), _turn())
    assert [event.event for event in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "citation",
        "error",
    ]
    assert [event.seq for event in events] == list(range(1, 6))
    assert events[-1].data["error"] == {
        "code": "upstream_error",
        "message": "The answer provider is unavailable.",
        "retryable": True,
    }
    wire = "".join(event.encode() for event in events)
    assert all(part not in wire for part in ("abc123", "/secrets/", "Traceback"))

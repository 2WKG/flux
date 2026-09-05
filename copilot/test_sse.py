"""Focused unit tests for lifecycle and successful tool SSE emission."""

from __future__ import annotations

import json

import pytest

from copilot.sse import CopilotEventStream, StreamStateError


def test_lifecycle_start_is_the_first_versioned_event() -> None:
    stream = CopilotEventStream()

    event = stream.start()

    assert event.event == "lifecycle"
    assert event.seq == 1
    assert event.data == {"v": 1, "seq": 1, "status": "started"}
    assert event.encode() == (
        'id: 1\nevent: lifecycle\ndata: {"v":1,"seq":1,"status":"started"}\n\n'
    )


def test_tool_call_and_result_are_ordered_and_correlated() -> None:
    stream = CopilotEventStream()
    start = stream.start()
    call = stream.tool_call(
        "call-site-1", "score_site", {"site_id": "site_tx_0007", "unit_mw": 300}
    )
    result = stream.tool_result(
        "call-site-1",
        "score_site",
        {"site_id": "site_tx_0007", "grid_value_score": 82.1},
        elapsed_ms=124,
    )

    assert [event.seq for event in (start, call, result)] == [1, 2, 3]
    assert call.data["input"] == {"site_id": "site_tx_0007", "unit_mw": 300}
    assert result.data == {
        "v": 1,
        "seq": 3,
        "call_id": "call-site-1",
        "tool": "score_site",
        "ok": True,
        "result": {"site_id": "site_tx_0007", "grid_value_score": 82.1},
        "elapsed_ms": 124,
    }
    assert json.loads(result.encode().split("data: ", 1)[1]) == dict(result.data)


def test_result_requires_its_matching_prior_tool_call() -> None:
    stream = CopilotEventStream()
    stream.start()
    stream.tool_call("call-1", "score_site", {"site_id": "site_tx_0007"})

    with pytest.raises(StreamStateError, match="expected 'score_site'"):
        stream.tool_result("call-1", "top_lines", {}, elapsed_ms=1)
    with pytest.raises(StreamStateError, match="no pending tool call"):
        stream.tool_result("missing", "score_site", {}, elapsed_ms=1)


def test_done_is_the_single_successful_terminal_event() -> None:
    stream = CopilotEventStream()
    stream.start()

    done = stream.done(verified=False, unverified_numbers=["999"])

    assert done.seq == 2
    assert done.data == {
        "v": 1,
        "seq": 2,
        "status": "completed",
        "verified": False,
        "unverified_numbers": ["999"],
    }
    with pytest.raises(StreamStateError, match="terminal"):
        stream.done(verified=True)
    with pytest.raises(StreamStateError, match="terminal"):
        stream.tool_call("call-late", "score_site", {})


def test_lifecycle_start_is_emitted_only_once() -> None:
    stream = CopilotEventStream()
    stream.start()

    with pytest.raises(StreamStateError, match="only once"):
        stream.start()
    # The rejected second start must not have advanced the stream.
    assert stream.done(verified=True).seq == 2


def test_events_before_lifecycle_start_are_rejected() -> None:
    stream = CopilotEventStream()

    with pytest.raises(StreamStateError, match="lifecycle start"):
        stream.tool_call("call-early", "score_site", {})
    with pytest.raises(StreamStateError, match="lifecycle start"):
        stream.tool_result("call-early", "score_site", {}, elapsed_ms=1)
    with pytest.raises(StreamStateError, match="lifecycle start"):
        stream.done(verified=True)
    # Nothing leaked into the sequence: start is still event 1.
    assert stream.start().seq == 1


def test_done_refuses_while_tool_calls_are_pending() -> None:
    stream = CopilotEventStream()
    stream.start()
    stream.tool_call("call-1", "score_site", {"site_id": "site_tx_0007"})

    with pytest.raises(StreamStateError, match="pending"):
        stream.done(verified=True)

    # Settling the call re-opens the successful terminal.
    stream.tool_result("call-1", "score_site", {}, elapsed_ms=1)
    assert stream.done(verified=True).event == "done"


def test_duplicate_pending_call_id_is_rejected() -> None:
    stream = CopilotEventStream()
    stream.start()
    stream.tool_call("call-1", "score_site", {"site_id": "site_tx_0007"})

    with pytest.raises(StreamStateError, match="already emitted"):
        stream.tool_call("call-1", "top_lines", {"region": "ERCOT"})
    # The rejected duplicate did not replace the pending call's tool binding.
    with pytest.raises(StreamStateError, match="expected 'score_site'"):
        stream.tool_result("call-1", "top_lines", {}, elapsed_ms=1)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_are_rejected_at_construction(bad: float) -> None:
    """Malformed payloads fail when the event is built, never at encode time."""
    stream = CopilotEventStream()
    stream.start()
    stream.tool_call("call-1", "score_site", {"site_id": "site_tx_0007"})

    with pytest.raises(ValueError):
        stream.tool_result("call-1", "score_site", {"score": bad}, elapsed_ms=1)


def test_rejected_payload_does_not_commit_tool_state_or_sequence() -> None:
    stream = CopilotEventStream()
    stream.start()

    with pytest.raises(ValueError):
        stream.tool_call("call-1", "score_site", {"score": float("nan")})
    call = stream.tool_call("call-1", "score_site", {})
    assert call.seq == 2

    with pytest.raises(ValueError):
        stream.tool_result("call-1", "score_site", {"score": float("nan")}, elapsed_ms=1)
    result = stream.tool_result("call-1", "score_site", {}, elapsed_ms=1)
    assert result.seq == 3
    assert stream.done(verified=True).seq == 4

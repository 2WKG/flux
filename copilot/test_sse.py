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


@pytest.mark.parametrize(
    ("method", "code", "message", "retryable"),
    [
        (
            "disconnected",
            "cancelled",
            "The answer attempt was cancelled before it completed.",
            True,
        ),
        (
            "timed_out",
            "deadline",
            "The answer could not finish within the request deadline.",
            True,
        ),
        (
            "provider_failed",
            "upstream_error",
            "The answer provider is unavailable.",
            True,
        ),
        (
            "refused",
            "refusal",
            "The answer provider declined this request.",
            False,
        ),
        (
            "iteration_limit_reached",
            "deadline",
            "The answer reached its iteration limit.",
            False,
        ),
    ],
)
def test_named_failures_emit_one_safe_terminal_error(
    method: str, code: str, message: str, retryable: bool
) -> None:
    stream = CopilotEventStream()
    stream.start()
    secret_failure = RuntimeError("token=abc123 /secrets/grid.duckdb Traceback")

    event = getattr(stream, method)(secret_failure)

    assert event.event == "error"
    assert event.seq == 2
    assert event.data == {
        "v": 1,
        "seq": 2,
        "status": "failed",
        "error": {"code": code, "message": message, "retryable": retryable},
    }
    serialized = event.encode()
    assert all(
        value not in serialized for value in ("abc123", "/secrets/", "Traceback")
    )
    with pytest.raises(StreamStateError, match="terminal"):
        stream.done(verified=True)


TOOL_TIMEOUT_MESSAGE = "The site scoring tool did not finish in time."


def test_failed_tool_result_is_non_terminal() -> None:
    """A failing tool reports `ok: false` and the answer attempt continues."""
    stream = CopilotEventStream()
    stream.start()
    stream.tool_call("call-1", "score_site", {"site_id": "site_tx_0007"})

    failed = stream.failed_tool_result(
        "call-1", "score_site", "timeout", TOOL_TIMEOUT_MESSAGE, elapsed_ms=5000
    )

    assert failed.event == "tool_result"
    assert failed.data == {
        "v": 1,
        "seq": 3,
        "call_id": "call-1",
        "tool": "score_site",
        "ok": False,
        "error": {"code": "timeout", "message": TOOL_TIMEOUT_MESSAGE},
        "elapsed_ms": 5000,
    }
    # `error` replaces `result`; a failed call never carries a plausible value.
    assert "result" not in failed.data

    # The turn stays viable: a later call, its result, and `done` all succeed.
    stream.tool_call("call-2", "top_lines", {"region": "ERCOT"})
    stream.tool_result("call-2", "top_lines", {"lines": []}, elapsed_ms=100)
    done = stream.done(verified=False)

    assert done.seq == 6
    assert done.data["status"] == "completed"

"""Focused unit tests for lifecycle and successful tool SSE emission."""

from __future__ import annotations

import json

import pytest

from copilot.sse import CopilotEventStream, SseEvent, StreamStateError


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
    # The failure is the one and only terminal: neither success nor a second
    # failure may follow it.
    with pytest.raises(StreamStateError, match="terminal"):
        stream.done(verified=True)
    with pytest.raises(StreamStateError, match="terminal"):
        getattr(stream, method)()
    with pytest.raises(StreamStateError, match="terminal"):
        stream.disconnected()

    # And a failure cannot follow the success terminal either.
    finished = CopilotEventStream()
    finished.start()
    finished.done(verified=True)
    with pytest.raises(StreamStateError, match="terminal"):
        getattr(finished, method)(secret_failure)


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


def test_failed_tool_result_requires_lifecycle_start() -> None:
    stream = CopilotEventStream()

    with pytest.raises(StreamStateError, match="lifecycle start"):
        stream.failed_tool_result(
            "call-1", "score_site", "timeout", TOOL_TIMEOUT_MESSAGE, elapsed_ms=1
        )


@pytest.mark.parametrize("code", ["", "TIMEOUT", "boom", "upstream_error", "cancelled"])
def test_failed_tool_result_rejects_codes_outside_the_vocabulary(code: str) -> None:
    stream = CopilotEventStream()
    stream.start()
    stream.tool_call("call-1", "score_site", {"site_id": "site_tx_0007"})

    with pytest.raises(ValueError, match="unsupported tool error code"):
        stream.failed_tool_result(
            "call-1", "score_site", code, TOOL_TIMEOUT_MESSAGE, elapsed_ms=1
        )
    # The rejected payload did not consume the pending call.
    settled = stream.failed_tool_result(
        "call-1", "score_site", "timeout", TOOL_TIMEOUT_MESSAGE, elapsed_ms=1
    )
    assert settled.data["error"]["code"] == "timeout"
    assert settled.seq == 3


@pytest.mark.parametrize(
    "code", sorted(["timeout", "invalid_input", "unavailable", "tool_error"])
)
def test_failed_tool_result_accepts_each_vocabulary_code(code: str) -> None:
    stream = CopilotEventStream()
    stream.start()
    stream.tool_call("call-1", "score_site", {})

    failed = stream.failed_tool_result(
        "call-1", "score_site", code, TOOL_TIMEOUT_MESSAGE, elapsed_ms=1
    )

    assert failed.data["ok"] is False
    assert failed.data["error"] == {"code": code, "message": TOOL_TIMEOUT_MESSAGE}


def test_failed_tool_result_bounds_the_message_length() -> None:
    stream = CopilotEventStream()
    stream.start()
    stream.tool_call("call-1", "score_site", {})

    with pytest.raises(ValueError, match="1..1024 characters"):
        stream.failed_tool_result("call-1", "score_site", "timeout", "", elapsed_ms=1)
    with pytest.raises(ValueError, match="1..1024 characters"):
        stream.failed_tool_result(
            "call-1", "score_site", "timeout", "x" * 1025, elapsed_ms=1
        )
    with pytest.raises(ValueError, match="non-negative"):
        stream.failed_tool_result(
            "call-1", "score_site", "timeout", TOOL_TIMEOUT_MESSAGE, elapsed_ms=-1
        )

    # Exactly the cap is accepted, and the earlier rejections left the call pending.
    failed = stream.failed_tool_result(
        "call-1", "score_site", "timeout", "x" * 1024, elapsed_ms=1
    )
    assert len(failed.data["error"]["message"]) == 1024
    assert failed.seq == 3


def test_complete_success_stream_has_contiguous_matching_sse_ids_and_one_terminal() -> (
    None
):
    stream = CopilotEventStream()
    events = [
        stream.start(),
        stream.tool_call("call-site", "score_site", {"site_id": "site_tx_0007"}),
        stream.tool_call("call-lines", "top_lines", {"region": "ERCOT"}),
        stream.tool_result("call-lines", "top_lines", {"lines": []}, elapsed_ms=4),
        stream.tool_result(
            "call-site", "score_site", {"site_id": "site_tx_0007"}, elapsed_ms=8
        ),
        stream.done(verified=True),
    ]

    consumed = [_consume(event) for event in events]

    assert [record["id"] for record in consumed] == ["1", "2", "3", "4", "5", "6"]
    assert [record["event"] for record in consumed] == [
        "lifecycle",
        "tool_call",
        "tool_call",
        "tool_result",
        "tool_result",
        "done",
    ]
    assert [record["data"]["seq"] for record in consumed] == [1, 2, 3, 4, 5, 6]
    call_positions = {
        record["data"]["call_id"]: index
        for index, record in enumerate(consumed)
        if record["event"] == "tool_call"
    }
    for index, record in enumerate(consumed):
        if record["event"] == "tool_result":
            assert call_positions[record["data"]["call_id"]] < index
    assert [record for record in consumed if record["event"] in {"done", "error"}] == [
        consumed[-1]
    ]


@pytest.mark.parametrize(
    ("method", "expected_code"),
    [
        ("disconnected", "cancelled"),
        ("timed_out", "deadline"),
        ("provider_failed", "upstream_error"),
    ],
)
def test_failure_streams_have_exactly_one_terminal_error(
    method: str, expected_code: str
) -> None:
    stream = CopilotEventStream()
    events = [stream.start(), getattr(stream, method)()]
    consumed = [_consume(event) for event in events]

    terminal = [record for record in consumed if record["event"] in {"done", "error"}]
    assert len(terminal) == 1
    assert terminal[0]["event"] == "error"
    assert terminal[0]["data"]["error"]["code"] == expected_code
    with pytest.raises(StreamStateError, match="terminal"):
        stream.tool_call("call-after-error", "score_site", {})


def _consume(event: SseEvent) -> dict[str, object]:
    """Parse a complete SSE record as a client would, without framework helpers."""
    encoded = event.encode()
    lines = encoded.splitlines()
    assert lines[-1] == ""
    fields = dict(line.split(": ", 1) for line in lines[:-1])
    return {
        "id": fields["id"],
        "event": fields["event"],
        "data": json.loads(fields["data"]),
    }

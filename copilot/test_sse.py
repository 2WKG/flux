"""Focused unit tests for lifecycle and successful tool SSE emission."""

from __future__ import annotations

import json
from types import MappingProxyType

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


def test_rejected_payload_does_not_commit_tool_state_or_sequence() -> None:
    stream = CopilotEventStream()
    stream.start()

    with pytest.raises(ValueError):
        stream.tool_call("call-1", "score_site", {"score": float("nan")})
    call = stream.tool_call("call-1", "score_site", {})
    assert call.seq == 2

    with pytest.raises(ValueError):
        stream.tool_result(
            "call-1", "score_site", {"score": float("nan")}, elapsed_ms=1
        )
    result = stream.tool_result("call-1", "score_site", {}, elapsed_ms=1)
    assert result.seq == 3
    assert stream.done(verified=True).seq == 4


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
    with pytest.raises(StreamStateError, match="terminal"):
        getattr(stream, method)()
    with pytest.raises(StreamStateError, match="terminal"):
        stream.disconnected()

    finished = CopilotEventStream()
    finished.start()
    finished.done(verified=True)
    with pytest.raises(StreamStateError, match="terminal"):
        getattr(finished, method)(secret_failure)


def test_failed_tool_result_is_non_terminal_and_settles_the_pending_call() -> None:
    stream = CopilotEventStream()
    stream.start()
    stream.tool_call("call-1", "score_site", {"site_id": "site_tx_0007"})

    event = stream.failed_tool_result(
        "call-1",
        "score_site",
        "tool_error",
        "The tool could not complete.",
        elapsed_ms=1,
    )

    assert event.event == "tool_result"
    assert event.data["ok"] is False
    assert event.data["error"] == {
        "code": "tool_error",
        "message": "The tool could not complete.",
    }
    assert stream.done(verified=True).event == "done"


def test_complete_success_stream_has_contiguous_matching_sse_ids_and_one_terminal() -> (
    None
):
    stream = CopilotEventStream()
    events = [stream.start()]

    # A result for a call that has not been emitted yet is rejected by the
    # emitter, not merely absent from the list this test builds.
    with pytest.raises(StreamStateError, match="no pending tool call"):
        stream.tool_result("call-lines", "top_lines", {"lines": []}, elapsed_ms=4)

    events += [
        stream.tool_call("call-site", "score_site", {"site_id": "site_tx_0007"}),
        stream.tool_call("call-lines", "top_lines", {"region": "ERCOT"}),
    ]
    # Calls may complete out of order, but each result must name a call that
    # is still pending; a settled call cannot be reported twice.
    events.append(
        stream.tool_result("call-lines", "top_lines", {"lines": []}, elapsed_ms=4)
    )
    with pytest.raises(StreamStateError, match="no pending tool call"):
        stream.tool_result("call-lines", "top_lines", {"lines": []}, elapsed_ms=4)
    # The stream cannot finish while `call-site` is still pending.
    with pytest.raises(StreamStateError, match="pending"):
        stream.done(verified=True)
    events += [
        stream.tool_result(
            "call-site", "score_site", {"site_id": "site_tx_0007"}, elapsed_ms=8
        ),
        stream.done(verified=True),
    ]

    consumed = [_consume(event) for event in events]

    # The rejected attempts consumed no ids: the wire sequence is contiguous.
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
    assert [
        record["data"]["call_id"]
        for record in consumed
        if record["event"] == "tool_call"
    ] == ["call-site", "call-lines"]
    assert [
        record["data"]["call_id"]
        for record in consumed
        if record["event"] == "tool_result"
    ] == ["call-lines", "call-site"]
    assert [record for record in consumed if record["event"] in {"done", "error"}] == [
        consumed[-1]
    ]
    # `done` is the one terminal: no failure terminal may follow it.
    with pytest.raises(StreamStateError, match="terminal"):
        stream.disconnected()
    with pytest.raises(StreamStateError, match="terminal"):
        stream.done(verified=True)


def test_success_terminal_rejects_a_later_disconnect() -> None:
    """start(); done(); disconnected() must not produce a second terminal record."""
    stream = CopilotEventStream()
    events = [stream.start(), stream.done(verified=True)]

    with pytest.raises(StreamStateError, match="terminal"):
        events.append(stream.disconnected(RuntimeError("client went away")))

    consumed = [_consume(event) for event in events]
    assert [record["event"] for record in consumed] == ["lifecycle", "done"]
    assert [record["id"] for record in consumed] == ["1", "2"]


@pytest.mark.parametrize(
    ("method", "expected_code"),
    [
        ("disconnected", "cancelled"),
        ("timed_out", "deadline"),
        ("provider_failed", "upstream_error"),
        ("refused", "refusal"),
        ("iteration_limit_reached", "deadline"),
    ],
)
def test_failure_streams_have_exactly_one_terminal_error(
    method: str, expected_code: str
) -> None:
    stream = CopilotEventStream()
    events = [
        stream.start(),
        stream.tool_call("call-site", "score_site", {"site_id": "site_tx_0007"}),
        getattr(stream, method)(),
    ]

    # Every further terminal or application event is rejected on the wire.
    with pytest.raises(StreamStateError, match="terminal"):
        events.append(stream.done(verified=True))
    with pytest.raises(StreamStateError, match="terminal"):
        events.append(getattr(stream, method)())
    with pytest.raises(StreamStateError, match="terminal"):
        events.append(stream.tool_call("call-after-error", "score_site", {}))
    with pytest.raises(StreamStateError, match="terminal"):
        events.append(stream.tool_result("call-site", "score_site", {}, elapsed_ms=1))

    consumed = [_consume(event) for event in events]
    assert [record["event"] for record in consumed] == [
        "lifecycle",
        "tool_call",
        "error",
    ]
    assert [record["id"] for record in consumed] == ["1", "2", "3"]
    terminal = [record for record in consumed if record["event"] in {"done", "error"}]
    assert terminal == [consumed[-1]]
    assert terminal[0]["data"]["error"]["code"] == expected_code


def _consume(event: SseEvent) -> dict[str, object]:
    """Parse a complete SSE record as a client would, without framework helpers."""
    encoded = event.encode()
    assert encoded.endswith("\n\n")
    lines = encoded[:-2].split("\n")
    fields = dict(line.split(": ", 1) for line in lines)
    return {
        "id": fields["id"],
        "event": fields["event"],
        "data": json.loads(fields["data"]),
    }


CITATION_HIT = {
    "doc": "10-cfr-part-100.pdf",
    "title": "10 CFR Part 100",
    "page": 12,
    "chunk_id": "10cfr100-p12-c2",
    "locator": "§ 100.10",
    "excerpt": "…",
    "url": None,
}


def test_text_emits_a_non_empty_delta() -> None:
    stream = CopilotEventStream()
    stream.start()

    with pytest.raises(ValueError, match="must not be empty"):
        stream.text("")
    event = stream.text("A county-level ")

    assert event.event == "text"
    assert event.data == {"v": 1, "seq": 2, "delta": "A county-level "}


def test_citation_emits_exactly_the_documented_wire_shape() -> None:
    stream = CopilotEventStream()
    stream.start()

    event = stream.citation("cite_1", CITATION_HIT)

    assert event.event == "citation"
    assert event.data == {"v": 1, "seq": 2, "citation_id": "cite_1", **CITATION_HIT}
    assert list(event.data)[:3] == ["v", "seq", "citation_id"]


@pytest.mark.parametrize("missing", ["doc", "title", "chunk_id"])
def test_citation_requires_non_empty_string_identity_fields(missing: str) -> None:
    stream = CopilotEventStream()
    stream.start()

    for bad in ("", None, 7):
        with pytest.raises(ValueError, match=f"non-empty string {missing!r}"):
            stream.citation("cite_1", {**CITATION_HIT, missing: bad})
    with pytest.raises(ValueError, match=f"non-empty string {missing!r}"):
        hit = dict(CITATION_HIT)
        del hit[missing]
        stream.citation("cite_1", hit)
    # Rejections consumed no sequence number.
    assert stream.citation("cite_1", CITATION_HIT).seq == 2


@pytest.mark.parametrize("page", ["12", 0, -1, True, None, 1.0])
def test_citation_page_must_be_a_positive_integer(page: object) -> None:
    stream = CopilotEventStream()
    stream.start()

    with pytest.raises(ValueError, match="positive integer page"):
        stream.citation("cite_1", {**CITATION_HIT, "page": page})


def test_citation_id_must_be_a_unique_non_empty_string() -> None:
    stream = CopilotEventStream()
    stream.start()

    with pytest.raises(ValueError, match="citation_id"):
        stream.citation("", CITATION_HIT)
    with pytest.raises(ValueError, match="citation_id"):
        stream.citation(7, CITATION_HIT)  # type: ignore[arg-type]
    stream.citation("cite_1", CITATION_HIT)
    with pytest.raises(StreamStateError, match="already emitted"):
        stream.citation("cite_1", CITATION_HIT)
    assert stream.citation("cite_2", CITATION_HIT).seq == 3


@pytest.mark.parametrize(
    "extra",
    [
        {"v": 7},
        {"seq": 999},
        {"citation_id": "spoof"},
        {"score": 0.9},
        {"text": "raw chunk"},
        {"source": "https://example.test"},
        {"provenance": {"retrieved_at": "x"}},
    ],
)
def test_citation_rejects_undocumented_and_envelope_fields(
    extra: dict[str, object],
) -> None:
    """A hit can neither leak backend fields nor overwrite ``v``/``seq``/``citation_id``."""
    stream = CopilotEventStream()
    stream.start()

    with pytest.raises(ValueError, match="undocumented fields"):
        stream.citation("cite_1", {**CITATION_HIT, **extra})
    event = stream.citation("cite_1", CITATION_HIT)
    assert (event.data["v"], event.data["seq"], event.data["citation_id"]) == (
        1,
        2,
        "cite_1",
    )


def test_citation_optional_fields_are_string_or_null_and_excerpt_is_capped() -> None:
    stream = CopilotEventStream()
    stream.start()

    for key in ("locator", "excerpt", "url"):
        with pytest.raises(ValueError, match=f"{key!r} must be a string or null"):
            stream.citation("cite_1", {**CITATION_HIT, key: 12})
    minimal = {key: CITATION_HIT[key] for key in ("doc", "title", "page", "chunk_id")}
    event = stream.citation("cite_1", minimal)
    assert (event.data["locator"], event.data["excerpt"], event.data["url"]) == (
        None,
        None,
        None,
    )

    long = stream.citation("cite_2", {**CITATION_HIT, "excerpt": "x" * 1201})
    assert len(long.data["excerpt"]) == 1200
    assert long.data["excerpt_truncated"] is True
    exact = stream.citation("cite_3", {**CITATION_HIT, "excerpt": "x" * 1200})
    assert "excerpt_truncated" not in exact.data


def test_citation_requires_an_active_stream() -> None:
    stream = CopilotEventStream()
    with pytest.raises(StreamStateError, match="lifecycle start"):
        stream.citation("cite_1", CITATION_HIT)
    stream.start()
    stream.done(verified=True)
    with pytest.raises(StreamStateError, match="terminal"):
        stream.citation("cite_1", CITATION_HIT)


@pytest.mark.parametrize(
    "code", ["", "banana", "api_error", "UNAVAILABLE", "timeout", "invalid_input"]
)
def test_error_rejects_codes_outside_the_closed_v1_set(code: str) -> None:
    stream = CopilotEventStream()
    stream.start()

    with pytest.raises(ValueError, match="unsupported error code"):
        stream.error(code, "A safe message.", retryable=False)
    # The rejected terminal left the stream open and consumed no sequence number.
    assert stream.done(verified=True).seq == 2


@pytest.mark.parametrize(
    "code",
    sorted(
        [
            "invalid_request",
            "unavailable",
            "deadline",
            "upstream_error",
            "tool_error",
            "refusal",
            "cancelled",
            "protocol_error",
        ]
    ),
)
def test_error_accepts_each_closed_v1_code_as_the_one_terminal(code: str) -> None:
    stream = CopilotEventStream()
    stream.start()
    stream.tool_call("call-1", "score_site", {"site_id": "site_tx_0007"})

    event = stream.error(code, "A safe message.", retryable=True)

    assert event.event == "error"
    assert event.data == {
        "v": 1,
        "seq": 3,
        "status": "failed",
        "error": {"code": code, "message": "A safe message.", "retryable": True},
    }
    # ``error`` closes the stream: the abandoned call cannot be settled and no
    # second terminal or application event may follow.
    with pytest.raises(StreamStateError, match="terminal"):
        stream.tool_result("call-1", "score_site", {}, elapsed_ms=1)
    with pytest.raises(StreamStateError, match="terminal"):
        stream.done(verified=True)
    with pytest.raises(StreamStateError, match="terminal"):
        stream.error(code, "A safe message.", retryable=True)
    with pytest.raises(StreamStateError, match="terminal"):
        stream.text("late")


def test_error_bounds_the_message_and_requires_an_active_stream() -> None:
    stream = CopilotEventStream()
    with pytest.raises(StreamStateError, match="lifecycle start"):
        stream.error("unavailable", "A safe message.", retryable=False)
    stream.start()

    with pytest.raises(ValueError, match="1..1024 characters"):
        stream.error("unavailable", "", retryable=False)
    with pytest.raises(ValueError, match="1..1024 characters"):
        stream.error("unavailable", "x" * 1025, retryable=False)
    event = stream.error("unavailable", "x" * 1024, retryable=False)
    assert event.seq == 2
    assert event.data["error"]["retryable"] is False

    finished = CopilotEventStream()
    finished.start()
    finished.done(verified=True)
    with pytest.raises(StreamStateError, match="terminal"):
        finished.error("unavailable", "A safe message.", retryable=False)


def test_done_reports_unverified_findings_only_when_unverified() -> None:
    stream = CopilotEventStream()
    stream.start()

    with pytest.raises(ValueError, match="verified answer cannot carry"):
        stream.done(verified=True, unverified_numbers=["999"])
    with pytest.raises(ValueError, match="verified answer cannot carry"):
        stream.done(verified=True, unverified_citations=["[d p.1]"])
    with pytest.raises(ValueError, match="verified answer cannot carry"):
        stream.done(verified=True, reason="regulatory_claim_without_cite")
    with pytest.raises(ValueError, match="unverified_numbers must not contain"):
        stream.done(verified=False, unverified_numbers=[""])
    with pytest.raises(ValueError, match="unverified_numbers must not contain"):
        stream.done(verified=False, unverified_numbers=["999", ""])
    with pytest.raises(ValueError, match="unverified_citations must not contain"):
        stream.done(verified=False, unverified_citations=[""])

    done = stream.done(
        verified=False,
        unverified_numbers=["999"],
        unverified_citations=["[d p.1]"],
        reason="regulatory_claim_without_cite",
    )
    assert done.data == {
        "v": 1,
        "seq": 2,
        "status": "completed",
        "verified": False,
        "unverified_numbers": ["999"],
        "unverified_citations": ["[d p.1]"],
        "reason": "regulatory_claim_without_cite",
    }


def test_nested_immutable_tool_payload_is_normalized_at_the_sse_boundary() -> None:
    stream = CopilotEventStream()
    stream.start()
    payload = MappingProxyType(
        {"nested": MappingProxyType({"values": ("one", MappingProxyType({"two": 2}))})}
    )

    event = stream.tool_call("call-1", "score_site", payload)

    assert event.data["input"] == {"nested": {"values": ["one", {"two": 2}]}}
    assert json.loads(event.encode().split("data: ", 1)[1]) == dict(event.data)

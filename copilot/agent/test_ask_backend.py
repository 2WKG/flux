"""Proof that `POST /ask` can answer, and that it refuses honestly when it cannot.

Before this unit `create_app` left `app.state.ask_backend` at `None`, so the
route emitted its unavailable terminal no matter how the provider was
configured and the chat dock could never answer.  These tests drive the real
route, the real `create_app` wiring, the real frozen input contract, and the
real persisted `top_lines` executor against a real DuckDB fixture built through
the production DDL.  Only two things are stubbed, both at the provider seam:
which tool the model picks, and the prose it streams back.

There is no API key in this checkout, so a live model call is not exercised
anywhere here and none is claimed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from copilot.agent.loop import PLANNING_STEP_TOOL, LocalToolBackend, build_ask_backend
from copilot.agent.registry import RegisteredTool, build_tool_registry
from copilot.app import create_app
from copilot.config import Settings
from copilot.narration import GroundedNarration
from copilot.persisted_fixtures import persisted_lines_database
from copilot.providers import tools_for
from copilot.providers.selection import ToolSelection
from copilot.routes.ask import AskRequest

ATTEMPT = "attempt_0123456789"
UNCONFIGURED_MESSAGE = "The local Copilot backend is not configured."
TOOL_UNAVAILABLE_MESSAGE = (
    "A required tool result is unavailable, so no answer was produced."
)

_PROVIDER_ENV = (
    "COPILOT_PROVIDER",
    "COPILOT_MODEL",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "gemini-api-key",
)


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's own credential must not decide any outcome below."""
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


class _PlanningProvider:
    """A provider seam: it plans a fixed tool call and narrates fixed prose.

    It implements both halves of the real contract (`select_tool` and `text`)
    so the loop, the registry, the executor and the stream are the code under
    test and only the model is replaced.
    """

    name = "gemini"
    model = "gemini-3.8-flash"

    def __init__(self, selection: ToolSelection | None) -> None:
        self._selection = selection
        self.narrated: list[Mapping[str, object]] = []
        self.tools_seen: tuple[str, ...] = ()

    async def select_tool(
        self,
        question: str,
        *,
        tools: Sequence[Mapping[str, Any]],
        context: Mapping[str, Any] | None = None,
        history: Sequence[Mapping[str, str]] = (),
    ) -> ToolSelection | None:
        self.tools_seen = tuple(str(tool["name"]) for tool in tools)
        return self._selection

    async def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        self.narrated.append(narration.evidence)
        yield "The persisted ranking is reported above."


class _NarrationOnlyProvider:
    """The pre-#277-shaped provider: it can restate evidence but not plan."""

    name = "gemini"
    model = "gemini-3.8-flash"

    async def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        yield "unreachable"  # pragma: no cover - never reached without a backend


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _events(response: Any) -> list[tuple[int, str, dict[str, Any]]]:
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


def _ask(app: Any, question: str = "Which Minnesota lines should we upgrade?") -> Any:
    return TestClient(app).post(
        "/ask", json={"attempt_id": ATTEMPT, "question": question}
    )


def _lines_database(path: Path) -> Path:
    persisted_lines_database(path)
    return path


TOP_LINES_CALL = ToolSelection("top_lines", {"region": "MN", "tech": "any", "n": 3})


# --- the factory exists and is called by create_app -------------------------


def test_create_app_builds_a_production_ask_backend_from_configuration(
    tmp_path: Path,
) -> None:
    """The gap this unit closes: nothing in production assigned this state."""
    provider = _PlanningProvider(TOP_LINES_CALL)

    app = create_app(
        _settings(duckdb_path=_lines_database(tmp_path / "lines.duckdb")),
        narration_provider=provider,
    )

    backend = app.state.ask_backend
    assert isinstance(backend, LocalToolBackend)
    assert backend.provider is provider


def test_ask_answers_end_to_end_through_the_app_built_backend(tmp_path: Path) -> None:
    """The whole point: a configured deployment reaches `done`, not `error`."""
    provider = _PlanningProvider(TOP_LINES_CALL)
    app = create_app(
        _settings(duckdb_path=_lines_database(tmp_path / "lines.duckdb")),
        narration_provider=provider,
    )

    events = _events(_ask(app))

    assert [name for _, name, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "text",
        "done",
    ]
    assert [seq for seq, _, _ in events] == [1, 2, 3, 4, 5]
    assert events[1][2]["tool"] == "top_lines"
    result = events[2][2]["result"]
    assert result["region"] == "MN"
    assert result["scenario_id"] == "mn_fixture"
    # Real persisted rows, read by the production `TopLinesReader` from a
    # database built through the production DDL.
    assert [line["line_id"] for line in result["lines"]] == ["11", "10", "12"]
    # The provider was handed that same evidence and nothing else.
    assert provider.narrated[0]["lines"][0]["line_id"] == "11"


def test_the_backend_only_ever_offers_tools_it_can_run(tmp_path: Path) -> None:
    provider = _PlanningProvider(TOP_LINES_CALL)
    app = create_app(
        _settings(duckdb_path=_lines_database(tmp_path / "lines.duckdb")),
        narration_provider=provider,
    )

    _ask(app)

    assert set(provider.tools_seen) == set(build_tool_registry(app.state.settings))


# --- honesty: an unconfigured deployment says so, in the same words ---------


def test_a_keyless_deployment_still_emits_the_named_unavailable_terminal(
    tmp_path: Path,
) -> None:
    """No credential means no backend, and the exact terminal master emits.

    This is the invariant the whole change is bounded by: wiring a factory must
    not turn "we cannot answer" into a plausible answer.
    """
    app = create_app(
        _settings(
            copilot_provider="gemini",
            duckdb_path=_lines_database(tmp_path / "lines.duckdb"),
        )
    )

    assert app.state.narration_provider is None
    assert app.state.ask_backend is None

    events = _events(_ask(app))

    assert [(seq, name) for seq, name, _ in events] == [(1, "lifecycle"), (2, "error")]
    assert events[-1][2]["error"] == {
        "code": "unavailable",
        "message": UNCONFIGURED_MESSAGE,
        "retryable": False,
    }
    assert "text" not in {name for _, name, _ in events}


def test_a_narration_only_provider_cannot_ground_an_answer(tmp_path: Path) -> None:
    """Choosing the tool locally to "make it work" is the forbidden default."""
    settings = _settings(duckdb_path=_lines_database(tmp_path / "lines.duckdb"))

    assert build_ask_backend(settings, _NarrationOnlyProvider()) is None
    assert build_ask_backend(settings, None) is None


# --- honesty: every failure to find evidence is a named refusal -------------


def test_a_planner_that_chooses_no_tool_refuses_under_its_own_name(
    tmp_path: Path,
) -> None:
    app = create_app(
        _settings(duckdb_path=_lines_database(tmp_path / "lines.duckdb")),
        narration_provider=_PlanningProvider(None),
    )

    events = _events(_ask(app, "What is the capital of Denmark?"))

    assert [name for _, name, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "error",
    ]
    assert events[1][2]["tool"] == PLANNING_STEP_TOOL
    assert events[2][2]["ok"] is False
    assert events[2][2]["error"]["code"] == "invalid_input"
    assert events[-1][2]["error"]["code"] == "unavailable"
    assert events[-1][2]["error"]["message"] == TOOL_UNAVAILABLE_MESSAGE


def test_a_tool_name_with_no_local_executor_is_refused(tmp_path: Path) -> None:
    app = create_app(
        _settings(duckdb_path=_lines_database(tmp_path / "lines.duckdb")),
        narration_provider=_PlanningProvider(
            ToolSelection("predict_outage", {"county_fips": "27001"})
        ),
    )

    events = _events(_ask(app))

    assert [name for _, name, _ in events][-1] == "error"
    assert events[1][2]["tool"] == PLANNING_STEP_TOOL
    assert events[1][2]["input"] == {"selected_tool": "predict_outage"}
    assert events[-1][2]["error"]["code"] == "unavailable"


def test_missing_evidence_is_reported_unavailable_rather_than_answered(
    tmp_path: Path,
) -> None:
    """A clean checkout has no DuckDB; the answer must be a refusal, not prose."""
    provider = _PlanningProvider(TOP_LINES_CALL)
    app = create_app(
        _settings(duckdb_path=tmp_path / "never-built.duckdb"),
        narration_provider=provider,
    )

    events = _events(_ask(app))

    assert [name for _, name, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "error",
    ]
    assert events[2][2]["ok"] is False
    assert events[-1][2]["error"]["code"] == "unavailable"
    assert provider.narrated == []
    assert not (tmp_path / "never-built.duckdb").exists()


def test_invented_tool_arguments_never_reach_an_executor(tmp_path: Path) -> None:
    """The model's arguments are a claim, re-checked against the frozen model."""
    calls: list[object] = []

    def spy(payload: object) -> object:  # pragma: no cover - must never run
        calls.append(payload)
        raise AssertionError("an unvalidated tool input reached the executor")

    settings = _settings(duckdb_path=_lines_database(tmp_path / "lines.duckdb"))
    registry = {
        "top_lines": RegisteredTool("top_lines", 5.0, spy)  # type: ignore[arg-type]
    }
    backend = LocalToolBackend(
        provider=_PlanningProvider(None),
        # `n` is bounded to 1..50 by the frozen `TopLinesInput`.
        selector=_PlanningProvider(
            ToolSelection("top_lines", {"region": "MN", "tech": "any", "n": 999})
        ),
        registry=registry,
        tools=[schema for schema in tools_for("gemini") if schema["name"] in registry],
    )

    turn = asyncio.run(
        backend.turn(AskRequest(attempt_id=ATTEMPT, question="how many lines?"))
    )

    assert calls == []
    assert turn.tool == "top_lines"
    assert turn.narration.status == "unavailable"
    assert turn.narration.unavailable is not None
    assert turn.narration.unavailable.code == "invalid_prerequisite"
    del settings


# --- the one-terminal invariant --------------------------------------------


@pytest.mark.parametrize(
    "selection,database",
    [
        (TOP_LINES_CALL, "lines.duckdb"),
        (TOP_LINES_CALL, "never-built.duckdb"),
        (None, "lines.duckdb"),
        (ToolSelection("predict_outage", {}), "lines.duckdb"),
    ],
)
def test_every_stream_carries_exactly_one_terminal_frame(
    tmp_path: Path, selection: ToolSelection | None, database: str
) -> None:
    """`done` XOR `error`, once, last -- in every outcome this loop can produce."""
    path = tmp_path / database
    if database == "lines.duckdb":
        _lines_database(path)
    app = create_app(
        _settings(duckdb_path=path), narration_provider=_PlanningProvider(selection)
    )

    names = [name for _, name, _ in _events(_ask(app))]

    terminals = [name for name in names if name in {"done", "error"}]
    assert len(terminals) == 1
    assert names[-1] == terminals[0]

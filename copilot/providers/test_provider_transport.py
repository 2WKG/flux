"""HTTP-boundary proof for both provider adapters and their `/ask` call site.

No test here opens a socket and no test carries a credential that could work.
Each provider SDK is constructed for real and handed an httpx mock transport
that replays a recorded response body from `copilot/providers/fixtures/`, so
the SDK's own streaming parser, the adapter, `copilot.runtime.stream_turn`,
the `/ask` route, and `create_app`'s provider construction all execute.  What
is faked is exactly one thing: the bytes on the wire.

The fixtures were written in each provider's documented streaming wire shape
and are proved to be that shape by the fact that the vendored SDK parses them;
they are not captured from a paid call, and neither file contains a key.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import MappingProxyType
from typing import Any

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.narration import GroundedNarration
from copilot.providers.claude import ClaudeNarrationProvider
from copilot.providers.gemini import GeminiNarrationProvider
from copilot.providers.grounding import REQUEST_TIMEOUT_SECONDS, SYSTEM_PROMPT
from copilot.routes.ask import AskRequest
from copilot.runtime import ToolTurn
from copilot.tools.schemas import ArtifactRef

FIXTURES = Path(__file__).parent / "fixtures"
ATTEMPT = "attempt_0123456789"

# The exact prose the two recorded streams deliver, in delta order.
RECORDED_DELTAS = (
    "Line L1 has a grid value score of ",
    "2.0",
    " in the supplied evidence.",
)
RECORDED_ANSWER = "".join(RECORDED_DELTAS)

# Written out here on purpose.  Parametrising over `SYSTEM_PROMPT.split()` would
# be an assertion that cannot fail: deleting a rule from `grounding.py` would
# just delete the case that should have caught it.  These are the rules spec 05
# and the repo's CLAUDE.md require to reach the model, pinned as literals.
REQUIRED_PROMPT_RULES = (
    "You narrate and plan. You never compute. Every number in your answer must",
    "appear verbatim in the tool evidence you were given.",
    "Never derive a new quantity from the evidence: no sums, differences,",
    "ratios, or percentages. Report the numbers separately instead.",
    "Every regulatory, legal, or physical claim must be supported by a supplied",
    "citation. Without one, say the claim is unverified.",
    "Say when topology is synthetic if the evidence labels it so.",
    "If a tool result is unavailable, say the answer is unavailable and why.",
    "Never substitute a plausible default for a missing value.",
    "Answer in at most six sentences of plain prose.",
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
    """A developer's own credentials must not decide these outcomes."""
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _narration() -> GroundedNarration:
    return GroundedNarration(
        status="available",
        text="One persisted line ranking row.",
        evidence=MappingProxyType({"lines": [{"line_id": "L1", "score": 2.0}]}),
        provenance=(
            ArtifactRef(
                artifact_id="line_upgrade_scores",
                artifact_version="1",
                source_kind="fixture",
                source_ref="fixture://lines",
            ),
        ),
        citations=(),
        limitations=("Topology is synthetic.",),
    )


def _turn() -> ToolTurn:
    return ToolTurn("ask-live", "fixture", {"source": "fixture"}, _narration())


class _ToolOnlyBackend:
    """A deployment-shaped backend: it plans tools and names no provider."""

    provider = None

    async def turn(self, payload: AskRequest) -> ToolTurn:
        return _turn()


class _StubProvider:
    """A backend-carried provider that is deliberately not the configured one."""

    name = "claude"
    model = "claude-opus-5"

    async def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        yield "Answered by the backend's own provider."


class _HungBackend:
    """A provider whose stream opens and then never produces another delta."""

    def __init__(self) -> None:
        self.provider = self
        self.name = "gemini"
        self.model = "gemini-3.8-flash"

    async def turn(self, payload: AskRequest) -> ToolTurn:
        return _turn()

    async def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        yield "The answer begins"
        await asyncio.Event().wait()
        yield "and never continues."  # pragma: no cover - unreachable by design


# --- transport seams -------------------------------------------------------
#
# Neither adapter carries a test-only parameter.  Each test patches the SDK
# entry point the adapter imports, so the adapter's own construction call --
# including the timeout it passes -- is the code under test.


def _record_gemini(
    monkeypatch: pytest.MonkeyPatch, body: bytes | None = None
) -> dict[str, Any]:
    from google import genai

    seen: dict[str, Any] = {}
    real_client = genai.Client
    payload = (FIXTURES / "gemini-stream.sse").read_bytes() if body is None else body

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200, content=payload, headers={"content-type": "text/event-stream"}
        )

    def patched(*, api_key: str, http_options: Any = None, **kwargs: Any) -> Any:
        seen["timeout_ms"] = getattr(http_options, "timeout", None)
        options = http_options.model_copy(
            update={"async_client_args": {"transport": httpx.MockTransport(handler)}}
        )
        return real_client(api_key=api_key, http_options=options, **kwargs)

    monkeypatch.setattr(genai, "Client", patched)
    return seen


def _record_claude(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import anthropic

    seen: dict[str, Any] = {}
    real_client = anthropic.AsyncAnthropic
    payload = (FIXTURES / "anthropic-stream.sse").read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx2.Response(
            200, content=payload, headers={"content-type": "text/event-stream"}
        )

    def patched(*, api_key: str, timeout: Any = None, **kwargs: Any) -> Any:
        seen["timeout_s"] = timeout
        return real_client(
            api_key=api_key,
            timeout=timeout,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
            **kwargs,
        )

    monkeypatch.setattr(anthropic, "AsyncAnthropic", patched)
    return seen


async def _collect(provider: Any) -> list[str]:
    return [delta async for delta in provider.text(_narration())]


# --- adapter-level HTTP boundary -------------------------------------------


def test_the_gemini_adapter_turns_a_recorded_http_stream_into_text_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _record_gemini(monkeypatch)

    deltas = asyncio.run(_collect(GeminiNarrationProvider("k", "gemini-3.8-flash")))

    assert deltas == list(RECORDED_DELTAS)
    assert "gemini-3.8-flash:streamGenerateContent" in seen["url"]
    assert seen["timeout_ms"] == int(REQUEST_TIMEOUT_SECONDS * 1000)


def test_the_claude_adapter_turns_a_recorded_http_stream_into_text_deltas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _record_claude(monkeypatch)

    deltas = asyncio.run(_collect(ClaudeNarrationProvider("k", "claude-sonnet-5")))

    assert deltas == list(RECORDED_DELTAS)
    assert seen["body"]["model"] == "claude-sonnet-5"
    assert seen["timeout_s"] == REQUEST_TIMEOUT_SECONDS


@pytest.mark.parametrize("rule", REQUIRED_PROMPT_RULES)
def test_every_shared_grounding_rule_reaches_gemini_on_the_wire(
    monkeypatch: pytest.MonkeyPatch, rule: str
) -> None:
    """The whole prompt is the contract, not one memorable substring of it."""
    seen = _record_gemini(monkeypatch)

    asyncio.run(_collect(GeminiNarrationProvider("k", "gemini-3.8-flash")))

    sent = seen["body"]["systemInstruction"]["parts"][0]["text"]
    assert rule in sent
    assert sent == SYSTEM_PROMPT
    assert "Topology is synthetic." in json.dumps(seen["body"]["contents"])


@pytest.mark.parametrize("rule", REQUIRED_PROMPT_RULES)
def test_every_shared_grounding_rule_reaches_claude_on_the_wire(
    monkeypatch: pytest.MonkeyPatch, rule: str
) -> None:
    seen = _record_claude(monkeypatch)

    asyncio.run(_collect(ClaudeNarrationProvider("k", "claude-sonnet-5")))

    assert rule in seen["body"]["system"]
    assert seen["body"]["system"] == SYSTEM_PROMPT
    assert "Topology is synthetic." in json.dumps(seen["body"]["messages"])


def test_no_recorded_fixture_carries_a_credential() -> None:
    for fixture in sorted(FIXTURES.iterdir()):
        text = fixture.read_text(encoding="utf-8")
        assert "api_key" not in text
        assert "sk-ant" not in text
        assert "AIza" not in text


# --- /ask, end to end, through the app-constructed provider ----------------


def _ask(app: Any) -> Any:
    return TestClient(app).post(
        "/ask", json={"attempt_id": ATTEMPT, "question": "which lines?"}
    )


def _events(response: Any) -> list[tuple[str, dict[str, object]]]:
    parsed = []
    for block in response.text.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if ": " in line
        )
        if "event" in fields:
            parsed.append((fields["event"], json.loads(fields["data"])))
    return parsed


def test_ask_answers_end_to_end_through_the_configured_gemini_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`create_app` builds the provider; `/ask` streams its recorded answer."""
    _record_gemini(monkeypatch)
    app = create_app(
        _settings(copilot_provider="gemini", gemini_api_key="unit-test-key"),
        ask_backend=_ToolOnlyBackend(),
    )

    response = _ask(app)
    events = _events(response)

    assert [name for name, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "text",
        "text",
        "text",
        "done",
    ]
    assert "".join(str(data["delta"]) for name, data in events if name == "text") == (
        RECORDED_ANSWER
    )
    assert response.headers["X-Flux-Copilot-Provider"] == "gemini"
    assert response.headers["X-Flux-Copilot-Model"] == "gemini-3.8-flash"


def test_ask_answers_end_to_end_through_the_configured_claude_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _record_claude(monkeypatch)
    app = create_app(
        _settings(copilot_provider="claude", anthropic_api_key="unit-test-key"),
        ask_backend=_ToolOnlyBackend(),
    )

    response = _ask(app)
    events = _events(response)

    assert [name for name, _ in events][-1] == "done"
    assert "".join(str(data["delta"]) for name, data in events if name == "text") == (
        RECORDED_ANSWER
    )
    assert response.headers["X-Flux-Copilot-Provider"] == "claude"
    assert response.headers["X-Flux-Copilot-Model"] == "claude-sonnet-5"


def test_an_unconfigured_provider_leaves_the_app_with_no_provider_at_all() -> None:
    app = create_app(_settings(copilot_provider="gemini"))

    assert app.state.narration_provider is None


# --- run metadata describes the provider that answered ---------------------


def test_ask_headers_name_the_backend_provider_not_the_configured_one() -> None:
    """A deployment-injected backend may carry a different provider."""
    app = create_app(
        _settings(copilot_provider="gemini", gemini_api_key="unit-test-key"),
        ask_backend=_ToolOnlyBackend(),
        narration_provider=_StubProvider(),
    )
    # The backend's own provider outranks the configured one.
    backend = _ToolOnlyBackend()
    backend.provider = _StubProvider()  # type: ignore[assignment]
    app.state.ask_backend = backend

    response = _ask(app)

    assert app.state.settings.provider_status().provider == "gemini"
    assert response.headers["X-Flux-Copilot-Provider"] == "claude"
    assert response.headers["X-Flux-Copilot-Model"] == "claude-opus-5"


def test_ask_omits_the_run_metadata_headers_when_no_provider_answers() -> None:
    app = create_app(
        _settings(copilot_provider="gemini"), ask_backend=_ToolOnlyBackend()
    )

    response = _ask(app)

    assert "X-Flux-Copilot-Provider" not in response.headers
    assert "X-Flux-Copilot-Model" not in response.headers
    assert _events(response)[-1][1]["error"]["code"] == "unavailable"  # type: ignore[index]


# --- the deadline terminal is reachable ------------------------------------


def test_a_hung_provider_stream_ends_in_the_deadline_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the bound this request never returns: the ping runs forever."""
    monkeypatch.setattr("copilot.runtime.PROVIDER_DELTA_TIMEOUT_SECONDS", 0.05)
    app = create_app(_settings(), ask_backend=_HungBackend())

    response = _ask(app)
    events = _events(response)

    assert [name for name, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "text",
        "error",
    ]
    assert events[-1][1]["error"] == {
        "code": "deadline",
        "message": "The answer could not finish within the request deadline.",
        "retryable": True,
    }
    # The heartbeat comment stops with the stream: nothing follows the terminal.
    assert response.text.rstrip().endswith(json.dumps(dict(events[-1][1]))) or (
        ": keepalive" not in response.text.split("event: error", 1)[1]
    )

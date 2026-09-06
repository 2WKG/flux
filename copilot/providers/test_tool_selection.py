"""HTTP-boundary proof for the tool-selection turn of both provider adapters.

Same discipline as `test_provider_transport.py`: each SDK is constructed for
real and handed an httpx mock transport that replays a recorded response body
from `copilot/providers/fixtures/`.  The SDK's own request builder and response
parser, the adapter, and the frozen schema rendering all execute.  What is
faked is exactly one thing -- the bytes on the wire.  No test here opens a
socket or carries a credential that could work.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest

from copilot.agent.registry import build_tool_registry
from copilot.config import Settings
from copilot.providers import tools_for
from copilot.providers.claude import ClaudeNarrationProvider
from copilot.providers.gemini import GeminiNarrationProvider
from copilot.providers.selection import SELECTION_SYSTEM_PROMPT, ToolSelection
from copilot.tools.schemas import TOOL_REGISTRY

FIXTURES = Path(__file__).parent / "fixtures"

# The exact call the two recorded planning responses make.
RECORDED_SELECTION = ToolSelection("top_lines", {"region": "MN", "tech": "any", "n": 3})

_PROVIDER_ENV = (
    "COPILOT_PROVIDER",
    "COPILOT_MODEL",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "gemini-api-key",
)


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


def _registered_tools(provider: str) -> list[dict[str, Any]]:
    registry = build_tool_registry(Settings(_env_file=None))
    return [schema for schema in tools_for(provider) if schema["name"] in registry]  # type: ignore[misc]


def _record_gemini(monkeypatch: pytest.MonkeyPatch, fixture: str) -> dict[str, Any]:
    from google import genai

    seen: dict[str, Any] = {}
    real_client = genai.Client
    payload = (FIXTURES / fixture).read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200, content=payload, headers={"content-type": "application/json"}
        )

    def patched(*, api_key: str, http_options: Any = None, **kwargs: Any) -> Any:
        options = http_options.model_copy(
            update={"async_client_args": {"transport": httpx.MockTransport(handler)}}
        )
        return real_client(api_key=api_key, http_options=options, **kwargs)

    monkeypatch.setattr(genai, "Client", patched)
    return seen


def _record_claude(monkeypatch: pytest.MonkeyPatch, fixture: str) -> dict[str, Any]:
    import anthropic

    seen: dict[str, Any] = {}
    real_client = anthropic.AsyncAnthropic
    payload = (FIXTURES / fixture).read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx2.Response(
            200, content=payload, headers={"content-type": "application/json"}
        )

    def patched(*, api_key: str, timeout: Any = None, **kwargs: Any) -> Any:
        return real_client(
            api_key=api_key,
            timeout=timeout,
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
            **kwargs,
        )

    monkeypatch.setattr(anthropic, "AsyncAnthropic", patched)
    return seen


def _select(provider: Any, tools: list[dict[str, Any]]) -> ToolSelection | None:
    return asyncio.run(
        provider.select_tool(
            "Which Minnesota lines should we upgrade?",
            tools=tools,
            context={"scenario_id": "beryl_2024"},
            history=[{"role": "user", "content": "Earlier question"}],
        )
    )


def test_the_claude_planner_returns_a_frozen_tool_call_from_a_recorded_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _record_claude(monkeypatch, "anthropic-tool-use.json")

    selection = _select(
        ClaudeNarrationProvider("k", "claude-sonnet-5"), _registered_tools("claude")
    )

    assert selection == RECORDED_SELECTION
    assert seen["body"]["system"] == SELECTION_SYSTEM_PROMPT
    assert seen["body"]["tool_choice"] == {"type": "auto"}
    assert [tool["name"] for tool in seen["body"]["tools"]] == [
        "top_lines",
        "causal_query",
    ]
    # The planner is told the selected state and the question, not a summary of
    # them: an argument it returns has to be traceable to the request.
    assert "beryl_2024" in json.dumps(seen["body"]["messages"])


def test_the_gemini_planner_returns_a_frozen_tool_call_from_a_recorded_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _record_gemini(monkeypatch, "gemini-tool-call.json")

    selection = _select(
        GeminiNarrationProvider("k", "gemini-3.8-flash"), _registered_tools("gemini")
    )

    assert selection == RECORDED_SELECTION
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == (
        SELECTION_SYSTEM_PROMPT
    )
    declared = seen["body"]["tools"][0]["functionDeclarations"]
    assert [tool["name"] for tool in declared] == ["top_lines", "causal_query"]
    assert "beryl_2024" in json.dumps(seen["body"]["contents"])


def test_a_claude_turn_that_calls_no_tool_is_reported_as_no_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal must survive as a refusal, not become a nearest-fit tool."""
    _record_claude(monkeypatch, "anthropic-no-tool.json")

    assert (
        _select(
            ClaudeNarrationProvider("k", "claude-sonnet-5"), _registered_tools("claude")
        )
        is None
    )


def test_a_gemini_turn_that_calls_no_tool_is_reported_as_no_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _record_gemini(monkeypatch, "gemini-no-tool.json")

    assert (
        _select(
            GeminiNarrationProvider("k", "gemini-3.8-flash"),
            _registered_tools("gemini"),
        )
        is None
    )


@pytest.mark.parametrize("provider", ["claude", "gemini"])
def test_a_frozen_tool_with_no_local_executor_is_never_advertised(
    provider: str,
) -> None:
    """The planner cannot choose a tool this deployment could not then run."""
    frozen = {definition.name for definition in TOOL_REGISTRY}
    advertised = {schema["name"] for schema in _registered_tools(provider)}
    runnable = set(build_tool_registry(Settings(_env_file=None)))

    assert advertised == runnable
    assert advertised < frozen
    assert "predict_outage" not in advertised


def test_no_recorded_planning_fixture_carries_a_credential() -> None:
    for fixture in sorted(FIXTURES.iterdir()):
        text = fixture.read_text(encoding="utf-8")
        assert "api_key" not in text
        assert "sk-ant" not in text
        assert "AIza" not in text

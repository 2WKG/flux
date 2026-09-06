"""The production `AskBackend`: a bounded, registry-only orchestration loop.

Until now `create_app` left `app.state.ask_backend` at `None`, so
`copilot/routes/ask.py` emitted its unavailable terminal before any provider
was reached and the chat dock could not answer with *any* configuration.  This
module is the missing production factory.

What it does, in order, for one `POST /ask`:

1. Ask the configured provider to choose exactly one tool from the frozen
   contract (`copilot/tools/schemas.py`), rendered in that provider's shape and
   filtered to the tools `copilot/agent/registry.py` can really run.
2. Re-validate the model's arguments against that tool's frozen input model.
   The model's claim is never trusted as a payload.
3. Run the bound executor in a worker thread under the tool's timeout.
4. Narrate the accepted result through `copilot.narration.narrate`, which is
   the only thing the provider is then allowed to talk about.

Step bound.  The `AskBackend` contract carries exactly one `ToolTurn` per
attempt, so this loop performs exactly one tool step; there is no unbounded
iteration and no path that reaches a database without a validated input.  A
multi-step loop (spec 05 §"Tool-use loop", `MAX_ITER = 8`) needs a wider
backend contract and is a named follow-up, not a silent behaviour here.

Honesty.  Every way this can fail to produce evidence ends in a *named*
unavailable narration, which `copilot.runtime.stream_turn` turns into a single
terminal `error` frame.  Nothing here fabricates an argument, substitutes a
tool, or lets an empty result be narrated as an answer.  When no provider is
configured at all, `build_ask_backend` returns `None` and the route keeps
emitting exactly the terminal it emits today.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from copilot.agent.registry import RegisteredTool, build_tool_registry
from copilot.config import Settings
from copilot.narration import GroundedNarration, narrate
from copilot.providers import tools_for
from copilot.providers.selection import ToolSelector
from copilot.routes.ask import AskBackend, AskRequest
from copilot.runtime import AsyncNarrationProvider, ToolTurn
from copilot.tools.schemas import Unavailable, UnavailableCode, validate_tool_input

PLANNING_STEP_TOOL = "tool_selection"
"""Trace name for the planning step itself.

A refusal has to be observable in the tool trace, and the only honest name for
it is the step that refused.  It is deliberately not one of the nine frozen
tool names: attributing a refusal to `top_lines` would claim `top_lines` ran.
"""


class LocalToolBackend:
    """One `AskBackend`: plan one frozen tool, run it locally, narrate it."""

    def __init__(
        self,
        provider: AsyncNarrationProvider,
        selector: ToolSelector,
        registry: Mapping[str, RegisteredTool],
        tools: Sequence[Mapping[str, Any]],
    ) -> None:
        self.provider = provider
        self._selector = selector
        self._registry = registry
        self._tools = tuple(tools)

    async def turn(self, payload: AskRequest) -> ToolTurn:
        started = time.monotonic()
        selection = await self._selector.select_tool(
            payload.question,
            tools=self._tools,
            context=(
                payload.context.model_dump(exclude_none=True)
                if payload.context is not None
                else None
            ),
            history=[message.model_dump() for message in payload.history],
        )
        if selection is None:
            return self._refused(
                payload,
                PLANNING_STEP_TOOL,
                {"question": payload.question},
                "unsupported_request",
                "no registered Flux tool answers this question with the "
                "arguments the request carried",
                started,
            )

        arguments = (
            dict(selection.input) if isinstance(selection.input, Mapping) else {}
        )
        registered = self._registry.get(selection.name)
        if registered is None:
            return self._refused(
                payload,
                PLANNING_STEP_TOOL,
                {"selected_tool": selection.name},
                "unsupported_request",
                "the selected tool has no local executor in this deployment",
                started,
            )

        try:
            model_input = validate_tool_input(selection.name, arguments)
        except (TypeError, ValueError):
            # Includes pydantic's ValidationError.  The model's arguments are a
            # claim; a claim that fails the frozen contract must not reach an
            # executor, and it must not be repaired into something plausible.
            return self._refused(
                payload,
                selection.name,
                arguments,
                "invalid_prerequisite",
                "the selected tool arguments failed its frozen input contract",
                started,
            )

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(registered.run, model_input),
                registered.timeout_seconds,
            )
        except TimeoutError:
            return self._refused(
                payload,
                selection.name,
                arguments,
                "invalid_prerequisite",
                "the selected tool exceeded its time limit",
                started,
            )

        return ToolTurn(
            self._call_id(payload),
            selection.name,
            arguments,
            narrate(selection.name, result),
            elapsed_ms=_elapsed_ms(started),
        )

    def _call_id(self, payload: AskRequest) -> str:
        # One tool step per attempt, so the attempt id already identifies the
        # call uniquely within its stream.
        return f"{payload.attempt_id}:1"

    def _refused(
        self,
        payload: AskRequest,
        tool: str,
        tool_input: Mapping[str, Any],
        code: UnavailableCode,
        reason: str,
        started: float,
    ) -> ToolTurn:
        """Report a named refusal as a tool turn, never as a silent success."""

        return ToolTurn(
            self._call_id(payload),
            tool,
            dict(tool_input),
            GroundedNarration(
                status="unavailable",
                text=reason,
                evidence=MappingProxyType({}),
                provenance=(),
                citations=(),
                limitations=(),
                unavailable=Unavailable(code=code, reason=reason),
            ),
            elapsed_ms=_elapsed_ms(started),
        )


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def build_ask_backend(
    settings: Settings, provider: AsyncNarrationProvider | None
) -> AskBackend | None:
    """Construct the deployment's `AskBackend`, or `None` when it cannot answer.

    `None` is returned -- and the route therefore keeps emitting exactly the
    documented "local Copilot backend is not configured" terminal -- when:

    * no provider is configured (no `COPILOT_PROVIDER` credential), or
    * the configured provider cannot plan a tool call.

    Neither case is filled in with a default answer, a canned tool, or a
    fabricated response.  Construction opens no connection and reads nothing.
    """

    if provider is None:
        return None
    if not callable(getattr(provider, "select_tool", None)):
        # A narration-only provider can restate evidence but cannot decide
        # which evidence to fetch.  Answering anyway would mean choosing the
        # tool here, which is the plausible default this contract forbids.
        return None

    registry = build_tool_registry(settings)
    # `build_narration_provider` builds the adapter from these same settings,
    # so the active provider name is the one that will receive these schemas.
    rendered = tools_for(settings.provider_status().provider)
    tools = [schema for schema in rendered if schema["name"] in registry]
    return LocalToolBackend(
        provider=provider, selector=provider, registry=registry, tools=tools
    )

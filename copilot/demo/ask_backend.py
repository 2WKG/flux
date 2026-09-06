"""A real, offline-safe ``POST /ask`` backend for the synthetic cascade tool.

This module is deliberately an injected runtime component.  It can be mounted
through the existing ``create_app(..., ask_backend=...)`` seam without changing
the browser request or SSE contracts.  The runner is supplied by integration:
when Texas topology inputs are absent it must return the same explicit tool
unavailable result as the core, never a fixture-shaped cascade.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import MappingProxyType
from typing import Protocol

from copilot.narration import GroundedNarration, narrate
from copilot.routes.ask import AskRequest
from copilot.runtime import AsyncNarrationProvider, ToolTurn
from copilot.tools.schemas import CascadeData, ToolOutput, unavailable_output


class CascadeRunner(Protocol):
    """The integration adapter around the actual Texas synthetic cascade core."""

    async def run(
        self, *, element_ids: list[str], scenario_id: str, hour: int
    ) -> CascadeData | ToolOutput: ...


class DeterministicNarrationProvider:
    """A no-network narrator for tool-provenanced results.

    It emits only the generic grounded narration from :func:`narrate`; therefore
    no numeric value, weather claim, or solver conclusion is recreated in text.
    A configured provider may replace it at construction time.
    """

    async def text(self, narration: GroundedNarration) -> AsyncIterator[str]:
        yield narration.text


class DemoAskBackend:
    """Turn a plain-English cascade request into one visible, bounded tool call."""

    def __init__(
        self,
        cascade_runner: CascadeRunner,
        provider: AsyncNarrationProvider | None = None,
    ) -> None:
        self._cascade_runner = cascade_runner
        self.provider = provider or DeterministicNarrationProvider()

    async def turn(self, payload: AskRequest) -> ToolTurn:
        """Build a tool turn. Unsupported prompts are explicit tool failures."""

        if not _asks_for_cascade(payload.question):
            return _unavailable_turn(
                payload,
                "This demo backend currently supports a Texas synthetic cascade request. Ask about an outage, trip, or cascade with a selected element.",
            )
        context = payload.context
        if context is None or not context.selected_element_id:
            return _unavailable_turn(
                payload,
                "Select a Texas synthetic grid element before running a cascade.",
            )
        if context.scenario_id is None or context.hour is None:
            return _unavailable_turn(
                payload,
                "Choose a supported scenario and hour before running a cascade.",
            )
        if context.scenario_id not in {"uri_2021", "beryl_2024", "helene_2024", "forecast_72h"}:
            return _unavailable_turn(
                payload,
                "This backend does not use the selected scenario as a Texas synthetic cascade input.",
            )

        result = await self._cascade_runner.run(
            element_ids=[context.selected_element_id],
            scenario_id=context.scenario_id,
            hour=context.hour,
        )
        # ``narrate`` checks the registered tool output shape again.  A core
        # adapter cannot slip arbitrary JSON or an unlabeled number into SSE.
        narration = narrate("run_cascade", result)
        return ToolTurn(
            call_id=f"cascade:{payload.attempt_id}",
            tool="run_cascade",
            input={
                "element_ids": [context.selected_element_id],
                "scenario_id": context.scenario_id,
                "hour": context.hour,
            },
            narration=narration,
        )


def _unavailable_turn(payload: AskRequest, reason: str) -> ToolTurn:
    context = payload.context
    input_payload: dict[str, object] = {}
    if context is not None:
        if context.selected_element_id is not None:
            input_payload["element_ids"] = [context.selected_element_id]
        if context.scenario_id is not None:
            input_payload["scenario_id"] = context.scenario_id
        if context.hour is not None:
            input_payload["hour"] = context.hour
    return ToolTurn(
        call_id=f"cascade:{payload.attempt_id}",
        tool="run_cascade",
        input=MappingProxyType(input_payload),
        narration=narrate(
            "run_cascade", unavailable_output("unsupported_request", reason)
        ),
    )


def _asks_for_cascade(question: str) -> bool:
    text = question.casefold()
    return any(word in text for word in ("cascade", "outage", "trip", "fail", "redundan"))

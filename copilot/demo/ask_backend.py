"""A real, offline-safe ``POST /ask`` backend for the synthetic cascade tool.

This module is deliberately an injected runtime component.  It can be mounted
through the existing ``create_app(..., ask_backend=...)`` seam without changing
the browser request or SSE contracts.  The runner is supplied by integration:
when Texas topology inputs are absent it must return the same explicit tool
unavailable result as the core, never a fixture-shaped cascade.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from copilot.demo.jepa import DEFAULT_JEPA_ARTIFACT, read_experimental_jepa_forecast
from copilot.narration import GroundedNarration, narrate
from copilot.routes.ask import AskRequest
from copilot.runtime import AsyncNarrationProvider, ToolTurn
from copilot.tools.schemas import (
    ArtifactRef,
    CascadeData,
    ToolOutput,
    unavailable_output,
)


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
        *,
        jepa_artifact_path: Path = DEFAULT_JEPA_ARTIFACT,
    ) -> None:
        self._cascade_runner = cascade_runner
        self.provider = provider or DeterministicNarrationProvider()
        self._jepa_artifact_path = jepa_artifact_path

    async def turn(self, payload: AskRequest) -> ToolTurn:
        """Build a tool turn. Unsupported prompts are explicit tool failures."""

        if _asks_for_experimental_forecast(payload.question):
            return _experimental_forecast_turn(payload, self._jepa_artifact_path)
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


def _asks_for_experimental_forecast(question: str) -> bool:
    text = question.casefold()
    return any(word in text for word in ("jepa", "trajectory forecast", "count forecast"))


def _experimental_forecast_turn(payload: AskRequest, path: Path) -> ToolTurn:
    """Expose the JEPA artifact as its own labelled experimental SSE tool."""

    result = read_experimental_jepa_forecast(path)
    if result.status == "unavailable":
        reason = result.reason or "Experimental forecast unavailable."
        return ToolTurn(
            call_id=f"forecast:{payload.attempt_id}",
            tool="experimental_forecast",
            input={"artifact": path.name},
            narration=GroundedNarration(
                status="unavailable",
                text=reason,
                evidence=MappingProxyType({}),
                provenance=(),
                citations=(),
                limitations=result.limitations,
                unavailable=unavailable_output("artifact_unavailable", reason).unavailable,
            ),
        )
    provenance = tuple(
        ArtifactRef(
            artifact_id=item,
            artifact_version=str(result.data["model_version"]),
            source_kind="observed",
            source_ref=item,
        )
        for item in result.provenance
    )
    return ToolTurn(
        call_id=f"forecast:{payload.attempt_id}",
        tool="experimental_forecast",
        input={"artifact": path.name},
        narration=GroundedNarration(
            status="available",
            text=(
                "Experimental observed-count trajectory forecast is available. "
                "It is not a weather forecast, outage probability, or cascade prediction."
            ),
            evidence=MappingProxyType(dict(result.data)),
            provenance=provenance,
            citations=(),
            limitations=result.limitations,
        ),
    )

"""Grounded natural-language dispatch for the opt-in interactive core service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Protocol

from copilot.demo.ask_backend import DeterministicNarrationProvider
from copilot.narration import GroundedNarration
from copilot.routes.ask import AskRequest
from copilot.runtime import AsyncNarrationProvider, ToolTurn
from copilot.tools.schemas import ArtifactRef, Unavailable, unavailable_output

Intent = Literal["balance", "redundancy", "siting_search", "scenario_edit"]


@dataclass(frozen=True)
class InteractiveEvidence:
    """Exact validated service output, held beside its named evidence lineage."""

    status: Literal["available", "unavailable"]
    result: Mapping[str, object]
    provenance: tuple[ArtifactRef, ...] = ()
    limitations: tuple[str, ...] = ()
    reason: str | None = None


class InteractiveToolBridge(Protocol):
    """Adapter owned by the interactive HTTP composition, never by narration."""

    async def execute(
        self, intent: Intent, payload: Mapping[str, object]
    ) -> InteractiveEvidence: ...


class InteractiveAskBackend:
    """Map plain English to one visible interactive tool operation."""

    def __init__(
        self, bridge: InteractiveToolBridge, provider: AsyncNarrationProvider | None = None
    ) -> None:
        self._bridge = bridge
        self.provider = provider or DeterministicNarrationProvider()

    async def turn(self, payload: AskRequest) -> ToolTurn:
        intent = _intent(payload.question)
        if intent is None:
            return _unavailable(payload, "This interactive agent supports balance, redundancy, placement search, and scenario edits.")
        evidence = await self._bridge.execute(intent, _context(payload))
        if evidence.status == "unavailable":
            return _unavailable(payload, evidence.reason or "The requested interactive tool is unavailable.", intent)
        if not evidence.provenance:
            return _unavailable(payload, "The interactive tool returned no provenance.", intent)
        return ToolTurn(
            call_id=f"{intent}:{payload.attempt_id}",
            tool=intent,
            input=_context(payload),
            narration=GroundedNarration(
                status="available",
                text=_summary(intent),
                evidence=MappingProxyType(dict(evidence.result)),
                provenance=evidence.provenance,
                citations=(),
                limitations=evidence.limitations,
            ),
        )


def _context(payload: AskRequest) -> dict[str, object]:
    context = payload.context
    if context is None:
        return {"question": payload.question}
    return {
        key: value
        for key, value in {
            "question": payload.question,
            "scenario_id": context.scenario_id,
            "hour": context.hour,
            "selected_site_id": context.selected_site_id,
            "compare_site_id": context.compare_site_id,
            "selected_element_id": context.selected_element_id,
            "unit_mw": context.unit_mw,
        }.items()
        if value is not None
    }


def _intent(question: str) -> Intent | None:
    text = question.casefold()
    if "balance" in text or "feasib" in text:
        return "balance"
    if "redundan" in text or "backup path" in text:
        return "redundancy"
    if "site" in text or "place" in text or "counterfactual" in text:
        return "siting_search"
    if "edit" in text or "scenario" in text or "remove" in text or "restore" in text:
        return "scenario_edit"
    return None


def _summary(intent: Intent) -> str:
    return {
        "balance": "The model balance result is available in the tool card.",
        "redundancy": "The model redundancy result is available in the tool card.",
        "siting_search": "The model placement comparison is available in the tool card.",
        "scenario_edit": "The scenario edit result is available in the tool card.",
    }[intent]


def _unavailable(payload: AskRequest, reason: str, intent: Intent = "balance") -> ToolTurn:
    unavailable = unavailable_output("unsupported_request", reason).unavailable
    assert isinstance(unavailable, Unavailable)
    return ToolTurn(
        call_id=f"{intent}:{payload.attempt_id}",
        tool=intent,
        input=_context(payload),
        narration=GroundedNarration(
            status="unavailable",
            text=reason,
            evidence=MappingProxyType({}),
            provenance=(),
            citations=(),
            limitations=(),
            unavailable=unavailable,
        ),
    )

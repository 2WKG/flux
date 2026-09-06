"""Optional JSON planning surface for the Flux demo.

``POST /ask`` remains the primary Copilot path and preserves its SSE lifecycle.
This route is intentionally a small, dependency-injected fallback for a demo
control room: it identifies an intent, calls one real bridge tool, and returns
the raw result in a card.  It never starts a provider, calculates a number, or
pretends that inventory data is a topology simulation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from copilot.api import UnavailableError
from copilot.demo.bridge import (
    DemoCapability,
    DemoToolBridge,
    DemoToolName,
    DemoToolResult,
)

_STATES = ("tx", "mn")

#: Which state each word in a question names.  Used to detect a question whose
#: geography disagrees with (or is absent from) the supplied context, so a
#: cascade is never silently answered for the wrong grid.
_STATE_WORDS: dict[str, tuple[str, ...]] = {
    "mn": ("minnesota",),
    "tx": ("texas", "ercot"),
}

#: Intent keyword sets, in the order ``_choose_intent`` tries them.  Precedence
#: is cascade > forecast > scenario > availability > inventory, so a question
#: carrying two intents resolves to the earlier one; matching is on whole words
#: so "failover" does not match "fail" and "unpredictable" does not match
#: "predict".
_CASCADE_WORDS = (
    "cascade",
    "fail",
    "fails",
    "failure",
    "failures",
    "outage",
    "outages",
    "redundancy",
    "redundant",
    "trip",
    "trips",
)
_FORECAST_WORDS = ("weather", "forecast", "jepa", "predict", "prediction", "projection")
_SCENARIO_WORDS = ("scenario", "storm", "snow", "heat", "cold", "timeline")
_AVAILABILITY_WORDS = (
    "available",
    "availability",
    "capability",
    "capabilities",
    "what data",
)


def _mentions(text: str, words: tuple[str, ...]) -> bool:
    """Whole-word match, so "failover" is not a cascade question."""
    return any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def _states_named(text: str) -> set[str]:
    return {
        code
        for code, words in _STATE_WORDS.items()
        if any(re.search(rf"\b{re.escape(word)}\b", text) for word in words)
    }


class DemoContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["tx", "mn"] | None = None
    scenario_id: str | None = Field(default=None, min_length=1, max_length=128)
    hour: int | None = Field(default=None, ge=0, le=167)
    selected_asset_id: str | None = Field(default=None, min_length=1, max_length=160)


class DemoAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: Annotated[str, Field(min_length=1, max_length=2_000)]
    context: DemoContext = Field(default_factory=DemoContext)


class DemoCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str = Field(pattern=r"^[1-9][0-9]*$")
    kind: Literal["inventory", "scenario", "cascade", "forecast", "availability"]
    title: str = Field(min_length=1, max_length=160)
    plain_english: str = Field(min_length=1, max_length=720)
    tool: DemoToolName
    result: DemoToolResult


class DemoAskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # This is deliberately not a substitute for the streamed Copilot.  Until
    # integration wires the real simulation HTTP/tool path, callers can render
    # it only as an explicitly labelled planning fallback.
    mode: Literal["planning_fallback"] = "planning_fallback"
    primary_copilot_path: Literal["/ask"] = "/ask"
    cards: tuple[DemoCard, ...]


class DemoBriefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    primary_copilot_path: Literal["/ask"] = "/ask"
    capabilities: tuple[DemoCapability, ...]
    guidance: str


def create_demo_router(tool_bridge: DemoToolBridge) -> APIRouter:
    """Create an optional ``/demo`` router around an explicitly supplied bridge."""

    router = APIRouter(prefix="/demo", tags=["demo"])

    @router.get("/brief", response_model=DemoBriefResponse)
    async def brief() -> DemoBriefResponse:
        capabilities = await _guarded(tool_bridge.capabilities())
        return DemoBriefResponse(
            capabilities=capabilities,
            guidance=(
                "Use the main Ask panel for streamed Copilot answers. This optional "
                "brief lists only the demo capabilities supplied by the current data."
            ),
        )

    @router.post("/ask", response_model=DemoAskResponse)
    async def demo_ask(payload: DemoAskRequest) -> DemoAskResponse:
        tool, kind, title, plain_english = _choose_intent(payload)
        result = await _guarded(tool_bridge.execute(tool, _arguments(payload.context)))
        return DemoAskResponse(
            cards=(
                DemoCard(
                    step_id="1",
                    kind=kind,
                    title=title,
                    plain_english=_narration(plain_english, result),
                    tool=tool,
                    result=result,
                ),
            )
        )

    return router


async def _guarded(awaitable):  # type: ignore[no-untyped-def]
    """Turn any bridge failure into the shared named 503, never a bare 500."""
    try:
        return await awaitable
    except Exception as exc:  # the bridge is deployment-injected and opaque
        raise UnavailableError(
            "The demo tool bridge is unavailable.",
            details={"reason": "demo_bridge_unavailable"},
        ) from exc


def _arguments(context: DemoContext) -> Mapping[str, object]:
    return {
        key: value
        for key, value in {
            "state": context.state,
            "scenario_id": context.scenario_id,
            "hour": context.hour,
            "selected_asset_id": context.selected_asset_id,
        }.items()
        if value is not None
    }


def _choose_intent(
    payload: DemoAskRequest,
) -> tuple[
    DemoToolName,
    Literal["inventory", "scenario", "cascade", "forecast", "availability"],
    str,
    str,
]:
    """Pick one intent.

    Precedence is cascade > forecast > scenario > availability > inventory and
    matching is on whole words (see ``_mentions``).  A cascade intent is the one
    place this demo can mislabel a grid, so it refuses rather than defaulting:
    the only topology-backed cascade here is the Texas synthetic model, and a
    question whose state is absent, ambiguous, or contradicted by the request
    context gets the analysis-boundary card instead.
    """
    text = payload.question.casefold()
    state = payload.context.state
    if _mentions(text, _CASCADE_WORDS):
        named = _states_named(text)
        if state is None:
            return (
                "availability",
                "availability",
                "Analysis boundary: no state selected",
                "I will not run a cascade without knowing which grid you mean. The only topology-backed cascade in this demo is the Texas synthetic model; Minnesota has none. Select a state and ask again. Here is the available boundary.",
            )
        if len(named) > 1 or (named and state not in named):
            return (
                "availability",
                "availability",
                "Analysis boundary: ambiguous state",
                "The question names a different state from the one selected, so I will not attribute a cascade to either grid. Here is the available boundary.",
            )
        if state == "mn":
            return (
                "availability",
                "availability",
                "Minnesota analysis boundary",
                "Minnesota has no topology-backed cascade in this demo. Here is the available aggregate or inventory boundary.",
            )
        return (
            "cascade",
            "cascade",
            "Texas synthetic cascade",
            "I checked the selected Texas scenario through the labelled synthetic topology tool. The card keeps its tool result and limits together.",
        )
    if _mentions(text, _FORECAST_WORDS):
        return (
            "forecast",
            "forecast",
            "Weather and forecast evidence",
            "I checked the available weather or experimental forecast artifact. This card does not turn an observed count forecast into a weather forecast or cascade claim.",
        )
    if _mentions(text, _SCENARIO_WORDS):
        return (
            "scenario",
            "scenario",
            "Scenario evidence",
            "I checked the selected scenario record and its source labels. Its time bounds and limitations remain in the tool result.",
        )
    if _mentions(text, _AVAILABILITY_WORDS):
        return (
            "availability",
            "availability",
            "Available analysis",
            "I checked what the current demo can support before making an analysis claim.",
        )
    return (
        "inventory",
        "inventory",
        "Energy-system inventory",
        "I checked the selected inventory surface. Inventory records describe available assets and provenance; they do not by themselves establish electrical connectivity.",
    )


def _narration(prefix: str, result: DemoToolResult) -> str:
    if result.status == "unavailable":
        return f"{prefix} The requested tool is unavailable: {result.reason}."
    return prefix

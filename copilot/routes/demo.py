"""Optional JSON planning surface for the Flux demo.

``POST /ask`` remains the primary Copilot path and preserves its SSE lifecycle.
This route is intentionally a small, dependency-injected fallback for a demo
control room: it identifies an intent, calls one real bridge tool, and returns
the raw result in a card.  It never starts a provider, calculates a number, or
pretends that inventory data is a topology simulation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from copilot.demo.bridge import DemoCapability, DemoToolBridge, DemoToolResult

_STATES = ("tx", "mn")


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
    tool: str = Field(min_length=1, max_length=80)
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
        capabilities = await tool_bridge.capabilities()
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
        result = await tool_bridge.execute(tool, _arguments(payload.context))
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
    str,
    Literal["inventory", "scenario", "cascade", "forecast", "availability"],
    str,
    str,
]:
    text = payload.question.casefold()
    state = payload.context.state
    if any(word in text for word in ("cascade", "fail", "outage", "redundan", "trip")):
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
    if any(
        word in text
        for word in ("weather", "forecast", "jepa", "predict", "projection")
    ):
        return (
            "forecast",
            "forecast",
            "Weather and forecast evidence",
            "I checked the available weather or experimental forecast artifact. This card does not turn an observed count forecast into a weather forecast or cascade claim.",
        )
    if any(
        word in text
        for word in ("scenario", "storm", "snow", "heat", "cold", "timeline")
    ):
        return (
            "scenario",
            "scenario",
            "Scenario evidence",
            "I checked the selected scenario record and its source labels. Its time bounds and limitations remain in the tool result.",
        )
    if any(word in text for word in ("available", "can you", "capabilit", "what data")):
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

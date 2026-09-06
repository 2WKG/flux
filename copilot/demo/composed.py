"""One `/ask` dispatcher that keeps interactive and supplemental demo paths together."""

from __future__ import annotations

import re

from copilot.demo.ask_backend import DemoAskBackend
from copilot.demo.interactive import InteractiveAskBackend, _intent, _unavailable
from copilot.demo.interactive_service import InteractiveServiceBridge
from copilot.routes.ask import AskRequest
from copilot.runtime import AsyncNarrationProvider, ToolTurn

_TEXAS_SCENARIOS = frozenset({"uri_2021", "beryl_2024", "helene_2024"})
_CANONICAL_ID = re.compile(r"^(line|impedance|generator|gen|sgen|load|slack):\S+$")
_CANONICAL_BUS = re.compile(r"\bbus\s*[:#]?\s*\d+\b", re.IGNORECASE)


class ComposedAskBackend:
    """Dispatch one request while retaining one provider and SSE lifecycle."""

    def __init__(
        self, *, demo: DemoAskBackend, interactive: InteractiveAskBackend
    ) -> None:
        self._demo = demo
        self._interactive = interactive
        # Both are deterministic grounded providers unless composition supplies
        # one configured provider. The route reads this single attribute.
        self.provider = interactive.provider

    async def turn(self, payload: AskRequest) -> ToolTurn:
        intent = _intent(payload.question)
        if intent is None:
            return await self._demo.turn(payload)
        if not _is_texas_synthetic_context(payload):
            return _unavailable(
                payload,
                "Switch to the Texas synthetic grid model and select a supported scenario before running an interactive operation.",
                intent,
            )
        return await self._interactive.turn(payload)


def create_composed_ask_backend(
    *,
    demo: DemoAskBackend,
    interactive_service: object,
    provider: AsyncNarrationProvider | None = None,
) -> ComposedAskBackend:
    """Build one transport backend around the shared interactive service."""

    interactive = InteractiveAskBackend(
        InteractiveServiceBridge(interactive_service), provider or demo.provider
    )
    return ComposedAskBackend(demo=demo, interactive=interactive)


def _is_texas_synthetic_context(payload: AskRequest) -> bool:
    context = payload.context
    if context is None or context.scenario_id not in _TEXAS_SCENARIOS:
        return False
    selected = context.selected_element_id
    # Balance has no selected element requirement; every action that mutates or
    # resolves a component must use an exact core canonical ID.
    intent = _intent(payload.question)
    if intent in {"balance", "siting_search"}:
        return True
    if intent == "redundancy":
        # A bus number is an explicit model reference. Do not manufacture one
        # from a physical inventory asset or a selected site.
        return bool(_CANONICAL_BUS.search(payload.question))
    return isinstance(selected, str) and bool(_CANONICAL_ID.fullmatch(selected))

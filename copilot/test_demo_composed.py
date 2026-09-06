from __future__ import annotations

import asyncio

from copilot.demo.composed import ComposedAskBackend
from copilot.routes.ask import AskRequest


class _Backend:
    provider = None

    def __init__(self, result: str) -> None:
        self.result = result
        self.calls = 0

    async def turn(self, payload: AskRequest) -> str:
        self.calls += 1
        return self.result


def _payload(
    question: str,
    scenario_id: str | None,
    element: str | None,
    *,
    region: str | None = None,
    view_mode: str | None = None,
) -> AskRequest:
    context = {
        key: value
        for key, value in {
            "scenario_id": scenario_id,
            "selected_element_id": element,
            "region": region,
            "view_mode": view_mode,
        }.items()
        if value is not None
    }
    return AskRequest(
        attempt_id="composed_0123456789", question=question, context=context or None
    )


def test_forecast_stays_on_the_existing_demo_backend() -> None:
    demo, interactive = _Backend("forecast"), _Backend("interactive")
    result = asyncio.run(
        ComposedAskBackend(demo=demo, interactive=interactive).turn(
            _payload("Show JEPA forecast", None, None)
        )
    )
    assert result == "forecast"
    assert (demo.calls, interactive.calls) == (1, 0)


def test_texas_canonical_interactive_request_uses_shared_interactive_backend() -> None:
    demo, interactive = _Backend("demo"), _Backend("cascade")
    result = asyncio.run(
        ComposedAskBackend(demo=demo, interactive=interactive).turn(
            _payload("Run cascade", "uri_2021", "line:973")
        )
    )
    assert result == "cascade"
    assert (demo.calls, interactive.calls) == (0, 1)


def test_current_ui_failure_wording_uses_shared_interactive_backend() -> None:
    demo, interactive = _Backend("demo"), _Backend("cascade")
    result = asyncio.run(
        ComposedAskBackend(demo=demo, interactive=interactive).turn(
            _payload("Simulate this failure", "uri_2021", "line:973")
        )
    )
    assert result == "cascade"
    assert (demo.calls, interactive.calls) == (0, 1)


def test_component_failure_scenario_prefill_routes_to_live_cascade() -> None:
    demo, interactive = _Backend("demo"), _Backend("cascade")
    result = asyncio.run(
        ComposedAskBackend(demo=demo, interactive=interactive).turn(
            _payload(
                "Run a synthetic component-failure scenario for line:973 in Uri 2021 at hour 0.",
                "uri_2021",
                "line:973",
            )
        )
    )
    assert result == "cascade"
    assert (demo.calls, interactive.calls) == (0, 1)


def test_texas_redundancy_uses_an_explicit_model_bus_without_an_asset_join() -> None:
    demo, interactive = _Backend("demo"), _Backend("redundancy")
    result = asyncio.run(
        ComposedAskBackend(demo=demo, interactive=interactive).turn(
            _payload("Check redundancy for bus 42", "uri_2021", None)
        )
    )
    assert result == "redundancy"
    assert (demo.calls, interactive.calls) == (0, 1)


def test_minnesota_interactive_request_returns_a_boundary_without_calling_texas_core() -> (
    None
):
    demo, interactive = _Backend("demo"), _Backend("interactive")
    result = asyncio.run(
        ComposedAskBackend(demo=demo, interactive=interactive).turn(
            _payload("Run cascade", "mn_winter_2023_snow", "line:973")
        )
    )
    assert result.narration.status == "unavailable"
    assert (demo.calls, interactive.calls) == (0, 0)


def test_inventory_view_rejects_texas_interactive_tool_even_with_a_texas_scenario() -> (
    None
):
    demo, interactive = _Backend("demo"), _Backend("interactive")
    result = asyncio.run(
        ComposedAskBackend(demo=demo, interactive=interactive).turn(
            _payload(
                "Run cascade",
                "uri_2021",
                "line:973",
                region="texas",
                view_mode="physical_inventory",
            )
        )
    )
    assert result.narration.status == "unavailable"
    assert (demo.calls, interactive.calls) == (0, 0)

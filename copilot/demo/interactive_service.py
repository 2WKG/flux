"""Concrete bridge over the one shared interactive simulation service."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from copilot.api import ApiError
from copilot.demo.interactive import Intent, InteractiveEvidence
from copilot.tools.schemas import ArtifactRef

_BUS_ID = re.compile(r"\bbus\s*[:#]?\s*(\d+)\b", re.IGNORECASE)


class InteractiveServiceBridge:
    """Call the shared service directly, preserving its edit registry and outputs."""

    def __init__(self, service: Any) -> None:
        self._service = service

    async def execute(
        self, intent: Intent, payload: Mapping[str, object]
    ) -> InteractiveEvidence:
        try:
            response = await self._call(intent, payload)
        except (ApiError, RuntimeError, TypeError, ValueError) as exc:
            return InteractiveEvidence(
                status="unavailable", result={}, reason=_safe_reason(exc)
            )
        if not isinstance(response, dict):
            return InteractiveEvidence(
                status="unavailable",
                result={},
                reason="The interactive service returned an invalid result.",
            )
        if intent == "cascade":
            response = dict(response)
            data = response.get("data")
            if isinstance(data, dict):
                response["scene_action"] = {
                    "kind": "synthetic_cascade_current",
                    "persisted": False,
                    "run_id": data.get("run_id"),
                    "scenario_id": data.get("scenario_id"),
                    "hour": data.get("hour"),
                    "element_ids": [
                        item.get("element_id")
                        for item in data.get("tripped_element_ids", [])
                        if isinstance(item, dict)
                        and isinstance(item.get("element_id"), str)
                    ],
                    # Keep this exact ordered tool output for scene playback;
                    # it is a current write=False run, not persisted evidence.
                    "timeline": data.get("tripped_element_ids", []),
                    "topology": data.get("topology"),
                    "synthetic": data.get("synthetic"),
                    "solver": data.get("solver"),
                    "model_fidelity": response.get("model_fidelity"),
                    "network_provenance": response.get("network_provenance"),
                    "limitations": response.get("limitations", []),
                }
        return InteractiveEvidence(
            status="available",
            result=response,
            provenance=(
                ArtifactRef(
                    artifact_id="tx:synthetic:interactive-service",
                    artifact_version="current",
                    source_kind="simulated",
                    source_ref="copilot.interactive_routes.InteractiveService",
                ),
            ),
            limitations=tuple(str(item) for item in response.get("limitations", ())),
        )

    async def _call(
        self, intent: Intent, payload: Mapping[str, object]
    ) -> dict[str, object]:
        from copilot.interactive_routes import (
            CascadeRequest,
            EditOperation,
            ScenarioEditRequest,
            SitingSearchRequest,
        )

        scenario_id = str(payload.get("scenario_id", "interactive"))
        hour = int(payload.get("hour", 0))
        selected = payload.get("selected_element_id")
        if intent == "scenario_edit":
            if not isinstance(selected, str):
                raise ValueError(
                    "Select a canonical synthetic element before editing a scenario."
                )
            return await self._service.scenario_edit(
                ScenarioEditRequest(
                    base_scenario_id=scenario_id,
                    hour=hour,
                    ops=[EditOperation(op="outage", element_id=selected)],
                )
            )
        if intent == "cascade":
            if not isinstance(selected, str):
                raise ValueError(
                    "Select a canonical synthetic element before running a cascade."
                )
            return await self._service.cascade(
                CascadeRequest(
                    element_ids=[selected], scenario_id=scenario_id, hour=hour
                )
            )
        if intent == "balance":
            return await self._service.balance(scenario_id=scenario_id, hour=hour)
        if intent == "redundancy":
            bus_id = _bus_id_from(payload)
            return await self._service.redundancy(
                bus_id=bus_id, scenario_id=scenario_id, hour=hour
            )
        unit_mw = payload.get("unit_mw")
        if not isinstance(unit_mw, int | float):
            raise TypeError("Choose a unit size before searching synthetic placements.")
        return await self._service.siting_search(
            SitingSearchRequest(
                kind="synthetic_generation",
                unit_mw=float(unit_mw),
                scenario_id=scenario_id,
                hour=hour,
                n=3,
            )
        )


def _bus_id_from(payload: Mapping[str, object]) -> int:
    question = payload.get("question")
    match = _BUS_ID.search(question) if isinstance(question, str) else None
    if match is None:
        raise ValueError(
            "Name a canonical model bus, for example 'bus 42', to inspect redundancy."
        )
    return int(match.group(1))


def _safe_reason(exc: Exception) -> str:
    message = str(exc)
    if message and len(message) <= 320:
        return message
    return "The interactive simulation tool is unavailable."

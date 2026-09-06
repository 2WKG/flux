"""Name -> local executor bindings for the frozen model-facing tool contract.

`copilot/tools/schemas.py` is the frozen contract and is not edited here.  This
registry binds the subset of those tools that have a **production** executor in
this checkout to that executor and to spec 05's per-tool timeout.

A frozen tool with no production executor is deliberately *absent* rather than
stubbed.  Absence has two consequences, both of them the honest ones: the
planner is never shown a tool that cannot run, and a name that reaches the loop
without a binding is reported unavailable instead of answered.  Adding a tool
here is exactly one thing -- binding its existing executor -- and never
inventing a payload for it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from copilot.config import Settings
from copilot.tools.causal_query import causal_query
from copilot.tools.schemas import (
    CausalQueryInput,
    ContractModel,
    ToolOutput,
    TopLinesInput,
)
from copilot.tools_lines import TopLinesReader

# Spec 05 §"Tool-use loop" fixes a per-tool wall-clock bound.  Only the bounds
# for tools this registry can actually bind are restated; the rest stay in the
# spec until their executor exists.
TOOL_TIMEOUT_SECONDS: Mapping[str, float] = MappingProxyType(
    {"top_lines": 5.0, "causal_query": 5.0}
)


@dataclass(frozen=True)
class RegisteredTool:
    """One frozen tool name bound to a local, blocking executor and a bound."""

    name: str
    timeout_seconds: float
    run: Callable[[ContractModel], ToolOutput]


def build_tool_registry(settings: Settings) -> Mapping[str, RegisteredTool]:
    """Bind every frozen tool that has a production executor in this checkout.

    Construction opens no database connection and reads no artifact: each
    executor resolves its own evidence when it is called, and reports the
    documented unavailable result when that evidence is missing.
    """

    reader = TopLinesReader(settings.duckdb_path)

    def run_top_lines(payload: ContractModel) -> ToolOutput:
        if not isinstance(
            payload, TopLinesInput
        ):  # pragma: no cover - caller-validated
            raise TypeError("top_lines requires a validated TopLinesInput")
        return reader.top_lines(payload.region, payload.tech, payload.n)

    def run_causal_query(payload: ContractModel) -> ToolOutput:
        if not isinstance(
            payload, CausalQueryInput
        ):  # pragma: no cover - caller-validated
            raise TypeError("causal_query requires a validated CausalQueryInput")
        return causal_query(
            kind=payload.kind,
            county_fips=payload.county_fips,
            scenario_id=payload.scenario_id,
            site_id=payload.site_id,
            capacity_mw=payload.capacity_mw,
            treatment=payload.treatment,
        )

    registered = (
        RegisteredTool("top_lines", TOOL_TIMEOUT_SECONDS["top_lines"], run_top_lines),
        RegisteredTool(
            "causal_query", TOOL_TIMEOUT_SECONDS["causal_query"], run_causal_query
        ),
    )
    return MappingProxyType({tool.name: tool for tool in registered})

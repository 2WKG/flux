"""Contracts for a truthful demo adapter.

The demo route deliberately owns no grid calculations, database reads, or model
calls.  Integration supplies a bridge built on accepted read routes and the
Texas synthetic cascade tool.  That makes it possible to show what is actually
available without turning an absent model or artifact into a plausible answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DemoCapability(BaseModel):
    """One user-visible capability with its truth label and limitations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=80)
    state: Literal["tx", "mn", "multi_state"]
    status: Literal["available", "synthetic", "aggregate", "unavailable"]
    label: str = Field(min_length=1, max_length=240)
    source: str | None = Field(default=None, min_length=1, max_length=1_024)
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=12)


class DemoToolResult(BaseModel):
    """A bridge result as shown to the user in an ordered demo card.

    Available results must carry named provenance.  ``data`` is passed through
    unchanged, so numerical fields always remain inside the named tool result
    which produced them; narration never recomputes or summarizes a number.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["available", "unavailable"]
    label: str = Field(min_length=1, max_length=240)
    data: Mapping[str, object] = Field(default_factory=dict)
    provenance: tuple[str, ...] = Field(default_factory=tuple, max_length=24)
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    reason: str | None = Field(default=None, min_length=1, max_length=320)

    @model_validator(mode="after")
    def _available_results_name_a_source(self) -> DemoToolResult:
        if self.status == "available" and not self.provenance:
            raise ValueError("available demo tool results require provenance")
        if self.status == "unavailable" and self.reason is None:
            raise ValueError("unavailable demo tool results require a reason")
        return self


class DemoToolBridge(Protocol):
    """Integration seam for deterministic demo intents.

    Implementations may call the existing scenario/layer/prediction reads or
    the Texas synthetic cascade adapter.  Minnesota calls must remain aggregate
    or inventory-only until a validated topology contract exists.
    """

    async def capabilities(self) -> tuple[DemoCapability, ...]: ...

    async def execute(
        self, tool: str, arguments: Mapping[str, object]
    ) -> DemoToolResult: ...

"""Declarative baseline and proposed parameters for reconductoring.

This module deliberately records a proposed reconductoring change without
ranking it, comparing it to DLR, or inventing a value for incomplete input.
Those responsibilities belong to the subsequent line-upgrade artifacts.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Frozen(BaseModel):
    """Strict immutable records keep an artifact reproducible after creation."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class Quantity(Frozen):
    """A positive physical value paired with its explicit unit."""

    value: float = Field(gt=0.0)
    unit: Literal["MW", "kV", "kcmil"]


class Evidence(Frozen):
    """The source for a parameter and any declared modelling assumption."""

    source: str = Field(min_length=1)
    assumption: str | None = None


class ConductorParameters(Frozen):
    """One conductor and the electrical ratings used to describe it."""

    name: str = Field(min_length=1)
    material: str = Field(min_length=1)
    size: Quantity
    thermal_rating: Quantity
    nominal_voltage: Quantity
    evidence: Evidence

    @model_validator(mode="after")
    def _units_match_parameter(self) -> ConductorParameters:
        if self.size.unit != "kcmil":
            raise ValueError("conductor size must use kcmil")
        if self.thermal_rating.unit != "MW":
            raise ValueError("thermal rating must use MW")
        if self.nominal_voltage.unit != "kV":
            raise ValueError("nominal voltage must use kV")
        return self


class ScenarioLink(Frozen):
    """The scenario and optional baseline run that this change refers to."""

    scenario_id: str = Field(min_length=1)
    baseline_run_id: str | None = None


class ReconductorParameterArtifact(Frozen):
    """A valid, scenario-linked proposal with all ratings stated explicitly.

    The proposal contains no calculated score or DLR result.  Consumers can
    safely pass this immutable record into their own intervention or scoring
    layers without losing the original conductor assumptions.
    """

    line_id: int = Field(ge=0)
    scenario: ScenarioLink
    baseline: ConductorParameters
    proposed: ConductorParameters
    changed_assumptions: tuple[str, ...] = Field(min_length=1)
    validity_status: Literal["valid"] = "valid"

    @model_validator(mode="after")
    def _proposal_increases_thermal_rating(self) -> ReconductorParameterArtifact:
        if self.proposed.thermal_rating.value <= self.baseline.thermal_rating.value:
            raise ValueError("proposed thermal rating must exceed the baseline rating")
        if self.proposed.nominal_voltage.value != self.baseline.nominal_voltage.value:
            raise ValueError("reconductoring must retain the baseline nominal voltage")
        return self

    def canonical_json(self) -> str:
        """Return a stable serialized form for identical inputs.

        Sorting keys makes this suitable for deterministic artifact comparisons
        and hashing by downstream code without imposing a storage schema here.
        """

        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )

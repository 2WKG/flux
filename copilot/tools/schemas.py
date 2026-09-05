"""Strict input and evidence-bound output contracts for Copilot tools.

This module owns contracts only. Tool implementations, DuckDB access, retrieval,
and model-provider calls belong to their dedicated units. Every model-facing
schema is closed to unknown fields and every returned value is either linked to
an artifact/retrieval chunk or represented as an explicit unavailable result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

type ScenarioId = Literal[
    "uri_2021", "beryl_2024", "helene_2024", "forecast_72h"
]
type ToolStatus = Literal["available", "unavailable"]
type UnavailableCode = Literal[
    "artifact_unavailable",
    "invalid_prerequisite",
    "unsupported_request",
    "insufficient_evidence",
]
# Tool payload details can be nested arbitrarily, while their enclosing result
# models remain typed. Implementations validate JSON serializability at their
# boundary with ``validate_json_value`` below.
type JsonValue = Any


class ContractModel(BaseModel):
    """Base model that rejects fields outside the declared contract."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ArtifactRef(ContractModel):
    artifact_id: Annotated[str, Field(min_length=1, max_length=256)]
    artifact_version: Annotated[str, Field(min_length=1, max_length=256)]
    source_kind: Literal["fixture", "observed", "simulated", "heuristic", "retrieval"]
    source_ref: Annotated[str, Field(min_length=1, max_length=2_048)]


class Citation(ContractModel):
    document: Annotated[str, Field(min_length=1, max_length=256)]
    locator: Annotated[str, Field(min_length=1, max_length=256)]
    chunk_id: Annotated[str | None, Field(max_length=256)] = None


class Unavailable(ContractModel):
    code: UnavailableCode
    reason: Annotated[str, Field(min_length=1, max_length=1_024)]
    retryable: bool = False


class ToolOutput(ContractModel):
    """Shared result envelope for every tool implementation.

    ``data`` has a tool-specific typed model in each registry definition. The
    envelope makes provenance and unavailable behavior uniform before a caller
    reads the payload.
    """

    status: ToolStatus
    provenance: list[ArtifactRef] = Field(default_factory=list, max_length=50)
    citations: list[Citation] = Field(default_factory=list, max_length=50)
    unavailable: Unavailable | None = None

    @model_validator(mode="after")
    def unavailable_matches_status(self) -> ToolOutput:
        if self.status == "unavailable" and self.unavailable is None:
            raise ValueError("unavailable results require an unavailable reason")
        if self.status == "available" and self.unavailable is not None:
            raise ValueError("available results cannot carry an unavailable reason")
        return self


class ToolResult[PayloadT: ContractModel](ToolOutput):
    """An evidence-bound tool result with a typed payload on available paths."""

    data: PayloadT | None = None

    @model_validator(mode="after")
    def payload_matches_status(self) -> ToolResult[PayloadT]:
        if self.status == "available" and self.data is None:
            raise ValueError("available results require typed data")
        if self.status == "available" and not self.provenance:
            raise ValueError("available results require artifact or retrieval provenance")
        if self.status == "unavailable" and self.data is not None:
            raise ValueError("unavailable results cannot carry data")
        return self


class PredictOutageInput(ContractModel):
    county_fips: Annotated[str, Field(pattern=r"^\d{5}$")]
    scenario_id: ScenarioId
    horizon_h: Annotated[int, Field(ge=1, le=72)] = 72


class RunCascadeInput(ContractModel):
    element_ids: Annotated[list[Annotated[str, Field(min_length=1, max_length=128)]], Field(min_length=1, max_length=25)]
    scenario_id: ScenarioId
    hour: Annotated[int, Field(ge=0, le=167)]


class ScoreSiteInput(ContractModel):
    site_id: Annotated[str, Field(min_length=1, max_length=128)]
    unit_mw: Literal[300, 1000]
    scenario_id: ScenarioId


class TopLinesInput(ContractModel):
    region: Annotated[str, Field(min_length=1, max_length=64)]
    tech: Literal["dlr", "reconductor", "any"]
    n: Annotated[int, Field(ge=1, le=50)] = 10


class SqlInput(ContractModel):
    query: Annotated[str, Field(min_length=1, max_length=5_000)]


class CiteInput(ContractModel):
    query: Annotated[str, Field(min_length=1, max_length=1_000)]
    k: Annotated[int, Field(ge=1, le=10)] = 5


class CompareInterventionsInput(ContractModel):
    scenario_id: ScenarioId
    intervention_ids: Annotated[
        list[Annotated[str, Field(pattern=r"^(site:[^@:\s]+(?:@(300|1000))?|line:[^:\s]+)$")]],
        Field(min_length=1, max_length=5),
    ]


class TopCriticalElementsInput(ContractModel):
    region: Annotated[str, Field(min_length=1, max_length=64)]
    n: Annotated[int, Field(ge=1, le=50)] = 10


class CausalQueryInput(ContractModel):
    kind: Literal["attribution", "effect", "counterfactual"]
    county_fips: Annotated[str | None, Field(pattern=r"^\d{5}$")] = None
    scenario_id: ScenarioId = "uri_2021"
    site_id: Annotated[str | None, Field(min_length=1, max_length=128)] = None
    capacity_mw: Literal[300, 1000] | None = None
    treatment: Literal["hardening_saidi", "firm_generation_100mw"] | None = None


class OutagePoint(ContractModel):
    ts: Annotated[str, Field(min_length=1, max_length=64)]
    p_out: Annotated[float, Field(ge=0, le=1)]
    customers_at_risk: Annotated[int, Field(ge=0)]


class PredictOutageData(ContractModel):
    county_fips: Annotated[str, Field(pattern=r"^\d{5}$")]
    scenario_id: ScenarioId
    horizon_h: Annotated[int, Field(ge=1, le=72)]
    peak_p_out: Annotated[float, Field(ge=0, le=1)]
    peak_ts: str
    customers_at_risk: Annotated[int, Field(ge=0)]
    driver: Annotated[str, Field(min_length=1, max_length=256)]
    series: Annotated[list[OutagePoint], Field(max_length=24)]


class CascadeData(ContractModel):
    run_id: Annotated[str, Field(min_length=1, max_length=256)]
    scenario_id: ScenarioId
    hour: Annotated[int, Field(ge=0)]
    tripped_element_ids: list[str]
    lost_load_mw: Annotated[float, Field(ge=0)]
    counties_dark: list[Annotated[str, Field(pattern=r"^\d{5}$")]]
    steps: Annotated[int, Field(ge=0)]


class SiteScoreData(ContractModel):
    site_id: Annotated[str, Field(min_length=1, max_length=128)]
    scenario_id: ScenarioId
    unit_mw: Literal[300, 1000]
    safety_score: Annotated[float, Field(ge=0)]
    grid_value_score: Annotated[float, Field(ge=0)]
    lol_reduction_mwh: Annotated[float, Field(ge=0)]


class LinesData(ContractModel):
    region: Annotated[str, Field(min_length=1, max_length=64)]
    tech: Literal["dlr", "reconductor", "any"]
    lines: list[dict[str, JsonValue]]


class SqlData(ContractModel):
    columns: list[str]
    rows: Annotated[list[list[JsonValue]], Field(max_length=200)]
    row_count: Annotated[int, Field(ge=0, le=200)]
    truncated: bool


class CiteData(ContractModel):
    hits: list[Citation]


class InterventionsData(ContractModel):
    scenario_id: ScenarioId
    baseline_run_id: Annotated[str, Field(min_length=1, max_length=256)]
    interventions: list[dict[str, JsonValue]]
    assumptions: list[str]


class CriticalElementsData(ContractModel):
    region: Annotated[str, Field(min_length=1, max_length=64)]
    n: Annotated[int, Field(ge=1, le=50)]
    scenario_ids: list[ScenarioId]
    elements: list[dict[str, JsonValue]]
    partial: bool = False


class CausalData(ContractModel):
    answer_numbers: dict[str, float | int]
    method: Annotated[str, Field(min_length=1, max_length=256)]
    assumptions: list[str]
    interval: tuple[float, float] | None = None
    evidence_rows: list[dict[str, JsonValue]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[ContractModel]
    output_model: type[BaseModel]


TOOL_REGISTRY: tuple[ToolDefinition, ...] = (
    ToolDefinition("predict_outage", "Read a persisted county outage prediction.", PredictOutageInput, ToolResult[PredictOutageData]),
    ToolDefinition("run_cascade", "Read or run the bounded cascade contract.", RunCascadeInput, ToolResult[CascadeData]),
    ToolDefinition("score_site", "Read a bounded site score.", ScoreSiteInput, ToolResult[SiteScoreData]),
    ToolDefinition("top_lines", "Read deterministic source-labeled line rankings.", TopLinesInput, ToolResult[LinesData]),
    ToolDefinition("sql", "Execute a bounded read-only analytical query.", SqlInput, ToolResult[SqlData]),
    ToolDefinition("cite", "Retrieve citation-preserving corpus chunks.", CiteInput, ToolResult[CiteData]),
    ToolDefinition("compare_interventions", "Compare up to five named interventions.", CompareInterventionsInput, ToolResult[InterventionsData]),
    ToolDefinition("top_critical_elements", "Rank persisted cascade reach by element.", TopCriticalElementsInput, ToolResult[CriticalElementsData]),
    ToolDefinition("causal_query", "Read a validated causal artifact or explicit unavailable result.", CausalQueryInput, ToolResult[CausalData]),
)

_REGISTRY_BY_NAME = {definition.name: definition for definition in TOOL_REGISTRY}


def _strict_schema(value: Any) -> Any:
    """Make every object closed and every declared property explicit for strict tools."""

    if isinstance(value, dict):
        result = {key: _strict_schema(item) for key, item in value.items()}
        if result.get("type") == "object" or "properties" in result:
            result["additionalProperties"] = False
            if "properties" in result:
                # Anthropic strict tool schemas require every object property to
                # be present. Python defaults remain available to direct callers.
                result["required"] = list(result["properties"])
        return result
    if isinstance(value, list):
        return [_strict_schema(item) for item in value]
    return value


def tool_schema(definition: ToolDefinition) -> dict[str, Any]:
    return {
        "name": definition.name,
        "description": definition.description,
        "strict": True,
        "input_schema": _strict_schema(definition.input_model.model_json_schema()),
    }


TOOL_SCHEMAS: tuple[dict[str, Any], ...] = tuple(tool_schema(definition) for definition in TOOL_REGISTRY)


def validate_tool_input(name: str, payload: dict[str, JsonValue]) -> ContractModel:
    """Validate a tool payload without dispatching a database or network call."""

    try:
        definition = _REGISTRY_BY_NAME[name]
    except KeyError as error:
        raise ValueError(f"unsupported tool: {name}") from error
    return definition.input_model.model_validate(payload)


def unavailable_output(
    code: UnavailableCode,
    reason: str,
    *,
    provenance: list[ArtifactRef] | None = None,
) -> ToolOutput:
    """Construct the canonical unavailable result used by every later tool implementation."""

    return ToolOutput(
        status="unavailable",
        provenance=provenance or [],
        unavailable=Unavailable(code=code, reason=reason),
    )


def validate_json_value(value: Any) -> JsonValue:
    """Fail before an implementation emits a non-JSON-compatible tool value."""

    return json.loads(json.dumps(value, allow_nan=False))

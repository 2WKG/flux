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


class Unavailable(ContractModel):
    code: UnavailableCode
    reason: Annotated[str, Field(min_length=1, max_length=1_024)]
    retryable: bool = False


class ToolOutput(ContractModel):
    """Evidence metadata placed beside each tool's documented top-level fields."""

    status: ToolStatus
    provenance: list[ArtifactRef] = Field(default_factory=list, max_length=50)
    unavailable: Unavailable | None = None

    @model_validator(mode="after")
    def unavailable_matches_status(self) -> ToolOutput:
        if self.status == "unavailable" and self.unavailable is None:
            raise ValueError("unavailable results require an unavailable reason")
        if self.status == "available" and self.unavailable is not None:
            raise ValueError("available results cannot carry an unavailable reason")
        if self.status == "available" and not self.provenance:
            raise ValueError("available results require artifact or retrieval provenance")
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


class PredictOutageData(ToolOutput):
    county_fips: Annotated[str, Field(pattern=r"^\d{5}$")]
    county_name: Annotated[str, Field(min_length=1, max_length=256)]
    scenario_id: ScenarioId
    horizon_h: Annotated[int, Field(ge=1, le=72)]
    peak_p_out: Annotated[float, Field(ge=0, le=1)]
    peak_ts: str
    customers_at_risk: Annotated[int, Field(ge=0)]
    driver: Annotated[str, Field(min_length=1, max_length=256)]
    series: Annotated[list[OutagePoint], Field(max_length=24)]


class CriticalLoadLoss(ContractModel):
    id: Annotated[str, Field(min_length=1, max_length=128)]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    kind: Literal["dod", "hospital", "water"]
    hour_lost: Annotated[int, Field(ge=0)]


class TrippedElement(ContractModel):
    element_id: Annotated[str, Field(min_length=1, max_length=128)]
    kind: Literal["line", "trafo", "gen", "bus"]
    stage: Annotated[int, Field(ge=0)]
    cause: Literal["weather", "overload", "island", "forced"]


class CascadeData(ToolOutput):
    run_id: Annotated[str, Field(min_length=1, max_length=256)]
    scenario_id: ScenarioId
    hour: Annotated[int, Field(ge=0)]
    tripped_element_ids: list[TrippedElement]
    lost_load_mw: Annotated[float, Field(ge=0)]
    counties_dark: list[Annotated[str, Field(pattern=r"^\d{5}$")]]
    critical_loads_lost: list[CriticalLoadLoss]
    steps: Annotated[int, Field(ge=0)]


class SiteScoreData(ToolOutput):
    site_id: Annotated[str, Field(min_length=1, max_length=128)]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    kind: Annotated[str, Field(min_length=1, max_length=128)]
    county_fips: Annotated[str, Field(pattern=r"^\d{5}$")]
    scenario_id: ScenarioId
    unit_mw: Literal[300, 1000]
    safety_score: Annotated[float, Field(ge=0)]
    safety_flags: list[str]
    grid_value_score: Annotated[float, Field(ge=0)]
    lol_reduction_mwh: Annotated[float, Field(ge=0)]
    congestion_relief_pct: Annotated[float, Field(ge=0)]
    blackstart_reach_mw: Annotated[float, Field(ge=0)]
    critical_loads_protected: list[str]
    regulatory_path: Annotated[str, Field(min_length=1, max_length=512)]


class LineSummary(ContractModel):
    line_id: Annotated[str, Field(min_length=1, max_length=128)]
    from_bus: Annotated[str, Field(min_length=1, max_length=128)]
    to_bus: Annotated[str, Field(min_length=1, max_length=128)]
    kv: Annotated[float, Field(gt=0)]
    congestion_usd_yr: Annotated[float, Field(ge=0)]
    uplift_mw: Annotated[float, Field(ge=0)]
    cost_usd: Annotated[float, Field(ge=0)]
    mw_per_musd: Annotated[float, Field(ge=0)]
    ferc_screen_pass: bool
    spark_eligible: bool


class LinesData(ToolOutput):
    region: Annotated[str, Field(min_length=1, max_length=64)]
    tech: Literal["dlr", "reconductor", "any"]
    lines: list[LineSummary]


class SqlData(ToolOutput):
    columns: list[str]
    rows: Annotated[list[list[JsonValue]], Field(max_length=200)]
    row_count: Annotated[int, Field(ge=0, le=200)]
    truncated: bool


class RetrievalHit(ContractModel):
    doc: Annotated[str, Field(min_length=1, max_length=256)]
    title: Annotated[str, Field(min_length=1, max_length=512)]
    page: Annotated[int, Field(ge=1)]
    chunk_id: Annotated[str, Field(min_length=1, max_length=256)]
    score: float
    text: Annotated[str, Field(min_length=1, max_length=1_200)]


class CiteData(ToolOutput):
    hits: list[RetrievalHit]


class Intervention(ContractModel):
    intervention_id: Annotated[str, Field(min_length=1, max_length=256)]
    kind: Literal["site", "line"]
    run_id: Annotated[str, Field(min_length=1, max_length=256)]
    lol_reduction_mwh: Annotated[float, Field(ge=0)]
    customer_hours_avoided: Annotated[float, Field(ge=0)]
    critical_loads_protected: list[str]


class InterventionsData(ToolOutput):
    scenario_id: ScenarioId
    baseline_run_id: Annotated[str, Field(min_length=1, max_length=256)]
    interventions: list[Intervention]
    assumptions: list[str]


class CriticalElement(ContractModel):
    element_id: Annotated[str, Field(min_length=1, max_length=128)]
    kind: Literal["line", "bus", "gen"]
    lost_load_mw: Annotated[float, Field(ge=0)]
    critical_loads_lost: list[str]
    runs: Annotated[int, Field(ge=0)]


class CriticalElementsData(ToolOutput):
    region: Annotated[str, Field(min_length=1, max_length=64)]
    n: Annotated[int, Field(ge=1, le=50)]
    scenario_ids: list[ScenarioId]
    elements: list[CriticalElement]
    partial: bool = False


class CausalData(ToolOutput):
    answer_numbers: dict[str, float | int]
    method: Annotated[str, Field(min_length=1, max_length=256)]
    assumptions: list[str]
    interval: Annotated[list[float], Field(min_length=2, max_length=2)] | None = None
    evidence_rows: list[dict[str, JsonValue]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[ContractModel]
    # The first model is the documented available result; ToolOutput represents
    # the canonical unavailable result shared by every tool.
    output_model: tuple[type[BaseModel], type[ToolOutput]]


TOOL_REGISTRY: tuple[ToolDefinition, ...] = (
    ToolDefinition("predict_outage", "Read a persisted county outage prediction.", PredictOutageInput, (PredictOutageData, ToolOutput)),
    ToolDefinition("run_cascade", "Read or run the bounded cascade contract.", RunCascadeInput, (CascadeData, ToolOutput)),
    ToolDefinition("score_site", "Read a bounded site score.", ScoreSiteInput, (SiteScoreData, ToolOutput)),
    ToolDefinition("top_lines", "Read deterministic source-labeled line rankings.", TopLinesInput, (LinesData, ToolOutput)),
    ToolDefinition("sql", "Execute a bounded read-only analytical query.", SqlInput, (SqlData, ToolOutput)),
    ToolDefinition("cite", "Retrieve citation-preserving corpus chunks.", CiteInput, (CiteData, ToolOutput)),
    ToolDefinition("compare_interventions", "Compare up to five named interventions.", CompareInterventionsInput, (InterventionsData, ToolOutput)),
    ToolDefinition("top_critical_elements", "Rank persisted cascade reach by element.", TopCriticalElementsInput, (CriticalElementsData, ToolOutput)),
    ToolDefinition("causal_query", "Read a validated causal artifact or explicit unavailable result.", CausalQueryInput, (CausalData, ToolOutput)),
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

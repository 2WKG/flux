"""Strict input and evidence-bound output contracts for Copilot tools.

This module owns contracts only. Tool implementations, DuckDB access, retrieval,
and model-provider calls belong to their dedicated units. Every model-facing
schema is closed to unknown fields and every returned value is either linked to
an artifact/retrieval chunk or represented as an explicit unavailable result.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type ScenarioId = Literal["uri_2021", "beryl_2024", "helene_2024", "forecast_72h"]
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
            raise ValueError(
                "available results require artifact or retrieval provenance"
            )
        return self


class UnavailableOutput(ToolOutput):
    """The common result shape for tools that cannot produce their payload."""

    status: Literal["unavailable"]


class PredictOutageInput(ContractModel):
    county_fips: Annotated[str, Field(pattern=r"^\d{5}$")]
    scenario_id: ScenarioId
    horizon_h: Annotated[int, Field(ge=1, le=72)] = 72


class RunCascadeInput(ContractModel):
    element_ids: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=128)]],
        Field(min_length=1, max_length=25),
    ]
    scenario_id: ScenarioId
    hour: Annotated[int, Field(ge=0, le=167)]


class ScoreSiteInput(ContractModel):
    site_id: Annotated[str, Field(min_length=1, max_length=128)]
    unit_mw: Literal[300, 1000]
    scenario_id: ScenarioId


TOP_LINES_MAX_LIMIT = 50
"""The largest page a ``top_lines`` read may request."""


class TopLinesInput(ContractModel):
    """Closed, bounded input for the persisted line-upgrade ranking read.

    ``region``, ``tech`` and ``n`` are the complete model-facing input: the
    frozen contract signature ``top_lines(region, tech, n=10)`` from
    ``docs/specs/00-overview.md`` §2.4 and ``05-copilot.md``.  No pagination or
    sort parameter is exposed to the model; the result order is spec 08's
    ``mw_per_musd`` descending and belongs to the ``top_lines`` implementation,
    which must pin it with a behavioural test when it lands.
    """

    region: Annotated[
        str,
        Field(
            min_length=1,
            max_length=64,
            description="Exact persisted region key; no SQL fragment or wildcard syntax.",
        ),
    ]
    tech: Literal["dlr", "reconductor", "any"]
    n: Annotated[
        int,
        Field(
            ge=1,
            le=TOP_LINES_MAX_LIMIT,
            description="Page size; at most 50 persisted ranking rows.",
        ),
    ] = 10


_SQL_INPUT_XOR_SCHEMA = {
    "oneOf": [
        {
            "properties": {
                "query": {"type": "string"},
                "template_id": {"type": "null"},
                "parameters": {},
            },
            "required": ["query"],
        },
        {
            "properties": {
                "query": {"type": "null"},
                "template_id": {"type": "string"},
                "parameters": {},
            },
            "required": ["template_id"],
        },
    ]
}


class SqlInput(ContractModel):
    # The strict model-facing schema requires both declared keys.  Its ``oneOf``
    # then permits exactly one non-null value, matching the runtime validator.
    model_config = ConfigDict(
        extra="forbid", strict=True, json_schema_extra=_SQL_INPUT_XOR_SCHEMA
    )

    query: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=5_000,
            description="Legacy free-form SQL; unavailable when a template registry is configured.",
        ),
    ] = None
    template_id: Annotated[
        str | None,
        Field(
            pattern=r"^[a-z][a-z0-9_]{0,63}$",
            description="Named query advertised by the deployment's approved-template registry.",
        ),
    ] = None
    parameters: Annotated[
        list[str | int | float | bool | None],
        Field(
            default_factory=list,
            max_length=25,
            description="Bound values for positional placeholders in a deployment-owned template.",
        ),
    ]

    @field_validator("parameters")
    @classmethod
    def _parameters_are_finite_json_scalars(
        cls, values: list[str | int | float | bool | None]
    ) -> list[str | int | float | bool | None]:
        if any(
            isinstance(value, float) and not math.isfinite(value) for value in values
        ):
            raise ValueError("SQL parameters must be finite JSON scalars")
        return values

    @model_validator(mode="after")
    def _exactly_one_input(self) -> SqlInput:
        # 00-overview A8 amendment: ``sql`` takes ``query`` XOR ``template_id``.
        # Enforced at the pydantic boundary so neither ``{}`` nor both fields
        # can reach an executor.
        if (self.query is None) == (self.template_id is None):
            raise ValueError("sql requires exactly one of query or template_id")
        return self


class CiteInput(ContractModel):
    query: Annotated[str, Field(min_length=1, max_length=1_000)]
    k: Annotated[int, Field(ge=1, le=10)] = 5


class CompareInterventionsInput(ContractModel):
    scenario_id: ScenarioId
    intervention_ids: Annotated[
        list[
            Annotated[
                str, Field(pattern=r"^(site:[^@:\s]+(?:@(300|1000))?|line:[^:\s]+)$")
            ]
        ],
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


# The interactive core currently supports only its explicitly labelled static
# baseline. These are separate from the historical/persisted scenario tools:
# their strict inputs prevent an agent from relabelling one static simulation as
# a storm replay.
class InteractiveEditOperation(ContractModel):
    op: Literal["outage"]
    element_id: Annotated[str, Field(min_length=1, max_length=160)]


class ScenarioEditInput(ContractModel):
    base_scenario_id: Literal["interactive"] = "interactive"
    ops: Annotated[list[InteractiveEditOperation], Field(min_length=1, max_length=64)]
    hour: Literal[0] = 0
    seed: Literal[0] = 0


class InteractiveCascadeInput(ContractModel):
    element_ids: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=160)]],
        Field(min_length=1, max_length=64),
    ]
    scenario_id: Literal["interactive"] = "interactive"
    hour: Literal[0] = 0
    edit_hash: Annotated[
        str | None,
        Field(default=None, min_length=16, max_length=64, pattern=r"^[a-f0-9]+$"),
    ] = None
    seed: Literal[0] = 0


class BalanceInput(ContractModel):
    scope: Literal["base", "edit"] = "base"
    scenario_id: Literal["interactive"] = "interactive"
    hour: Literal[0] = 0
    seed: Literal[0] = 0
    edit_hash: Annotated[
        str | None,
        Field(default=None, min_length=16, max_length=64, pattern=r"^[a-f0-9]+$"),
    ] = None


class RedundancyInput(ContractModel):
    bus_id: Annotated[int, Field(ge=0)]
    scenario_id: Literal["interactive"] = "interactive"
    hour: Literal[0] = 0
    seed: Literal[0] = 0


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
    scenario_id: Annotated[str, Field(min_length=1, max_length=128)]
    artifact_id: Annotated[str, Field(min_length=1, max_length=256)]
    source_class: Literal["observed", "simulated", "proxy"]
    intervention_type: Literal["dlr", "reconductor"]
    status: Literal["available"]
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
    scenario_id: Annotated[str, Field(min_length=1, max_length=128)]
    artifact_id: Annotated[str, Field(min_length=1, max_length=256)]
    tech: Literal["dlr", "reconductor", "any"]
    lines: list[LineSummary]


class SqlData(ToolOutput):
    columns: list[str]
    rows: Annotated[list[list[JsonValue]], Field(max_length=200)]
    row_count: Annotated[int, Field(ge=0, le=200)]
    truncated: bool


class RetrievalHit(ContractModel):
    content_kind: Literal["fixture", "source"]
    date: Annotated[str | None, Field(max_length=64)]
    doc: Annotated[str, Field(min_length=1, max_length=256)]
    locator: Annotated[str, Field(min_length=1, max_length=256)]
    provenance: dict[
        Annotated[str, Field(min_length=1, max_length=128)],
        Annotated[str, Field(min_length=1, max_length=2_048)],
    ]
    source: Annotated[str, Field(min_length=1, max_length=2_048)]
    title: Annotated[str, Field(min_length=1, max_length=512)]
    page: Annotated[int, Field(ge=1)]
    chunk_id: Annotated[str, Field(min_length=1, max_length=256)]
    score: float
    text: Annotated[str, Field(min_length=1, max_length=1_200)]
    version: Annotated[str, Field(min_length=1, max_length=256)]


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


class CausalVariable(ContractModel):
    """A labeled causal treatment or outcome variable."""

    name: Annotated[str, Field(min_length=1, max_length=256)]
    definition: Annotated[str, Field(min_length=1, max_length=1_024)]
    unit_or_category: Annotated[str, Field(min_length=1, max_length=256)]
    source_id: Annotated[str, Field(min_length=1, max_length=256)]


class CausalTargetPopulation(ContractModel):
    description: Annotated[str, Field(min_length=1, max_length=1_024)]
    geography: Annotated[str, Field(min_length=1, max_length=256)]
    time_window: Annotated[str, Field(min_length=1, max_length=256)]


class CausalQuestion(ContractModel):
    treatment: CausalVariable
    outcome: CausalVariable
    target_population: CausalTargetPopulation


class CausalSource(ContractModel):
    source_id: Annotated[str, Field(min_length=1, max_length=256)]
    name: Annotated[str, Field(min_length=1, max_length=512)]
    version: Annotated[str, Field(min_length=1, max_length=256)]
    locator: Annotated[str, Field(min_length=1, max_length=2_048)]
    coverage: Annotated[str, Field(min_length=1, max_length=1_024)]


class CausalSample(ContractModel):
    unit: Annotated[str, Field(min_length=1, max_length=256)]
    n_total: Annotated[int, Field(ge=0)]
    n_treated: Annotated[int, Field(ge=0)]
    n_control: Annotated[int, Field(ge=0)]
    period: Annotated[str, Field(min_length=1, max_length=1_024)]


class CausalDiagnostic(ContractModel):
    name: Annotated[str, Field(min_length=1, max_length=256)]
    status: Literal["pass"]
    evidence: Annotated[str, Field(min_length=1, max_length=2_048)]


class CausalCitation(ContractModel):
    source_id: Annotated[str, Field(min_length=1, max_length=256)]
    locator: Annotated[str, Field(min_length=1, max_length=2_048)]


class CausalData(ToolOutput):
    answer_numbers: dict[str, float | int]
    method: Annotated[str, Field(min_length=1, max_length=256)]
    assumptions: list[str]
    interval: Annotated[list[float], Field(min_length=2, max_length=2)] | None = None
    evidence_rows: list[dict[str, JsonValue]]
    question: CausalQuestion
    sources: Annotated[list[CausalSource], Field(min_length=1, max_length=50)]
    sample: CausalSample
    diagnostics: Annotated[list[CausalDiagnostic], Field(min_length=1, max_length=50)]
    citations: Annotated[list[CausalCitation], Field(min_length=1, max_length=50)]


class InteractiveData(ToolOutput):
    """A validated envelope from the non-persisting interactive service."""

    status: Literal["available"]
    model_fidelity: Literal["dc_screening"]
    # 00-overview.md §"the only topology label any route emits": this is
    # `pipelines.labels.SYNTHETIC_TOPOLOGY_LABEL` verbatim, not a second spelling.
    network_provenance: Literal["synthetic (ACTIVSg2000)"]
    limitations: Annotated[list[str], Field(min_length=1)]
    data: dict[str, JsonValue]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[ContractModel]
    # The first model is the documented available result; UnavailableOutput is
    # the canonical unavailable result shared by every tool.
    output_model: tuple[type[BaseModel], type[UnavailableOutput]]


TOOL_REGISTRY: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        "predict_outage",
        "Read a persisted county outage prediction.",
        PredictOutageInput,
        (PredictOutageData, UnavailableOutput),
    ),
    ToolDefinition(
        "run_cascade",
        "Read or run the bounded cascade contract.",
        RunCascadeInput,
        (CascadeData, UnavailableOutput),
    ),
    ToolDefinition(
        "score_site",
        "Read a bounded site score.",
        ScoreSiteInput,
        (SiteScoreData, UnavailableOutput),
    ),
    ToolDefinition(
        "top_lines",
        "Read deterministic source-labeled line rankings.",
        TopLinesInput,
        (LinesData, UnavailableOutput),
    ),
    ToolDefinition(
        "sql",
        "Execute a bounded read-only analytical query.",
        SqlInput,
        (SqlData, UnavailableOutput),
    ),
    ToolDefinition(
        "cite",
        "Retrieve citation-preserving corpus chunks.",
        CiteInput,
        (CiteData, UnavailableOutput),
    ),
    ToolDefinition(
        "compare_interventions",
        "Compare up to five named interventions.",
        CompareInterventionsInput,
        (InterventionsData, UnavailableOutput),
    ),
    ToolDefinition(
        "top_critical_elements",
        "Rank persisted cascade reach by element.",
        TopCriticalElementsInput,
        (CriticalElementsData, UnavailableOutput),
    ),
    ToolDefinition(
        "causal_query",
        "Read a validated causal artifact or explicit unavailable result.",
        CausalQueryInput,
        (CausalData, UnavailableOutput),
    ),
    ToolDefinition(
        "scenario_edit",
        "Create one immutable synthetic outage edit on the static interactive baseline.",
        ScenarioEditInput,
        (InteractiveData, UnavailableOutput),
    ),
    ToolDefinition(
        "cascade",
        "Run a bounded synthetic cascade on the static interactive baseline.",
        InteractiveCascadeInput,
        (InteractiveData, UnavailableOutput),
    ),
    ToolDefinition(
        "balance",
        "Read synthetic balance accounting for the static interactive baseline or an edit.",
        BalanceInput,
        (InteractiveData, UnavailableOutput),
    ),
    ToolDefinition(
        "redundancy",
        "Read bounded synthetic topology redundancy for a canonical bus.",
        RedundancyInput,
        (InteractiveData, UnavailableOutput),
    ),
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


TOOL_SCHEMAS: tuple[dict[str, Any], ...] = tuple(
    tool_schema(definition) for definition in TOOL_REGISTRY
)


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
) -> UnavailableOutput:
    """Construct the canonical unavailable result used by every later tool implementation."""

    return UnavailableOutput(
        status="unavailable",
        provenance=provenance or [],
        unavailable=Unavailable(code=code, reason=reason),
    )


def validate_json_value(value: Any) -> JsonValue:
    """Fail before an implementation emits a non-JSON-compatible tool value."""

    return json.loads(json.dumps(value, allow_nan=False))

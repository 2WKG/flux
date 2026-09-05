from __future__ import annotations

import pytest
from pydantic import ValidationError

from copilot.tools.schemas import (
    TOOL_REGISTRY,
    TOOL_SCHEMAS,
    ArtifactRef,
    PredictOutageData,
    PredictOutageInput,
    ToolOutput,
    ToolResult,
    unavailable_output,
    validate_tool_input,
)


def test_registry_has_exactly_the_nine_shared_contract_tools() -> None:
    assert [tool.name for tool in TOOL_REGISTRY] == [
        "predict_outage",
        "run_cascade",
        "score_site",
        "top_lines",
        "sql",
        "cite",
        "compare_interventions",
        "top_critical_elements",
        "causal_query",
    ]


def test_every_model_facing_schema_is_strict_and_closed() -> None:
    for schema in TOOL_SCHEMAS:
        assert schema["strict"] is True
        assert schema["input_schema"]["additionalProperties"] is False
        assert set(schema["input_schema"]["required"]) == set(
            schema["input_schema"]["properties"]
        )


def test_unknown_input_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PredictOutageInput.model_validate(
            {
                "county_fips": "48453",
                "scenario_id": "uri_2021",
                "unexpected": True,
            }
        )


def test_intervention_bound_and_prefix_are_enforced() -> None:
    with pytest.raises(ValidationError):
        validate_tool_input(
            "compare_interventions",
            {
                "scenario_id": "uri_2021",
                "intervention_ids": ["site:one"] * 6,
            },
        )
    with pytest.raises(ValidationError):
        validate_tool_input(
            "compare_interventions",
            {
                "scenario_id": "uri_2021",
                "intervention_ids": ["unprefixed"],
            },
        )


def test_representative_unavailable_output_keeps_provenance() -> None:
    result = unavailable_output(
        "artifact_unavailable",
        "fixture prediction artifact is absent",
        provenance=[
            ArtifactRef(
                artifact_id="outage_predictions",
                artifact_version="fixture-v1",
                source_kind="fixture",
                source_ref="data/duck/grid.duckdb",
            )
        ],
    )
    assert result.status == "unavailable"
    assert result.unavailable is not None
    assert result.unavailable.code == "artifact_unavailable"
    assert result.provenance[0].artifact_id == "outage_predictions"


def test_unavailable_status_cannot_omit_its_reason() -> None:
    with pytest.raises(ValidationError):
        ToolOutput(status="unavailable")


def test_available_result_requires_a_typed_payload() -> None:
    with pytest.raises(ValidationError):
        ToolResult[PredictOutageData](status="available")


def test_available_result_requires_provenance() -> None:
    with pytest.raises(ValidationError, match="provenance"):
        ToolResult[PredictOutageData](
            status="available",
            data=PredictOutageData(
                county_fips="48453",
                scenario_id="uri_2021",
                horizon_h=72,
                peak_p_out=0.5,
                peak_ts="2021-02-16T19:00:00Z",
                customers_at_risk=10,
                driver="fixture",
                series=[],
            ),
        )

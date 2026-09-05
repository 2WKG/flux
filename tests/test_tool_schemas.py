from __future__ import annotations

import pytest
from pydantic import ValidationError

from copilot.tools.schemas import (
    TOP_LINES_DEFAULT_SORT,
    TOP_LINES_MAX_LIMIT,
    TOP_LINES_MAX_OFFSET,
    TOOL_REGISTRY,
    TOOL_SCHEMAS,
    ArtifactRef,
    CascadeData,
    CausalData,
    CiteData,
    PredictOutageData,
    PredictOutageInput,
    ToolOutput,
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


def test_top_lines_schema_has_only_bounded_allowlisted_filters() -> None:
    request = validate_tool_input(
        "top_lines",
        {"region": "ERCOT", "tech": "dlr", "n": TOP_LINES_MAX_LIMIT, "offset": 0},
    )

    assert request.n == TOP_LINES_MAX_LIMIT
    assert request.offset == 0
    assert TOP_LINES_DEFAULT_SORT == "mw_per_musd DESC, cost_usd ASC, line_id ASC"

    for payload in (
        {"region": "ERCOT", "tech": "dlr", "n": TOP_LINES_MAX_LIMIT + 1},
        {"region": "ERCOT", "tech": "dlr", "offset": TOP_LINES_MAX_OFFSET + 1},
        {"region": "ERCOT", "tech": "dlr", "sort": "line_id DESC"},
        {"region": "ERCOT", "tech": "dlr", "owner": "any"},
    ):
        with pytest.raises(ValidationError):
            validate_tool_input("top_lines", payload)


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


def test_real_tool_contract_accepts_its_unavailable_output() -> None:
    result = unavailable_output("artifact_unavailable", "fixture prediction artifact is absent")
    definition = next(tool for tool in TOOL_REGISTRY if tool.name == "predict_outage")

    validated = []
    for model in definition.output_model:
        try:
            validated.append(model.model_validate(result.model_dump()))
        except ValidationError:
            pass

    assert any(output.status == "unavailable" for output in validated)


def test_unavailable_output_variant_rejects_incomplete_available_result() -> None:
    definition = next(tool for tool in TOOL_REGISTRY if tool.name == "predict_outage")

    with pytest.raises(ValidationError):
        definition.output_model[1].model_validate(
            {
                "status": "available",
                "provenance": [
                    {
                        "artifact_id": "outage_predictions",
                        "artifact_version": "fixture-v1",
                        "source_kind": "fixture",
                        "source_ref": "data/duck/grid.duckdb",
                    }
                ],
            }
        )


def test_unavailable_status_cannot_omit_its_reason() -> None:
    with pytest.raises(ValidationError):
        ToolOutput(status="unavailable")


def test_available_output_requires_provenance() -> None:
    with pytest.raises(ValidationError, match="provenance"):
        ToolOutput(status="available")


def test_documented_outage_fields_are_top_level() -> None:
    fields = PredictOutageData.model_fields
    assert {"county_fips", "county_name", "scenario_id", "horizon_h", "peak_p_out", "series"} <= set(fields)
    assert "data" not in fields


def test_consumer_shaped_outage_response_validates_with_top_level_payload() -> None:
    response = PredictOutageData(
        status="available",
        provenance=[
            ArtifactRef(
                artifact_id="outage_predictions",
                artifact_version="fixture-v1",
                source_kind="fixture",
                source_ref="data/duck/grid.duckdb",
            )
        ],
        county_fips="48453",
        county_name="Travis",
        scenario_id="uri_2021",
        horizon_h=72,
        peak_p_out=0.5,
        peak_ts="2021-02-16T19:00:00Z",
        customers_at_risk=10,
        driver="fixture",
        series=[],
    )
    assert response.county_name == "Travis"
    assert "data" not in response.model_dump()


def test_cite_hits_match_the_shared_retrieval_shape() -> None:
    hit = CiteData.model_fields["hits"].annotation
    assert hit is not None
    assert {"doc", "title", "page", "chunk_id", "score", "text"} <= set(
        CiteData.model_json_schema()["$defs"]["RetrievalHit"]["properties"]
    )


def test_consumer_shaped_cite_response_validates() -> None:
    response = CiteData(
        status="available",
        provenance=[
            ArtifactRef(
                artifact_id="corpus_chunks",
                artifact_version="fixture-v1",
                source_kind="retrieval",
                source_ref="data/duck/grid.duckdb",
            )
        ],
        hits=[
            {
                "doc": "10cfr100",
                "title": "10 CFR Part 100",
                "page": 2,
                "chunk_id": "10cfr100-p2-c1",
                "score": 0.9,
                "text": "A bounded retrieval excerpt.",
            }
        ],
    )
    assert response.hits[0].doc == "10cfr100"


def test_tool_output_has_no_unused_citation_channel() -> None:
    result = unavailable_output("artifact_unavailable", "fixture is absent")

    assert "citations" not in ToolOutput.model_fields
    assert "citations" not in result.model_dump()


def test_cascade_output_accepts_persisted_tripped_element_shape() -> None:
    response = CascadeData(
        status="available",
        provenance=[
            ArtifactRef(
                artifact_id="cascade_runs",
                artifact_version="fixture-v1",
                source_kind="simulated",
                source_ref="data/duck/grid.duckdb",
            )
        ],
        run_id="cascade-1",
        scenario_id="uri_2021",
        hour=1,
        tripped_element_ids=[
            {"element_id": "L1", "kind": "line", "stage": 1, "cause": "weather"}
        ],
        lost_load_mw=0.0,
        counties_dark=[],
        critical_loads_lost=[],
        steps=1,
    )

    assert response.tripped_element_ids[0].cause == "weather"


def test_cascade_output_rejects_unknown_tripped_element_kind() -> None:
    with pytest.raises(ValidationError):
        CascadeData(
            status="available",
            provenance=[
                ArtifactRef(
                    artifact_id="cascade_runs",
                    artifact_version="fixture-v1",
                    source_kind="simulated",
                    source_ref="data/duck/grid.duckdb",
                )
            ],
            run_id="cascade-1",
            scenario_id="uri_2021",
            hour=1,
            tripped_element_ids=[
                {"element_id": "L1", "kind": "switch", "stage": 1, "cause": "weather"}
            ],
            lost_load_mw=0.0,
            counties_dark=[],
            critical_loads_lost=[],
            steps=1,
        )


def test_causal_interval_round_trips_as_a_json_list() -> None:
    response = CausalData(
        status="available",
        provenance=[
            ArtifactRef(
                artifact_id="causal_results",
                artifact_version="fixture-v1",
                source_kind="fixture",
                source_ref="data/duck/grid.duckdb",
            )
        ],
        answer_numbers={},
        method="fixture",
        assumptions=[],
        interval=[0.1, 0.9],
        evidence_rows=[],
    )

    assert response.interval == [0.1, 0.9]
    with pytest.raises(ValidationError):
        response.model_validate({**response.model_dump(), "interval": [0.1]})


def test_all_tool_outputs_keep_documented_payloads_top_level() -> None:
    expected = {
        "predict_outage": {"county_fips", "county_name", "scenario_id", "horizon_h", "peak_p_out", "peak_ts", "customers_at_risk", "driver", "series"},
        "run_cascade": {"run_id", "scenario_id", "hour", "tripped_element_ids", "lost_load_mw", "counties_dark", "critical_loads_lost", "steps"},
        "score_site": {"site_id", "name", "kind", "county_fips", "unit_mw", "safety_score", "safety_flags", "grid_value_score", "lol_reduction_mwh", "congestion_relief_pct", "blackstart_reach_mw", "critical_loads_protected", "regulatory_path"},
        "top_lines": {"region", "tech", "lines"},
        "sql": {"columns", "rows", "row_count", "truncated"},
        "cite": {"hits"},
        "compare_interventions": {"scenario_id", "baseline_run_id", "interventions", "assumptions"},
        "top_critical_elements": {"region", "n", "scenario_ids", "elements", "partial"},
        "causal_query": {"answer_numbers", "method", "assumptions", "interval", "evidence_rows"},
    }
    for definition in TOOL_REGISTRY:
        fields = definition.output_model[0].model_fields
        assert expected[definition.name] <= set(fields)
        assert "data" not in fields

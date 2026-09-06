from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from copilot.tools.schemas import (
    TOOL_REGISTRY,
    TOOL_SCHEMAS,
    TOP_LINES_MAX_LIMIT,
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
from scripts.ci.export_tool_contracts import build_schema_document, render_ts


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


def test_top_lines_schema_is_exactly_the_frozen_contract_signature() -> None:
    schema = next(item for item in TOOL_SCHEMAS if item["name"] == "top_lines")

    # 00 §2.4 / 05 freeze ``top_lines(region, tech, n=10)``; no pagination or
    # sort parameter is model-facing.
    assert set(schema["input_schema"]["properties"]) == {"region", "tech", "n"}

    request = validate_tool_input("top_lines", {"region": "ERCOT", "tech": "dlr"})
    assert request.n == 10
    assert not hasattr(request, "offset")

    request = validate_tool_input(
        "top_lines", {"region": "ERCOT", "tech": "dlr", "n": TOP_LINES_MAX_LIMIT}
    )
    assert request.n == TOP_LINES_MAX_LIMIT == 50


def test_top_lines_rejects_out_of_bound_pages_and_unknown_filters() -> None:
    for payload in (
        {"region": "ERCOT", "tech": "dlr", "n": TOP_LINES_MAX_LIMIT + 1},
        {"region": "ERCOT", "tech": "dlr", "n": 0},
        {"region": "ERCOT", "tech": "dlr", "offset": 0},
        {"region": "ERCOT", "tech": "dlr", "offset": 10},
        {"region": "ERCOT", "tech": "dlr", "sort": "line_id DESC"},
        {"region": "ERCOT", "tech": "dlr", "owner": "any"},
        {"region": "", "tech": "dlr"},
        {"region": "ERCOT", "tech": "hvdc"},
    ):
        with pytest.raises(ValidationError):
            validate_tool_input("top_lines", payload)


def test_sql_input_requires_exactly_one_of_query_or_template_id() -> None:
    # 00-overview A8 amendment: ``sql(query | template_id)``; the boundary,
    # not the executor, is where ``{}`` and both-set payloads die.
    for payload in (
        {},
        {"query": "SELECT 1", "template_id": "summary_rows"},
        {"query": None, "template_id": None},
    ):
        with pytest.raises(ValidationError, match="exactly one"):
            validate_tool_input("sql", payload)

    legacy = validate_tool_input("sql", {"query": "SELECT 1"})
    template = validate_tool_input("sql", {"template_id": "summary_rows"})
    assert legacy.model_dump() == {"query": "SELECT 1", "template_id": None}
    assert template.model_dump() == {"query": None, "template_id": "summary_rows"}


def test_sql_template_id_keeps_the_frozen_identifier_pattern() -> None:
    for template_id in ("Summary_rows", "_x", "a-b", "a" * 65, ""):
        with pytest.raises(ValidationError):
            validate_tool_input("sql", {"template_id": template_id})

    schema = next(item for item in TOOL_SCHEMAS if item["name"] == "sql")
    assert set(schema["input_schema"]["properties"]) == {"query", "template_id"}


def test_sql_tool_schema_encodes_the_exactly_one_input_contract() -> None:
    schema = next(item for item in TOOL_SCHEMAS if item["name"] == "sql")[
        "input_schema"
    ]
    validator = Draft202012Validator(schema)

    # Strict tool schemas require every declared key, so the unused XOR member
    # is explicit null rather than omitted.
    assert validator.is_valid({"query": "SELECT 1", "template_id": None})
    assert validator.is_valid({"query": None, "template_id": "summary_rows"})
    for payload in (
        {},
        {"query": "SELECT 1"},
        {"template_id": "summary_rows"},
        {"query": None, "template_id": None},
        {"query": "SELECT 1", "template_id": "summary_rows"},
    ):
        assert not validator.is_valid(payload)


def test_exported_sql_contract_keeps_the_xor_in_json_schema_and_typescript() -> None:
    document = build_schema_document()
    schema = {"$ref": "#/$defs/SqlInput", "$defs": document["$defs"]}
    validator = Draft202012Validator(schema)

    assert validator.is_valid({"query": "SELECT 1", "template_id": None})
    assert validator.is_valid({"query": None, "template_id": "summary_rows"})
    assert not validator.is_valid({"query": None, "template_id": None})
    assert not validator.is_valid({"query": "SELECT 1", "template_id": "summary_rows"})
    assert (
        "export type SqlInput = { query?: string | null; template_id?: string | null; } "
        "& ({ query: string; template_id: null; } | { query: null; template_id: string; });"
        in render_ts(document)
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


def test_real_tool_contract_accepts_its_unavailable_output() -> None:
    result = unavailable_output(
        "artifact_unavailable", "fixture prediction artifact is absent"
    )
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
    assert {
        "county_fips",
        "county_name",
        "scenario_id",
        "horizon_h",
        "peak_p_out",
        "series",
    } <= set(fields)
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
    assert {
        "content_kind",
        "date",
        "doc",
        "locator",
        "provenance",
        "source",
        "title",
        "page",
        "chunk_id",
        "score",
        "text",
        "version",
    } <= set(CiteData.model_json_schema()["$defs"]["RetrievalHit"]["properties"])


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
                "content_kind": "source",
                "date": "2026-09-05",
                "doc": "10cfr100",
                "locator": "page 2; chunk 1",
                "provenance": {"source_name": "NRC"},
                "source": "https://example.test/10cfr100.pdf",
                "title": "10 CFR Part 100",
                "page": 2,
                "chunk_id": "10cfr100-p2-c1",
                "score": 0.9,
                "text": "A bounded retrieval excerpt.",
                "version": "2026-09-05",
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
        question={
            "treatment": {
                "name": "hardening",
                "definition": "test treatment",
                "unit_or_category": "category",
                "source_id": "source-1",
            },
            "outcome": {
                "name": "duration",
                "definition": "test outcome",
                "unit_or_category": "hours",
                "source_id": "source-1",
            },
            "target_population": {
                "description": "test population",
                "geography": "Texas",
                "time_window": "2021",
            },
        },
        sources=[
            {
                "source_id": "source-1",
                "name": "test source",
                "version": "v1",
                "locator": "test-row",
                "coverage": "2021",
            }
        ],
        sample={
            "unit": "county",
            "n_total": 2,
            "n_treated": 1,
            "n_control": 1,
            "period": "2021",
        },
        diagnostics=[{"name": "balance", "status": "pass", "evidence": "recorded"}],
        citations=[{"source_id": "source-1", "locator": "test-row"}],
    )

    assert response.interval == [0.1, 0.9]
    with pytest.raises(ValidationError):
        response.model_validate({**response.model_dump(), "interval": [0.1]})


def test_all_tool_outputs_keep_documented_payloads_top_level() -> None:
    expected = {
        "predict_outage": {
            "county_fips",
            "county_name",
            "scenario_id",
            "horizon_h",
            "peak_p_out",
            "peak_ts",
            "customers_at_risk",
            "driver",
            "series",
        },
        "run_cascade": {
            "run_id",
            "scenario_id",
            "hour",
            "tripped_element_ids",
            "lost_load_mw",
            "counties_dark",
            "critical_loads_lost",
            "steps",
        },
        "score_site": {
            "site_id",
            "name",
            "kind",
            "county_fips",
            "unit_mw",
            "safety_score",
            "safety_flags",
            "grid_value_score",
            "lol_reduction_mwh",
            "congestion_relief_pct",
            "blackstart_reach_mw",
            "critical_loads_protected",
            "regulatory_path",
        },
        "top_lines": {"region", "tech", "lines"},
        "sql": {"columns", "rows", "row_count", "truncated"},
        "cite": {"hits"},
        "compare_interventions": {
            "scenario_id",
            "baseline_run_id",
            "interventions",
            "assumptions",
        },
        "top_critical_elements": {"region", "n", "scenario_ids", "elements", "partial"},
        "causal_query": {
            "answer_numbers",
            "method",
            "assumptions",
            "interval",
            "evidence_rows",
        },
    }
    for definition in TOOL_REGISTRY:
        fields = definition.output_model[0].model_fields
        assert expected[definition.name] <= set(fields)
        assert "data" not in fields

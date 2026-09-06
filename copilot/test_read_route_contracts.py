"""Contract inventory for every currently registered Flux API route.

Each referenced test drives the route through ``TestClient`` against a local
DuckDB fixture.  Keeping this mapping alongside the OpenAPI inventory makes a
missing success, invalid-input, or unavailable state visible in review.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from copilot.app import create_app


@dataclass(frozen=True)
class RouteContract:
    success: str
    invalid: str | None
    unavailable: str


READ_ROUTE_CONTRACTS = {
    ("GET", "/health"): RouteContract(
        "copilot/test_app.py::test_health_opens_a_fixture_database_without_claiming_model_availability",
        None,
        "copilot/test_app.py::test_health_returns_the_shared_unavailable_envelope_for_a_missing_fixture",
    ),
    ("GET", "/layers/{layer_name}"): RouteContract(
        "copilot/test_layers.py::test_buses_layer_is_bare_geojson_through_the_real_app",
        "copilot/test_layers.py::test_malformed_layer_name_is_invalid_input_before_any_lookup",
        "copilot/test_layers.py::test_documented_but_unbuilt_layers_are_unavailable_not_built",
    ),
    ("POST", "/site-score"): RouteContract(
        "copilot/test_interventions.py::test_site_and_comparison_reads_are_server_side",
        "copilot/test_interventions.py::test_invalid_capacity_and_identifiers_are_validation_errors",
        "copilot/test_interventions.py::test_missing_artifact_is_unavailable",
    ),
    ("POST", "/compare"): RouteContract(
        "copilot/test_interventions.py::test_site_and_comparison_reads_are_server_side",
        "copilot/test_interventions.py::test_invalid_capacity_and_identifiers_are_validation_errors",
        "copilot/test_interventions.py::test_missing_artifact_is_unavailable",
    ),
    ("GET", "/scenarios"): RouteContract(
        "copilot/test_scenarios.py::test_catalog_is_the_bare_array_pinned_by_the_overview",
        None,
        "copilot/test_scenarios.py::test_empty_scenarios_table_is_unavailable_not_an_empty_success",
    ),
    ("GET", "/scenarios/{scenario_id}"): RouteContract(
        "copilot/test_scenarios.py::test_detail_returns_the_unwrapped_row",
        None,
        "copilot/test_scenarios.py::test_missing_database_file_is_the_shared_unavailable_envelope",
    ),
    ("GET", "/predictions"): RouteContract(
        "copilot/test_predictions.py::test_qualified_persisted_prediction_is_returned_as_bare_array",
        "copilot/test_predictions.py::test_malformed_parameters_are_the_shared_validation_envelope",
        "copilot/test_predictions.py::test_prediction_missing_database_is_unavailable",
    ),
    ("GET", "/cascade"): RouteContract(
        "copilot/test_predictions.py::test_persisted_cascade_is_returned_unwrapped",
        "copilot/test_predictions.py::test_malformed_parameters_are_the_shared_validation_envelope",
        "copilot/test_predictions.py::test_missing_cascade_database_is_unavailable",
    ),
    ("POST", "/ask"): RouteContract(
        "copilot/test_ask.py::test_ask_streams_real_sql_evidence_to_an_injected_provider",
        "copilot/test_ask.py::test_ask_rejects_invalid_attempt_history_and_resume_id",
        "copilot/test_ask.py::test_ask_unconfigured_backend_and_resume_are_explicit",
    ),
}


def _test_exists(node_id: str) -> bool:
    path_text, test_name = node_id.split("::", 1)
    path = Path(__file__).parents[1] / path_text
    return path.is_file() and f"def {test_name}" in path.read_text(encoding="utf-8")


def test_every_registered_route_has_fixture_contract_coverage() -> None:
    registered = {
        (method.upper(), path)
        for path, operations in create_app().openapi()["paths"].items()
        for method in operations
    }

    assert set(READ_ROUTE_CONTRACTS) == registered
    for contract in READ_ROUTE_CONTRACTS.values():
        assert _test_exists(contract.success)
        assert _test_exists(contract.unavailable)
        if contract.invalid is not None:
            assert _test_exists(contract.invalid)

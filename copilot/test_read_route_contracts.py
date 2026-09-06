"""Behavioural contract inventory for every currently registered Flux API route.

Two properties are proven here, both against the running app:

* the inventory is *complete* — the set of contract keys is derived from the live
  ``create_app().openapi()`` document, so a newly registered route with no
  contract is a failure; and
* every contract cell is *real* — the referenced test is executed in a
  subprocess under :mod:`copilot._route_contract_probe`, which records the route
  template and status code of every request the test issued.  A cell only holds
  if the referenced test ran, passed, drove *that* route, and observed *that*
  status.  Gutting the referenced test, or filing it under a different route,
  fails here; a name pin could not tell the difference.

Where a state genuinely does not exist for a route the cell carries an explicit
sentinel (:data:`NO_INPUT`, :class:`Unreachable`) rather than ``None``, and a
reachable-but-uncovered state carries :class:`Gap` with a tracking key, so the
holes in the inventory are greppable instead of absent.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from copilot._artifact_fixtures import registered_routes
from copilot.app import create_app

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
#: Recorded call as the probe plugin writes it: (method, route template, status).
Call = tuple[str, str, int]


@dataclass(frozen=True)
class Cell:
    """A test that must drive this route into this status when it runs."""

    node_id: str
    status: int


@dataclass(frozen=True)
class NoInput:
    """The route accepts no client input, so it has no invalid-input state.

    Verified against the OpenAPI document: no parameters and no request body.
    """


@dataclass(frozen=True)
class Unreachable:
    """The state cannot occur for this route; the reason says why."""

    reason: str


@dataclass(frozen=True)
class Gap:
    """The state is reachable but uncovered.  Must cite a tracking key."""

    reason: str


NO_INPUT: Final = NoInput()

Slot = Cell | NoInput | Unreachable | Gap


@dataclass(frozen=True)
class RouteContract:
    success: Cell
    invalid: Slot
    unavailable: Cell
    not_found: Slot

    def cells(self) -> tuple[tuple[str, Slot], ...]:
        return (
            ("success", self.success),
            ("invalid", self.invalid),
            ("unavailable", self.unavailable),
            ("not_found", self.not_found),
        )


_NO_NOT_FOUND: Final = Unreachable("the route raises no NotFoundError")

READ_ROUTE_CONTRACTS: Final[dict[tuple[str, str], RouteContract]] = {
    ("GET", "/health"): RouteContract(
        success=Cell(
            "copilot/test_app.py::test_health_opens_a_fixture_database_without_claiming_model_availability",
            200,
        ),
        invalid=NO_INPUT,
        unavailable=Cell(
            "copilot/test_app.py::test_health_returns_the_shared_unavailable_envelope_for_a_missing_fixture",
            503,
        ),
        not_found=_NO_NOT_FOUND,
    ),
    ("GET", "/layers/{layer_name}"): RouteContract(
        success=Cell(
            "copilot/test_layers.py::test_buses_layer_is_bare_geojson_through_the_real_app",
            200,
        ),
        invalid=Cell(
            "copilot/test_layers.py::test_malformed_layer_name_is_invalid_input_before_any_lookup",
            422,
        ),
        unavailable=Cell(
            "copilot/test_layers.py::test_documented_but_unbuilt_layers_are_unavailable_not_built",
            503,
        ),
        not_found=Cell(
            "copilot/test_layers.py::test_well_formed_undocumented_layer_is_not_found_not_an_empty_success",
            404,
        ),
    ),
    ("GET", "/api/v1/grid/layers/{layer}"): RouteContract(
        success=Cell(
            "copilot/test_physical_layers.py::test_tx_lines_are_real_http_pages_with_release_bound_cursor",
            200,
        ),
        invalid=Cell(
            "copilot/test_physical_layers.py::test_invalid_viewport_and_unknown_physical_layer_use_shared_errors",
            422,
        ),
        unavailable=Cell(
            "copilot/test_physical_layers.py::test_missing_release_is_explicitly_unavailable",
            503,
        ),
        not_found=Cell(
            "copilot/test_physical_layers.py::test_invalid_viewport_and_unknown_physical_layer_use_shared_errors",
            404,
        ),
    ),
    ("POST", "/site-score"): RouteContract(
        success=Cell(
            "copilot/test_interventions.py::test_site_read_is_server_side_and_unqualified_comparison_is_unavailable",
            200,
        ),
        invalid=Cell(
            "copilot/test_interventions.py::test_site_score_capacity_bound_is_a_validation_error",
            422,
        ),
        unavailable=Cell(
            "copilot/test_interventions.py::test_site_score_missing_database_is_unavailable",
            503,
        ),
        not_found=Cell(
            "copilot/test_interventions.py::test_unknown_site_is_not_found_rather_than_retryable",
            404,
        ),
    ),
    ("POST", "/compare"): RouteContract(
        success=Cell(
            "copilot/test_interventions.py::test_comparison_reads_a_qualified_persisted_score_without_deriving_a_delta",
            200,
        ),
        invalid=Cell(
            "copilot/test_interventions.py::test_missing_and_invalid_comparison_inputs_are_not_empty_successes",
            422,
        ),
        unavailable=Cell(
            "copilot/test_interventions.py::test_site_read_is_server_side_and_unqualified_comparison_is_unavailable",
            503,
        ),
        not_found=_NO_NOT_FOUND,
    ),
    ("GET", "/lines/top"): RouteContract(
        success=Cell(
            "copilot/test_lines.py::test_top_lines_reads_a_deterministic_persisted_page",
            200,
        ),
        invalid=Cell(
            "copilot/test_lines.py::test_top_lines_rejects_invalid_page_bounds", 422
        ),
        unavailable=Cell(
            "copilot/test_lines.py::test_top_lines_reports_unavailable_artifact_states",
            503,
        ),
        not_found=_NO_NOT_FOUND,
    ),
    ("GET", "/elements/critical"): RouteContract(
        success=Cell(
            "copilot/test_interventions.py::test_critical_elements_use_persisted_values_with_stable_paging",
            200,
        ),
        invalid=Cell(
            "copilot/test_interventions.py::test_critical_elements_rejects_an_out_of_bounds_page_with_shared_envelope",
            422,
        ),
        unavailable=Cell(
            "copilot/test_interventions.py::test_canonical_unavailable_critical_manifest_needs_no_domain_row",
            503,
        ),
        not_found=_NO_NOT_FOUND,
    ),
    ("GET", "/scenarios"): RouteContract(
        success=Cell(
            "copilot/test_scenarios.py::test_catalog_is_the_bare_array_pinned_by_the_overview",
            200,
        ),
        invalid=NO_INPUT,
        unavailable=Cell(
            "copilot/test_scenarios.py::test_empty_scenarios_table_is_unavailable_not_an_empty_success",
            503,
        ),
        not_found=_NO_NOT_FOUND,
    ),
    ("GET", "/scenarios/{scenario_id}"): RouteContract(
        success=Cell(
            "copilot/test_scenarios.py::test_detail_returns_the_unwrapped_row", 200
        ),
        invalid=Unreachable(
            "scenario_id is an unconstrained path str: every value routes, so the "
            "absent-row state is the 404 below rather than a 422."
        ),
        unavailable=Cell(
            "copilot/test_scenarios.py::test_detail_missing_database_file_is_the_shared_unavailable_envelope",
            503,
        ),
        not_found=Cell(
            "copilot/test_scenarios.py::test_detail_reports_not_found_for_an_absent_scenario_row",
            404,
        ),
    ),
    ("GET", "/predictions"): RouteContract(
        success=Cell(
            "copilot/test_predictions.py::test_qualified_persisted_prediction_is_returned_as_bare_array",
            200,
        ),
        invalid=Cell(
            "copilot/test_predictions.py::test_malformed_parameters_are_the_shared_validation_envelope",
            422,
        ),
        unavailable=Cell(
            "copilot/test_predictions.py::test_prediction_missing_database_is_unavailable",
            503,
        ),
        not_found=_NO_NOT_FOUND,
    ),
    ("GET", "/cascade"): RouteContract(
        success=Cell(
            "copilot/test_predictions.py::test_persisted_cascade_is_returned_unwrapped",
            200,
        ),
        invalid=Cell(
            "copilot/test_predictions.py::test_malformed_parameters_are_the_shared_validation_envelope",
            422,
        ),
        unavailable=Cell(
            "copilot/test_predictions.py::test_missing_cascade_database_is_unavailable",
            503,
        ),
        not_found=Cell(
            "copilot/test_predictions.py::test_cascade_run_id_selects_that_run_or_is_not_found",
            404,
        ),
    ),
    ("POST", "/interactive/scenario/edit"): RouteContract(
        success=Cell(
            "copilot/test_interactive_routes.py::test_all_ticket_436_routes_are_mounted_under_the_interactive_prefix",
            200,
        ),
        invalid=Cell(
            "copilot/test_interactive_routes.py::test_unknown_and_malformed_edits_fail_explicitly",
            422,
        ),
        unavailable=Cell(
            "copilot/test_interactive_routes.py::test_every_route_reports_a_missing_core_as_unavailable",
            503,
        ),
        not_found=_NO_NOT_FOUND,
    ),
    ("POST", "/interactive/cascade"): RouteContract(
        success=Cell(
            "copilot/test_interactive_routes.py::test_all_ticket_436_routes_are_mounted_under_the_interactive_prefix",
            200,
        ),
        invalid=Cell(
            "copilot/test_interactive_routes.py::test_every_route_refuses_a_context_it_cannot_apply",
            422,
        ),
        unavailable=Cell(
            "copilot/test_interactive_routes.py::test_every_route_reports_a_missing_core_as_unavailable",
            503,
        ),
        not_found=Cell(
            "copilot/test_interactive_routes.py::test_cascade_with_an_unknown_edit_hash_is_not_found",
            404,
        ),
    ),
    ("GET", "/interactive/balance"): RouteContract(
        success=Cell(
            "copilot/test_interactive_routes.py::test_all_ticket_436_routes_are_mounted_under_the_interactive_prefix",
            200,
        ),
        invalid=Cell(
            "copilot/test_interactive_routes.py::test_every_route_refuses_a_context_it_cannot_apply",
            422,
        ),
        unavailable=Cell(
            "copilot/test_interactive_routes.py::test_every_route_reports_a_missing_core_as_unavailable",
            503,
        ),
        not_found=Cell(
            "copilot/test_interactive_routes.py::test_unknown_and_malformed_edits_fail_explicitly",
            404,
        ),
    ),
    ("GET", "/interactive/redundancy"): RouteContract(
        success=Cell(
            "copilot/test_interactive_routes.py::test_all_ticket_436_routes_are_mounted_under_the_interactive_prefix",
            200,
        ),
        invalid=Cell(
            "copilot/test_interactive_routes.py::test_every_route_refuses_a_context_it_cannot_apply",
            422,
        ),
        unavailable=Cell(
            "copilot/test_interactive_routes.py::test_every_route_reports_a_missing_core_as_unavailable",
            503,
        ),
        not_found=_NO_NOT_FOUND,
    ),
    ("POST", "/ask"): RouteContract(
        success=Cell(
            "copilot/test_ask.py::test_ask_streams_real_sql_evidence_to_an_injected_provider",
            200,
        ),
        invalid=Cell(
            "copilot/test_ask.py::test_ask_rejects_invalid_attempt_history_and_resume_id",
            422,
        ),
        unavailable=Cell(
            "copilot/test_ask.py::test_ask_unconfigured_backend_and_resume_are_explicit",
            503,
        ),
        not_found=_NO_NOT_FOUND,
    ),
}


def _referenced_node_ids() -> tuple[str, ...]:
    seen = {
        slot.node_id
        for contract in READ_ROUTE_CONTRACTS.values()
        for _, slot in contract.cells()
        if isinstance(slot, Cell)
    }
    return tuple(sorted(seen))


@lru_cache(maxsize=1)
def _observed_calls() -> dict[str, list[Call]]:
    """Run every referenced test once and return the routes each one drove.

    The referenced tests must *pass*: a non-zero exit status (including pytest's
    "no tests collected" for a renamed or deleted test) fails the contract.
    """
    node_ids = _referenced_node_ids()
    with tempfile.TemporaryDirectory() as workspace:
        destination = Path(workspace) / "route-calls.json"
        environment = dict(os.environ, FLUX_ROUTE_PROBE_OUT=str(destination))
        environment.pop("DUCKDB_PATH", None)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-p",
                "copilot._route_contract_probe",
                "-q",
                *node_ids,
            ],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, (
            "referenced contract tests did not all run and pass:\n"
            f"{completed.stdout[-4000:]}\n{completed.stderr[-2000:]}"
        )
        recorded = json.loads(destination.read_text(encoding="utf-8"))
    calls: dict[str, list[Call]] = {}
    for node, entries in recorded.items():
        calls[node] = [(method, path, status) for method, path, status in entries]
    return calls


def _calls_for(node_id: str) -> list[Call]:
    """Calls recorded for a node id, folding in its parametrised variants."""
    observed = _observed_calls()
    collected = list(observed.get(node_id, ()))
    for recorded_id, entries in observed.items():
        if recorded_id.startswith(f"{node_id}["):
            collected.extend(entries)
    return collected


def test_every_registered_route_has_a_contract() -> None:
    """The inventory is derived from the live app, not from a hand-kept list."""
    assert set(READ_ROUTE_CONTRACTS) == registered_routes()


def test_no_input_cells_match_the_published_operation() -> None:
    """``NO_INPUT`` is a checkable claim, not a way of writing ``None``."""
    paths = create_app().openapi()["paths"]
    for (method, path), contract in READ_ROUTE_CONTRACTS.items():
        if not isinstance(contract.invalid, NoInput):
            continue
        operation = paths[path][method.lower()]
        assert not operation.get("parameters"), (method, path)
        assert "requestBody" not in operation, (method, path)


def test_every_contract_gap_cites_a_tracking_key() -> None:
    """A hole in the inventory must be explicit and greppable."""
    gaps = [
        (route, state, slot)
        for route, contract in READ_ROUTE_CONTRACTS.items()
        for state, slot in contract.cells()
        if isinstance(slot, Gap)
    ]
    for route, state, slot in gaps:
        assert "2WKG-" in slot.reason, (route, state)
    assert not gaps


def test_every_unreachable_cell_states_a_reason() -> None:
    for route, contract in READ_ROUTE_CONTRACTS.items():
        for state, slot in contract.cells():
            if isinstance(slot, Unreachable):
                assert slot.reason.strip(), (route, state)


def test_every_contract_cell_is_exercised_by_its_referenced_test() -> None:
    """Each cell's test must run, pass, drive that route, and see that status."""
    for (method, path), contract in READ_ROUTE_CONTRACTS.items():
        for state, slot in contract.cells():
            if not isinstance(slot, Cell):
                continue
            calls = _calls_for(slot.node_id)
            assert calls, f"{slot.node_id} issued no HTTP request at all ({state})"
            assert (method, path, slot.status) in calls, (
                f"{method} {path} [{state}]: {slot.node_id} never drove that route "
                f"to {slot.status}; it recorded {sorted(set(calls))}"
            )

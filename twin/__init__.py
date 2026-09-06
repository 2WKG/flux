"""Grid-twin physics modules for synthetic topology only."""

from twin.build import cached_base_network, model_geometry
from twin.cascade import (
    add_unit,
    balance_report,
    control_room_payload,
    feasibility_report,
    immutable_scenario_net,
    placement_counterfactual,
    rank_candidate_placements,
    redundancy_report,
    run_cascade,
    scenario_identity,
    texas_stress_preset,
)
from twin.contracts import (
    SYNTHETIC_TOPOLOGY_LABEL,
    SimulationCancelledError,
    SimulationError,
    SimulationInputError,
    SimulationSolveError,
    SimulationUnavailableError,
)

__all__ = [
    "SYNTHETIC_TOPOLOGY_LABEL",
    "SimulationCancelledError",
    "SimulationError",
    "SimulationInputError",
    "SimulationSolveError",
    "SimulationUnavailableError",
    "add_unit",
    "balance_report",
    "cached_base_network",
    "control_room_payload",
    "feasibility_report",
    "immutable_scenario_net",
    "model_geometry",
    "placement_counterfactual",
    "rank_candidate_placements",
    "redundancy_report",
    "run_cascade",
    "scenario_identity",
    "texas_stress_preset",
]

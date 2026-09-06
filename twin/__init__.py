"""Grid-twin physics modules for synthetic topology only."""

from twin.cascade import (
    add_unit,
    control_room_payload,
    rank_candidate_placements,
    run_cascade,
    texas_stress_preset,
)
from twin.contracts import (
    SYNTHETIC_TOPOLOGY_LABEL,
    SimulationError,
    SimulationInputError,
    SimulationSolveError,
    SimulationUnavailableError,
)

__all__ = [
    "SYNTHETIC_TOPOLOGY_LABEL",
    "SimulationError",
    "SimulationInputError",
    "SimulationSolveError",
    "SimulationUnavailableError",
    "add_unit",
    "control_room_payload",
    "rank_candidate_placements",
    "run_cascade",
    "texas_stress_preset",
]

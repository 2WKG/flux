"""Grid-twin physics modules for synthetic topology only."""

from twin.cascade import add_unit, rank_candidate_placements, run_cascade
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
    "rank_candidate_placements",
    "run_cascade",
]

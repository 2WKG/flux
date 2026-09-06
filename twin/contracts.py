"""Typed, JSON-safe contracts for the synthetic ACTIVS cascade engine.

The objects in this module deliberately describe a *synthetic* topology.  They
must never be joined to the public physical-inventory graph: that graph has no
accepted terminal-to-terminal connectivity evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pipelines.labels import SYNTHETIC_TOPOLOGY_LABEL

EditKind = Literal["outage", "remove", "add_gen", "add_load", "add_line"]


class SimulationError(RuntimeError):
    """Base class for an explicit simulation failure."""


class SimulationInputError(SimulationError):
    """The requested edit cannot be applied to this synthetic model."""


class SimulationUnavailableError(SimulationError):
    """A required case, coordinate artifact, or persistence artifact is absent."""


class SimulationSolveError(SimulationError):
    """pandapower could not solve the edited synthetic model."""


class SimulationCancelledError(SimulationError):
    """A caller cancelled a synchronous DC run before it was persisted."""


@dataclass(frozen=True)
class GridEdit:
    """One immutable topology or injection edit used by the policy helpers."""

    kind: EditKind
    element_id: str
    bus_id: int | None = None
    from_bus_id: int | None = None
    to_bus_id: int | None = None
    p_mw: float | None = None
    pmax_mw: float | None = None
    r_pu: float | None = None
    x_pu: float | None = None
    rate_a_mw: float | None = None
    base_kv: float | None = None
    length_km: float | None = None

    def json(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class CascadeEvent:
    """An ordered outage event that can be serialized into ``cascade_runs``."""

    element_id: str
    kind: Literal["line", "impedance", "generator", "static_generator", "load"]
    stage: int
    cause: Literal["forced", "overload", "island"]
    loading_percent: float | None = None

    def json(self) -> dict[str, Any]:
        value = asdict(self)
        if self.loading_percent is None:
            value.pop("loading_percent")
        return value


@dataclass(frozen=True)
class CascadeResult:
    """One synthetic cascade hour in the exact common ``cascade_runs`` shape."""

    run_id: str
    scenario_id: str
    hour: int
    tripped_element_ids: tuple[CascadeEvent, ...]
    lost_load_mw: float
    served_load_mw: float
    counties_dark: tuple[str, ...]
    critical_loads_lost: tuple[Any, ...]
    topology: str = SYNTHETIC_TOPOLOGY_LABEL
    solver: str = "pandapower.rundcpp"
    synthetic: bool = True
    loading_by_element: dict[str, float] = field(default_factory=dict)
    county_impacts: tuple[dict[str, Any], ...] = ()
    scenario_identity: dict[str, Any] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        """Return the copilot-friendly payload without numpy/pandas values."""
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "hour": self.hour,
            "tripped_element_ids": [event.json() for event in self.tripped_element_ids],
            "lost_load_mw": float(self.lost_load_mw),
            "served_load_mw": float(self.served_load_mw),
            "counties_dark": list(self.counties_dark),
            "critical_loads_lost": list(self.critical_loads_lost),
            "topology": self.topology,
            "synthetic": self.synthetic,
            "solver": self.solver,
            "loading_by_element": {
                key: float(value) for key, value in self.loading_by_element.items()
            },
            "county_impacts": [dict(value) for value in self.county_impacts],
            "scenario_identity": dict(self.scenario_identity),
        }


@dataclass(frozen=True)
class PlacementResult:
    """A synthetic candidate-bus placement score; this is not physical siting."""

    bus_id: int
    redundancy: int
    reachable_load_mw: float
    topology: str = SYNTHETIC_TOPOLOGY_LABEL

    def json(self) -> dict[str, Any]:
        return asdict(self)

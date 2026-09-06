"""Public, JSON-safe contracts for the synthetic grid simulation foundation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SYNTHETIC_TOPOLOGY_LABEL = "synthetic (ACTIVSg2000)"


class SimulationError(RuntimeError):
    """Base class for a simulation error that callers can report honestly."""


class SimulationUnavailableError(SimulationError):
    """The requested input artifact or its required schema is unavailable."""


class SimulationInputError(SimulationError):
    """A requested edit cannot be applied to the supplied synthetic model."""


class SimulationSolveError(SimulationError):
    """The edited model could not be solved with pandapower DC flow."""


EditKind = Literal["outage", "remove", "add_gen", "add_load", "add_line"]


@dataclass(frozen=True)
class GridEdit:
    """One immutable topology or injection edit.

    The ordered sequence supplied to :func:`twin.edits.apply_edits` is part of
    the scenario identity.  Fields irrelevant to an operation are ``None``.
    """

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
    element_id: str
    kind: Literal["line", "impedance", "generator", "load"]
    stage: int
    cause: Literal["forced", "overload", "island"]
    loading_percent: float | None = None

    def json(self) -> dict[str, Any]:
        value = asdict(self)
        if value["loading_percent"] is None:
            value.pop("loading_percent")
        return value


@dataclass(frozen=True)
class CascadeResult:
    edit_hash: str
    tripped_element_ids: tuple[CascadeEvent, ...]
    lost_load_mw: float
    served_load_mw: float
    county_impacts: tuple[dict[str, Any], ...] = ()
    critical_loads_lost: tuple[dict[str, Any], ...] = ()
    loading_by_element: dict[str, float] = field(default_factory=dict)
    topology: str = SYNTHETIC_TOPOLOGY_LABEL
    solver: str = "pandapower.rundcpp"

    def json(self) -> dict[str, Any]:
        return {
            "edit_hash": self.edit_hash,
            "tripped_element_ids": [event.json() for event in self.tripped_element_ids],
            "lost_load_mw": float(self.lost_load_mw),
            "served_load_mw": float(self.served_load_mw),
            "county_impacts": [dict(item) for item in self.county_impacts],
            "critical_loads_lost": [dict(item) for item in self.critical_loads_lost],
            "loading_by_element": {key: float(value) for key, value in self.loading_by_element.items()},
            "topology": self.topology,
            "solver": self.solver,
        }

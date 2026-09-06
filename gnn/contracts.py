"""JSON-safe contracts for solver-labelled surrogate training samples.

Every object here describes the *synthetic* ACTIVSg2000 model.  Values that the
model does not supply (a branch rating, an hourly demand observation, a label
behind a failed solve) are carried as ``None`` next to an explicit reason, never
as a substituted number.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SAMPLE_SCHEMA_VERSION = "gnn-training-sample/v1"
SYNTHETIC_TOPOLOGY_LABEL = "synthetic (ACTIVSg2000)"

SampleKind = Literal["baseline", "n1", "n2", "placement_gen", "placement_load"]
SampleStatus = Literal["labelled", "failed"]


class SamplingError(RuntimeError):
    """The requested sampling plan cannot be built from this model or database."""


class SamplingUnavailableError(SamplingError):
    """A required observed input or solver backend is unavailable."""


def derive_seed(seed: int, *parts: object) -> int:
    """Derive a stable child seed.

    ``random.Random`` accepts tuples, but Python's string hashing is salted per
    process, so a tuple seed containing text is not reproducible across runs.
    Hashing a canonical encoding keeps every stream regenerable, which is what
    makes an interrupted generation resumable.
    """
    token = "\x1f".join([str(int(seed)), *(str(part) for part in parts)])
    return int(hashlib.sha256(token.encode()).hexdigest()[:16], 16)


@dataclass(frozen=True)
class HourPoint:
    """One observed hour of balancing-authority demand and its scale factor."""

    hour: int
    ts: str
    demand_mw: float
    scale: float
    band: Literal["calm", "mid", "stress"]

    def json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BranchFlow:
    """A solved baseline branch flow used to weight contingency sampling."""

    element_id: str
    table: Literal["line", "impedance"]
    index: int
    from_bus: int
    to_bus: int
    abs_flow_mw: float
    rating_mva: float | None
    loading_percent: float | None

    def json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlannedSample:
    """One deterministic unit of work: what to break, where, and in which hour.

    ``group_key`` is the split unit.  Splitting by it — never by row — keeps a
    contingency and its near-duplicates (the N-2 pairs built around the same
    primary element, and the placement counterfactuals of the same outage) on
    one side of the train/held-out boundary.
    """

    sample_index: int
    kind: SampleKind
    hour: int
    element_ids: tuple[str, ...]
    primary_element_id: str | None
    group_key: str
    site_bus: int | None = None
    unit_mw: float | None = None
    added_load_mw: float | None = None

    def json(self) -> dict[str, Any]:
        value = asdict(self)
        value["element_ids"] = list(self.element_ids)
        return value


@dataclass(frozen=True)
class SampleLabels:
    """Solver outcome for one sample, with missing values kept missing."""

    lost_load_mw: float
    total_served_load_mw: float
    total_shed_load_mw: float
    lost_load_reconciled: bool
    terminal_solve_status: Literal["solved", "solver_failed"]
    branch_loading_percent: dict[str, float | None] = field(default_factory=dict)
    served_load_mw_by_bus: dict[str, float] = field(default_factory=dict)
    shed_load_mw_by_bus: dict[str, float] = field(default_factory=dict)
    missing_rating_element_ids: tuple[str, ...] = ()
    out_of_service_element_ids: tuple[str, ...] = ()
    terminal_solve_error: str | None = None

    def json(self) -> dict[str, Any]:
        value = asdict(self)
        value["missing_rating_element_ids"] = list(self.missing_rating_element_ids)
        value["out_of_service_element_ids"] = list(self.out_of_service_element_ids)
        return value


@dataclass(frozen=True)
class TrainingSample:
    """One labelled row, carrying enough identity to be regenerated exactly."""

    sample_id: str
    plan: PlannedSample
    status: SampleStatus
    seed: int
    scenario_id: str
    scenario_identity: dict[str, Any]
    demand: dict[str, Any]
    labels: SampleLabels | None = None
    failure_kind: str | None = None
    failure_message: str | None = None
    solve_seconds: float | None = None
    topology: str = SYNTHETIC_TOPOLOGY_LABEL
    solver: str = "pandapower.rundcpp"
    schema_version: str = SAMPLE_SCHEMA_VERSION

    def json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sample_id": self.sample_id,
            "status": self.status,
            "seed": self.seed,
            "scenario_id": self.scenario_id,
            "topology": self.topology,
            "synthetic": True,
            "solver": self.solver,
            "model_fidelity": "dc_screening",
            "plan": self.plan.json(),
            "group_key": self.plan.group_key,
            "demand": dict(self.demand),
            "scenario_identity": dict(self.scenario_identity),
            "labels": None if self.labels is None else self.labels.json(),
            "failure_kind": self.failure_kind,
            "failure_message": self.failure_message,
            "solve_seconds": self.solve_seconds,
            "limitations": [
                "DC power flow: no reactive power, voltage, dynamics, protection, or unit commitment",
                "ACTIVSg2000 is a synthetic Texas network, not ERCOT's model",
                "Labels are this DC screening solver's output, not observed grid behaviour",
            ],
        }

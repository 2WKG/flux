"""Deterministic reconductoring intervention artifacts.

This module deliberately does not import :mod:`twin.dlr`: reconductoring is a
physical conductor replacement, not a weather-adjusted operating rating.  The
separate artifact prevents a proposed conductor from being presented as DLR.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReconductorStatus(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"


class ReconductorUnavailableReason(StrEnum):
    MISSING_BASELINE_RATING = "missing_baseline_rating"
    MISSING_PROPOSED_RATING = "missing_proposed_rating"
    NON_INCREASING_RATING = "non_increasing_rating"
    MISSING_CONDUCTOR = "missing_conductor"


@dataclass(frozen=True)
class Rating:
    """A thermal rating and the assumptions required to interpret it."""

    mw: float
    conductor: str
    unit: str = "MW"
    source: str = "fixture"
    assumption: str = "static thermal rating"


@dataclass(frozen=True)
class ReconductorArtifact:
    """A completed conductor-replacement proposal, never a DLR result."""

    intervention_type: str
    status: ReconductorStatus
    baseline: Rating
    proposed: Rating
    scenario_id: str
    uplift_mw: float
    source: str
    assumption: str


@dataclass(frozen=True)
class UnavailableReconductorArtifact:
    """A failed proposal with a machine-readable reason and no uplift."""

    intervention_type: str
    status: ReconductorStatus
    scenario_id: str
    reason: ReconductorUnavailableReason


def build_reconductor_artifact(
    *,
    scenario_id: str,
    baseline: Rating | None,
    proposed: Rating | None,
    source: str,
    assumption: str,
) -> ReconductorArtifact | UnavailableReconductorArtifact:
    """Build a deterministic reconductoring result or explicit unavailable state.

    Ratings are intentionally supplied rather than calculated from weather.  A
    replacement must increase the static rating; otherwise it is unavailable
    rather than an invented zero-benefit intervention.
    """

    if baseline is None:
        return _unavailable(scenario_id, ReconductorUnavailableReason.MISSING_BASELINE_RATING)
    if proposed is None:
        return _unavailable(scenario_id, ReconductorUnavailableReason.MISSING_PROPOSED_RATING)
    if not baseline.conductor or not proposed.conductor:
        return _unavailable(scenario_id, ReconductorUnavailableReason.MISSING_CONDUCTOR)
    if baseline.unit != "MW" or proposed.unit != "MW" or baseline.mw <= 0 or proposed.mw <= 0:
        return _unavailable(scenario_id, ReconductorUnavailableReason.MISSING_BASELINE_RATING)
    if proposed.mw <= baseline.mw:
        return _unavailable(scenario_id, ReconductorUnavailableReason.NON_INCREASING_RATING)

    return ReconductorArtifact(
        intervention_type="reconductor",
        status=ReconductorStatus.READY,
        baseline=baseline,
        proposed=proposed,
        scenario_id=scenario_id,
        uplift_mw=proposed.mw - baseline.mw,
        source=source,
        assumption=assumption,
    )


def _unavailable(
    scenario_id: str, reason: ReconductorUnavailableReason
) -> UnavailableReconductorArtifact:
    return UnavailableReconductorArtifact(
        intervention_type="reconductor",
        status=ReconductorStatus.UNAVAILABLE,
        scenario_id=scenario_id,
        reason=reason,
    )

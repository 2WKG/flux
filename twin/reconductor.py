"""Static reconductoring calculations using the shared scoring contract.

Implements spec 08 section 4 (``docs/specs/08-line-upgrade-screen.md``):
``reconductor_uplift_mw = static_rating_mw x (m - 1)`` with ``m`` by existing
conductor (1.8 for ACSR <= 795 kcmil, 1.6 for larger ACSR, 1.2 if already
ACSS/ACCC, capped at 2.0x) and ``reconductor_cost_usd = length_mi x
cost_per_mile(kV)`` plus 15 % for terminal upgrades, from a caller-supplied
``refa_costs.yaml`` mapping whose entries each carry a ``source``.

Results are master's :class:`ReconductorIntervention`; unavailable outcomes are
master's :class:`UnavailableReason`.  :func:`build_reconductor_artifact` keys a
result to a :class:`LineKey` and ``scenario_id`` and wraps an unavailable
outcome in the shared Copilot ``Unavailable{code, reason, retryable}`` envelope
so it can be joined to ``line_upgrade_scores`` / ``line_upgrade_detail`` and
reported without translation.

Nothing here fabricates a rating, multiplier, or cost: an ACSR conductor of
unknown size, a non-MW rating, or a voltage with no costed entry is reported
unavailable rather than defaulted.  This module deliberately does not import
:mod:`twin.dlr`; a test pins that separation.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from numbers import Real
from typing import Literal

from pydantic import Field, model_validator

from copilot.tools.schemas import Unavailable
from pipelines.line_upgrade_contracts import (
    Frozen,
    InterventionType,
    LineKey,
    Mw,
    ReconductorIntervention,
    UnavailableReason,
)

KM_PER_MILE = 1.609344
TERMINAL_UPGRADE_MULTIPLIER = 1.15
RATING_UNIT = "MW"
MAX_MULTIPLIER = 2.0
"""Spec 08 section 4: capped by substation/terminal equipment at 2.0x."""
ACSR_SMALL_MAX_KCMIL = 795
HTLS_MATERIALS = frozenset({"ACSS", "ACCC"})


def reconductor_multiplier(material: str, kcmil: int | None) -> float:
    """Return the spec-08 static rating multiplier for the existing conductor.

    Raises ``ValueError`` for a material outside the table and for ACSR without
    a size: the table branches on size for ACSR, and guessing the size would
    silently pick the more optimistic 1.8x.
    """
    normalized = _normalize_material(material)
    if normalized == "ACSR":
        if kcmil is None:
            raise ValueError("ACSR multiplier requires the conductor size in kcmil")
        if isinstance(kcmil, bool) or not isinstance(kcmil, int) or kcmil <= 0:
            raise ValueError(f"kcmil must be a positive int, got {kcmil!r}")
        base = 1.8 if kcmil <= ACSR_SMALL_MAX_KCMIL else 1.6
    elif normalized in HTLS_MATERIALS:
        base = 1.2
    else:
        raise ValueError("material must be ACSR, ACSS, or ACCC")
    return min(base, MAX_MULTIPLIER)


def reconductor_uplift_mw(
    rate_a_mw: float, material: str, kcmil: int | None, unit: str = RATING_UNIT
) -> float:
    """Compute static-rating uplift; no weather/DLR calculation is involved."""
    if unit != RATING_UNIT:
        raise ValueError(f"rate_a_mw must be in {RATING_UNIT}, got unit {unit!r}")
    if not _positive(rate_a_mw):
        raise ValueError("rate_a_mw must be a finite positive number")
    return float(rate_a_mw) * (reconductor_multiplier(material, kcmil) - 1.0)


def reconductor_cost_usd(
    length_km: float, base_kv: float, costs: Mapping[object, object]
) -> float:
    """Apply a sourced per-mile voltage cost plus the terminal-upgrade factor.

    ``costs`` is the voltage mapping from ``refa_costs.yaml``. Each entry must
    provide a positive ``value`` and a non-empty ``source``.  A zero or missing
    length is rejected: a zero cost makes ``mw_per_musd`` undefined (master
    treats zero cost as unknown), so it must surface as ``COST_UNKNOWN``.
    """
    if not _positive(length_km) or not _positive(base_kv):
        raise ValueError("length_km and base_kv must be finite positive numbers")
    voltage = int(float(base_kv))
    entry = costs.get(str(voltage), costs.get(voltage))
    if not isinstance(entry, Mapping):
        raise TypeError(f"no reconductoring cost for {base_kv:g} kV")
    value, source = entry.get("value"), entry.get("source")
    if not _positive(value) or not isinstance(source, str) or not source.strip():
        raise ValueError("cost entries require a positive value and source")
    return float(length_km) / KM_PER_MILE * float(value) * TERMINAL_UPGRADE_MULTIPLIER


def build_reconductor_intervention(
    *,
    rate_a_mw: float | None,
    material: str | None,
    kcmil: int | None,
    length_km: float | None,
    base_kv: float | None,
    costs: Mapping[object, object],
    unit: str = RATING_UNIT,
) -> ReconductorIntervention | UnavailableReason:
    """Return a consumable reconductoring intervention or its canonical reason."""
    result = _evaluate(
        rate_a_mw=rate_a_mw,
        material=material,
        kcmil=kcmil,
        length_km=length_km,
        base_kv=base_kv,
        costs=costs,
        unit=unit,
    )
    return result if isinstance(result, ReconductorIntervention) else result[0]


class ReconductorArtifact(Frozen):
    """A computed reconductoring intervention for one line in one scenario."""

    key: LineKey
    scenario_id: str = Field(min_length=1)
    static_rating_mw: Mw
    multiplier: float = Field(gt=1.0, le=MAX_MULTIPLIER)
    intervention: ReconductorIntervention

    @model_validator(mode="after")
    def _scenario_matches_key(self) -> ReconductorArtifact:
        _require_scenario_matches_key(self.key, self.scenario_id)
        return self


class UnavailableReconductorArtifact(Frozen):
    """No intervention for the line. Has no uplift or cost field to fabricate."""

    key: LineKey
    scenario_id: str = Field(min_length=1)
    intervention_type: Literal[InterventionType.RECONDUCTOR] = (
        InterventionType.RECONDUCTOR
    )
    reason: UnavailableReason
    unavailable: Unavailable
    detail: str = Field(min_length=1)

    @model_validator(mode="after")
    def _scenario_matches_key(self) -> UnavailableReconductorArtifact:
        _require_scenario_matches_key(self.key, self.scenario_id)
        return self


def _require_scenario_matches_key(key: LineKey, scenario_id: str) -> None:
    """The artifact's scenario is the key's scenario; two identities may not drift."""
    if scenario_id != key.scenario_id:
        raise ValueError(
            "reconductor artifact scenario_id must match the line key scenario_id"
        )


def build_reconductor_artifact(
    *,
    key: LineKey,
    scenario_id: str,
    rate_a_mw: float | None,
    material: str | None,
    kcmil: int | None,
    length_km: float | None,
    base_kv: float | None,
    costs: Mapping[object, object],
    unit: str = RATING_UNIT,
) -> ReconductorArtifact | UnavailableReconductorArtifact:
    """Key :func:`build_reconductor_intervention` to a line and scenario.

    Deterministic: equal inputs give equal artifacts.  Unavailable outcomes
    carry master's reason and the shared ``Unavailable`` envelope
    (``code="invalid_prerequisite"``, ``reason=<UnavailableReason value>``).
    """
    result = _evaluate(
        rate_a_mw=rate_a_mw,
        material=material,
        kcmil=kcmil,
        length_km=length_km,
        base_kv=base_kv,
        costs=costs,
        unit=unit,
    )
    if isinstance(result, ReconductorIntervention):
        return ReconductorArtifact(
            key=key,
            scenario_id=scenario_id,
            static_rating_mw=float(rate_a_mw),  # type: ignore[arg-type]  # validated
            multiplier=reconductor_multiplier(result.conductor_material, kcmil),
            intervention=result,
        )
    reason, detail = result
    return UnavailableReconductorArtifact(
        key=key,
        scenario_id=scenario_id,
        reason=reason,
        unavailable=Unavailable(
            code="invalid_prerequisite", reason=reason.value, retryable=False
        ),
        detail=detail,
    )


def _evaluate(
    *,
    rate_a_mw: float | None,
    material: str | None,
    kcmil: int | None,
    length_km: float | None,
    base_kv: float | None,
    costs: Mapping[object, object],
    unit: str,
) -> ReconductorIntervention | tuple[UnavailableReason, str]:
    if unit != RATING_UNIT:
        return (
            UnavailableReason.NO_RATING,
            f"rating unit must be {RATING_UNIT}, got {unit!r}",
        )
    if rate_a_mw is None or not _positive(rate_a_mw):
        return (
            UnavailableReason.NO_RATING,
            f"static rating must be a finite positive number of MW, got {rate_a_mw!r}",
        )
    if not isinstance(material, str) or not material.strip():
        return UnavailableReason.NO_CONDUCTOR, "conductor material is required"
    try:
        uplift_mw = reconductor_uplift_mw(rate_a_mw, material, kcmil, unit)
    except (TypeError, ValueError) as exc:
        return UnavailableReason.NO_CONDUCTOR, str(exc)
    try:
        cost_usd = reconductor_cost_usd(length_km, base_kv, costs)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        return UnavailableReason.COST_UNKNOWN, str(exc)
    return ReconductorIntervention(
        uplift_mw=uplift_mw,
        cost_usd=cost_usd,
        conductor_material=_normalize_material(material),
        conductor_kcmil=kcmil,
    )


def _normalize_material(material: object) -> str:
    """The conductor class the multiplier was chosen for, as persisted."""
    if not isinstance(material, str):
        raise TypeError("material must be a string")
    return material.strip().upper()


def _positive(value: object) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and isfinite(float(value))
        and float(value) > 0.0
    )

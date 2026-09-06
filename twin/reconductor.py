"""Static reconductoring calculations using the shared scoring contract."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from numbers import Real

from pipelines.line_upgrade_contracts import ReconductorIntervention, UnavailableReason

KM_PER_MILE = 1.609344
TERMINAL_UPGRADE_MULTIPLIER = 1.15


def reconductor_multiplier(material: str, kcmil: int | None) -> float:
    """Return the spec-08 static rating multiplier for the existing conductor."""
    normalized = material.strip().upper()
    if normalized == "ACSR":
        return 1.8 if kcmil is None or kcmil <= 795 else 1.6
    if normalized in {"ACSS", "ACCC"}:
        return 1.2
    raise ValueError("material must be ACSR, ACSS, or ACCC")


def reconductor_uplift_mw(rate_a_mw: float, material: str, kcmil: int | None) -> float:
    """Compute static-rating uplift; no weather/DLR calculation is involved."""
    if not _positive(rate_a_mw):
        raise ValueError("rate_a_mw must be a finite positive number")
    return float(rate_a_mw) * (reconductor_multiplier(material, kcmil) - 1.0)


def reconductor_cost_usd(
    length_km: float, base_kv: float, costs: Mapping[object, object]
) -> float:
    """Apply a sourced per-mile voltage cost plus the terminal-upgrade factor.

    ``costs`` is the voltage mapping from ``refa_costs.yaml``. Each entry must
    provide a positive ``value`` and a non-empty ``source``.
    """
    if not _nonnegative(length_km) or not _positive(base_kv):
        raise ValueError("length_km must be finite/non-negative and base_kv positive")
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
) -> ReconductorIntervention | UnavailableReason:
    """Return a consumable reconductoring intervention or its canonical reason."""
    if rate_a_mw is None or not _positive(rate_a_mw):
        return UnavailableReason.NO_RATING
    if not material or not material.strip():
        return UnavailableReason.NO_CONDUCTOR
    try:
        uplift_mw = reconductor_uplift_mw(rate_a_mw, material, kcmil)
    except ValueError:
        return UnavailableReason.NO_CONDUCTOR
    try:
        cost_usd = reconductor_cost_usd(length_km, base_kv, costs)
    except (TypeError, ValueError):
        return UnavailableReason.COST_UNKNOWN
    return ReconductorIntervention(
        uplift_mw=uplift_mw,
        cost_usd=cost_usd,
        conductor_material=material,
        conductor_kcmil=kcmil,
    )


def _positive(value: object) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and isfinite(float(value))
        and float(value) > 0.0
    )


def _nonnegative(value: object) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and isfinite(float(value))
        and float(value) >= 0.0
    )

"""Fail-closed IEEE 738-style dynamic line rating calculations.

The public scorer supplies weather in SI units (m/s and degrees Celsius) and
line ratings in MW.  This module deliberately does not infer a conductor or
weather value: an incomplete or unsupported weather slice is reported as
unavailable rather than producing a plausible-looking rating.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, pi, sin, sqrt
from numbers import Integral, Real
from typing import Any

import pandas as pd

_MIN_SUPPORTED_TEMP_C = -60.0
_MAX_SUPPORTED_TEMP_C = 60.0
_MAX_SUPPORTED_WIND_MS = 60.0
_STATIC_WIND_MS = 0.61  # 2 ft/s, the IEEE/vendor static-rating convention.
_DLR_WIND_MAX_MS = 5.0  # Spec 08 cap; stronger wind must not inflate a rating.
_WIND_ANGLE_DEG = 45.0  # Explicit planning assumption pending line azimuth data.
_TEXAS_CENTRAL_TIMEZONE = "America/Chicago"
_NATURAL_CONVECTION_SI_COEFFICIENT = 3.645


@dataclass(frozen=True)
class Conductor:
    """Bare-conductor properties used by the steady-state heat balance.

    Resistances are AC resistance per metre at 25 and 75 degrees Celsius.
    ``emissivity`` and ``absorptivity`` default to planning values; callers
    performing the Drake vendor calibration must explicitly use 0.5 for both.
    """

    name: str
    kcmil: int
    diameter_m: float
    r_ac_25c_ohm_m: float
    r_ac_75c_ohm_m: float
    t_max_c: float
    emissivity: float = 0.8
    absorptivity: float = 0.8


def _validate_conductor(cond: Conductor) -> None:
    """Validate only bounded primitive properties the heat balance can support."""

    if not isinstance(cond, Conductor):
        raise TypeError("conductor must be a Conductor")
    if not isinstance(cond.name, str) or not cond.name.strip():
        raise ValueError("conductor name is required")
    if (
        isinstance(cond.kcmil, bool)
        or not isinstance(cond.kcmil, Integral)
        or not 1 <= cond.kcmil <= 10_000
    ):
        raise ValueError("conductor kcmil must be an integer in the supported range")

    numeric: dict[str, float] = {}
    for field in (
        "diameter_m",
        "r_ac_25c_ohm_m",
        "r_ac_75c_ohm_m",
        "t_max_c",
        "emissivity",
        "absorptivity",
    ):
        value = getattr(cond, field)
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError(f"conductor {field} must be a finite number")
        try:
            numeric[field] = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"conductor {field} must be a finite number") from exc
        if not isfinite(numeric[field]):
            raise ValueError(f"conductor {field} must be finite")

    if not 0.001 <= numeric["diameter_m"] <= 0.1:
        raise ValueError("conductor diameter_m is outside the supported range")
    if (
        not 1e-8 <= numeric["r_ac_25c_ohm_m"] <= 1.0
        or not 1e-8 <= numeric["r_ac_75c_ohm_m"] <= 1.0
    ):
        raise ValueError("conductor resistances are outside the supported range")
    if not 40.0 < numeric["t_max_c"] <= 250.0:
        raise ValueError("conductor t_max_c is outside the supported range")
    if (
        not 0.0 < numeric["emissivity"] <= 1.0
        or not 0.0 <= numeric["absorptivity"] <= 1.0
    ):
        raise ValueError("emissivity and absorptivity must be in [0, 1]")


def _air_properties(temp_c: float, elevation_m: float) -> tuple[float, float, float]:
    """Return density, dynamic viscosity, and thermal conductivity of air.

    The temperature-film approximation and Sutherland relation are the
    standard engineering approximation used by the IEEE forced-convection
    correlations.  Elevation is converted with the ISA barometric relation.
    """

    film_k = temp_c + 273.15
    pressure_pa = 101325.0 * (1.0 - 2.25577e-5 * elevation_m) ** 5.2559
    density = pressure_pa / (287.05 * film_k)
    viscosity = 1.458e-6 * film_k**1.5 / (film_k + 110.4)
    conductivity = 0.02424 * (film_k / 273.15) ** 0.9
    return density, viscosity, conductivity


def _resistance_at_c(cond: Conductor, temp_c: float) -> float:
    """Interpolate the supplied AC resistance without inventing a new table."""

    return cond.r_ac_25c_ohm_m + (temp_c - 25.0) * (
        (cond.r_ac_75c_ohm_m - cond.r_ac_25c_ohm_m) / 50.0
    )


def _wind_direction_factor(wind_angle_deg: float) -> float:
    # IEEE 738 Eq. 4.4.3 direction factor, angle relative to conductor axis.
    angle = abs(wind_angle_deg) % 180.0
    # A reversed wind has the same angle to an unoriented conductor axis.
    if angle > 90.0:
        angle = 180.0 - angle
    radians = angle * pi / 180.0
    return (
        1.194 - cos(radians) + 0.194 * cos(2.0 * radians) + 0.368 * sin(2.0 * radians)
    )


def ieee738_ampacity_a(
    cond: Conductor,
    wind_ms: float,
    temp_amb_c: float,
    t_cond_c: float,
    wind_angle_deg: float = _WIND_ANGLE_DEG,
    solar_w_m2: float = 1000.0,
    elevation_m: float = 300.0,
) -> float:
    """Calculate steady-state ampacity (A) from the IEEE 738 heat balance.

    Inputs use m/s, degrees Celsius, W/m², and metres.  The default is the
    declared 45-degree planning assumption.  Callers reproducing a vendor
    rating must pass that rating's wind angle explicitly (the Drake fixture is
    perpendicular wind).  Invalid heat balance or unsupported physical inputs
    raise ``ValueError`` instead of returning a zero or substituted value. The
    caller-facing hourly API converts such errors into an explicit unavailable
    result.
    """

    _validate_conductor(cond)
    values = (wind_ms, temp_amb_c, t_cond_c, wind_angle_deg, solar_w_m2, elevation_m)
    if any(not isfinite(value) for value in values):
        raise ValueError("ampacity inputs must be finite")
    if wind_ms < 0.0 or wind_ms > _MAX_SUPPORTED_WIND_MS:
        raise ValueError("wind_ms is outside the supported 0–60 m/s range")
    if not _MIN_SUPPORTED_TEMP_C <= temp_amb_c <= _MAX_SUPPORTED_TEMP_C:
        raise ValueError("temp_amb_c is outside the supported -60–60 C range")
    if t_cond_c <= temp_amb_c:
        raise ValueError("conductor temperature must exceed ambient temperature")
    if (
        solar_w_m2 < 0.0
        or solar_w_m2 > 1400.0
        or elevation_m < -500.0
        or elevation_m > 6000.0
    ):
        raise ValueError("solar irradiance or elevation is outside the supported range")

    delta_t = t_cond_c - temp_amb_c
    film_c = (t_cond_c + temp_amb_c) / 2.0
    density, viscosity, conductivity = _air_properties(film_c, elevation_m)
    reynolds = max(density * wind_ms * cond.diameter_m / viscosity, 0.0)
    # IEEE's low- and high-wind forced-convection correlations, plus natural
    # convection; selecting the maximum prevents a wind-direction artefact
    # from lowering heat loss below the natural-convection case.
    direction = _wind_direction_factor(wind_angle_deg)
    forced_low = direction * conductivity * delta_t * (1.01 + 1.35 * reynolds**0.52)
    forced_high = direction * conductivity * delta_t * (0.754 * reynolds**0.6)
    natural = (
        _NATURAL_CONVECTION_SI_COEFFICIENT
        * sqrt(density)
        * cond.diameter_m**0.75
        * delta_t**1.25
    )
    convection = max(natural, forced_low, forced_high)
    radiation = (
        17.8
        * cond.diameter_m
        * cond.emissivity
        * (((t_cond_c + 273.15) / 100.0) ** 4 - ((temp_amb_c + 273.15) / 100.0) ** 4)
    )
    solar = cond.absorptivity * solar_w_m2 * cond.diameter_m
    joule_heat_w_m = convection + radiation - solar
    resistance = _resistance_at_c(cond, t_cond_c)
    if joule_heat_w_m <= 0.0 or resistance <= 0.0:
        raise ValueError("heat balance cannot support a positive ampacity")
    return sqrt(joule_heat_w_m / resistance)


def _unavailable_ratings(reason: str) -> pd.DataFrame:
    result = pd.DataFrame(
        columns=["ts", "static_mw", "aar_mw", "dlr_mw", "status", "unavailable_reason"]
    )
    result.attrs.update(
        {
            "status": "unavailable",
            "unavailable_reason": reason,
            "input_units": {"wind_ms": "m/s", "temp_c": "degC", "ts": "UTC timestamp"},
            "output_unit": "MW",
            "provenance": "IEEE 738 steady-state planning calculation; no fallback weather or conductor values",
        }
    )
    return result


def _normalise_weather(weather: pd.DataFrame) -> tuple[pd.DataFrame | None, str | None]:
    if not isinstance(weather, pd.DataFrame):
        return None, "weather must be a pandas DataFrame"
    required = {"ts", "wind_ms", "temp_c"}
    missing = sorted(required - set(weather.columns))
    if missing:
        return None, f"weather is missing required columns: {', '.join(missing)}"
    if weather.empty:
        return None, "weather contains no hourly observations"
    normalised = weather.loc[:, ["ts", "wind_ms", "temp_c"]].copy()
    normalised["ts"] = pd.to_datetime(normalised["ts"], utc=True, errors="coerce")
    normalised["wind_ms"] = pd.to_numeric(normalised["wind_ms"], errors="coerce")
    normalised["temp_c"] = pd.to_numeric(normalised["temp_c"], errors="coerce")
    if normalised.isna().any().any():
        return (
            None,
            "weather contains missing or non-numeric timestamps, wind, or temperature",
        )
    if (normalised["wind_ms"] < 0.0).any() or (
        normalised["wind_ms"] > _MAX_SUPPORTED_WIND_MS
    ).any():
        return None, "weather wind_ms is outside the supported 0–60 m/s range"
    if (normalised["temp_c"] < _MIN_SUPPORTED_TEMP_C).any() or (
        normalised["temp_c"] > _MAX_SUPPORTED_TEMP_C
    ).any():
        return None, "weather temp_c is outside the supported -60–60 C range"
    return normalised.sort_values("ts", kind="stable").reset_index(drop=True), None


def _clear_sky_solar_w_m2(ts: pd.Timestamp) -> float:
    """Return the fixed clear-sky curve using Texas Central civil time.

    Weather timestamps follow the shared UTC contract.  The curve is evaluated
    in ``America/Chicago`` (including daylight saving time), not in UTC and not
    from site-specific longitude-based solar time.
    """

    local_ts = ts.tz_convert(_TEXAS_CENTRAL_TIMEZONE)
    hour = local_ts.hour + local_ts.minute / 60.0
    return max(0.0, sin(pi * (hour - 6.0) / 12.0)) * 1000.0


def hourly_ratings_mw(
    line_id: str,
    cond: Conductor,
    weather: pd.DataFrame,
    base_kv: float,
    rate_a_mw: float,
) -> pd.DataFrame:
    """Return static, ambient-adjusted, and directional DLR ratings in MW.

    A result whose ``attrs['status']`` is ``'unavailable'`` intentionally has
    no rating rows.  It is the fail-closed response for missing data, invalid
    units/ranges, an unsupported conductor, or an invalid line prerequisite.
    """

    if not isinstance(line_id, str) or not line_id.strip():
        return _unavailable_ratings("line_id is required")
    if not all(
        not isinstance(value, bool)
        and isinstance(value, Real)
        and isfinite(float(value))
        for value in (base_kv, rate_a_mw)
    ):
        return _unavailable_ratings("base_kv and rate_a_mw must be finite numbers")
    if not 1.0 <= float(base_kv) <= 1200.0 or float(rate_a_mw) <= 0.0:
        return _unavailable_ratings(
            "base_kv or rate_a_mw is outside the supported range"
        )
    try:
        _validate_conductor(cond)
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        return _unavailable_ratings(f"unsupported conductor: {exc}")
    normalised, reason = _normalise_weather(weather)
    if reason:
        return _unavailable_ratings(reason)
    assert normalised is not None

    try:
        static_a = ieee738_ampacity_a(
            cond,
            _STATIC_WIND_MS,
            40.0,
            cond.t_max_c,
            wind_angle_deg=_WIND_ANGLE_DEG,
            solar_w_m2=1000.0,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        return _unavailable_ratings(
            f"static IEEE 738 calibration is unavailable: {exc}"
        )
    static_physics_mw = sqrt(3.0) * float(base_kv) * static_a / 1000.0
    calibration = float(rate_a_mw) / static_physics_mw

    rows: list[dict[str, Any]] = []
    try:
        for observation in normalised.itertuples(index=False):
            solar_w_m2 = _clear_sky_solar_w_m2(observation.ts)
            aar_a = ieee738_ampacity_a(
                cond,
                _STATIC_WIND_MS,
                float(observation.temp_c),
                cond.t_max_c,
                wind_angle_deg=_WIND_ANGLE_DEG,
                solar_w_m2=solar_w_m2,
            )
            effective_wind_ms = min(
                max(float(observation.wind_ms), _STATIC_WIND_MS), _DLR_WIND_MAX_MS
            )
            dlr_a = ieee738_ampacity_a(
                cond,
                effective_wind_ms,
                float(observation.temp_c),
                cond.t_max_c,
                wind_angle_deg=_WIND_ANGLE_DEG,
                solar_w_m2=solar_w_m2,
            )
            rows.append(
                {
                    "ts": observation.ts,
                    "static_mw": float(rate_a_mw),
                    "aar_mw": sqrt(3.0) * float(base_kv) * aar_a / 1000.0 * calibration,
                    "dlr_mw": sqrt(3.0) * float(base_kv) * dlr_a / 1000.0 * calibration,
                    "status": "ok",
                    "unavailable_reason": None,
                }
            )
    except (TypeError, ValueError, OverflowError) as exc:
        return _unavailable_ratings(
            f"hourly IEEE 738 calculation is unavailable: {exc}"
        )

    result = pd.DataFrame(rows)
    result.attrs.update(
        {
            "status": "ok",
            "input_units": {"wind_ms": "m/s", "temp_c": "degC", "ts": "UTC timestamp"},
            "output_unit": "MW",
            "provenance": {
                "standard": "IEEE 738 steady-state heat balance",
                "static_reference": "0.61 m/s, 40 C ambient, 1000 W/m2 solar",
                "calibration": "scaled to the supplied synthetic rate_a_mw",
                "dlr_wind": "hourly wind clamped to 0.61–5.0 m/s",
                "wind_angle_deg": _WIND_ANGLE_DEG,
                "solar": (
                    "fixed clear-sky hourly curve evaluated in Texas Central civil time "
                    "(America/Chicago, including daylight saving time), not UTC or "
                    "site-specific solar time; cloud cover is not modeled"
                ),
            },
        }
    )
    return result


def dlr_summary(ratings: pd.DataFrame) -> dict[str, Any]:
    """Summarise a ratings frame without concealing unavailable prerequisites."""

    if not isinstance(ratings, pd.DataFrame):
        return {
            "status": "unavailable",
            "reason": "ratings must be a pandas DataFrame",
            "unit": "MW",
        }
    if ratings.attrs.get("status") == "unavailable":
        return {
            "status": "unavailable",
            "reason": ratings.attrs.get(
                "unavailable_reason", "ratings are unavailable"
            ),
            "unit": "MW",
            "provenance": ratings.attrs.get("provenance"),
        }
    required = {"static_mw", "dlr_mw"}
    if ratings.empty or not required.issubset(ratings.columns):
        return {
            "status": "unavailable",
            "reason": "ratings contain no usable static and DLR values",
            "unit": "MW",
        }
    uplift = (
        pd.to_numeric(ratings["dlr_mw"], errors="coerce")
        - pd.to_numeric(ratings["static_mw"], errors="coerce")
    ).clip(lower=0.0)
    if uplift.isna().any():
        return {
            "status": "unavailable",
            "reason": "ratings contain non-numeric values",
            "unit": "MW",
        }
    static = pd.to_numeric(ratings["static_mw"], errors="coerce")
    return {
        "status": "ok",
        "dlr_uplift_mw": float(uplift.quantile(0.5)),
        "p10_uplift_mw": float(uplift.quantile(0.1)),
        "p90_uplift_mw": float(uplift.quantile(0.9)),
        "hours_above_static": int((uplift > static * 0.05).sum()),
        "unit": "MW",
        "provenance": ratings.attrs.get("provenance"),
    }


def dlr_cost_usd(length_km: float) -> float:
    """Return the stated DLR planning cost: $40k/mile plus a $60k floor."""

    if (
        isinstance(length_km, bool)
        or not isinstance(length_km, Real)
        or not isfinite(float(length_km))
        or float(length_km) < 0.0
    ):
        raise ValueError("length_km must be a finite non-negative number")
    return float(length_km) / 1.609344 * 40_000.0 + 60_000.0

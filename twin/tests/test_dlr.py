from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from twin.dlr import (
    Conductor,
    _clear_sky_solar_w_m2,
    dlr_summary,
    hourly_ratings_mw,
    ieee738_ampacity_a,
)


@pytest.fixture
def drake() -> Conductor:
    # 1.108 in OD; 0.021 ohm/kft at 20 C.  The AC values are deliberately
    # supplied rather than silently inferred from the vendor's DC resistance.
    return Conductor(
        name="Drake 795 kcmil ACSR 26/7",
        kcmil=795,
        diameter_m=0.0281432,
        r_ac_25c_ohm_m=6.8898e-5,
        r_ac_75c_ohm_m=8.2782e-5,
        t_max_c=75.0,
        emissivity=0.5,
        absorptivity=0.5,
    )


def test_drake_vendor_anchor_and_directional_monotonicity(drake: Conductor) -> None:
    anchor = ieee738_ampacity_a(
        drake, wind_ms=0.61, temp_amb_c=25.0, t_cond_c=75.0, wind_angle_deg=90.0
    )
    hotter = ieee738_ampacity_a(drake, wind_ms=0.61, temp_amb_c=40.0, t_cond_c=75.0)
    crosswind = ieee738_ampacity_a(
        drake, wind_ms=2.0, temp_amb_c=25.0, t_cond_c=75.0, wind_angle_deg=90.0
    )
    alongwind = ieee738_ampacity_a(
        drake, wind_ms=2.0, temp_amb_c=25.0, t_cond_c=75.0, wind_angle_deg=0.0
    )
    nominal_direction = ieee738_ampacity_a(
        drake, wind_ms=2.0, temp_amb_c=25.0, t_cond_c=75.0, wind_angle_deg=45.0
    )
    reversed_direction = ieee738_ampacity_a(
        drake, wind_ms=2.0, temp_amb_c=25.0, t_cond_c=75.0, wind_angle_deg=135.0
    )

    assert anchor == pytest.approx(907.0, rel=0.05)
    assert hotter < anchor
    assert crosswind > alongwind
    assert reversed_direction == pytest.approx(nominal_direction)


def test_ieee738_drake_numeric_pins_include_still_air_natural_convection(
    drake: Conductor,
) -> None:
    still_air = ieee738_ampacity_a(
        drake,
        wind_ms=0.0,
        temp_amb_c=40.0,
        t_cond_c=100.0,
        wind_angle_deg=90.0,
        solar_w_m2=1000.0,
        elevation_m=0.0,
    )
    ieee_worked_example = ieee738_ampacity_a(
        drake,
        wind_ms=0.61,
        temp_amb_c=40.0,
        t_cond_c=100.0,
        wind_angle_deg=90.0,
        solar_w_m2=1000.0,
        elevation_m=0.0,
    )

    assert still_air == pytest.approx(767.0, abs=3.0)
    assert ieee_worked_example == pytest.approx(1020.0, abs=3.0)


def test_hourly_ratings_normalise_units_and_reward_crosswind_weather(
    drake: Conductor,
) -> None:
    weather = pd.DataFrame(
        {
            "ts": ["2026-01-01T12:00:00-05:00", "2026-01-01T13:00:00-05:00"],
            "wind_ms": [0.61, 5.0],
            "temp_c": [40.0, 40.0],
        }
    )

    ratings = hourly_ratings_mw(
        "line-1", drake, weather, base_kv=230.0, rate_a_mw=300.0
    )

    assert ratings.attrs["status"] == "ok"
    assert ratings.attrs["input_units"] == {
        "wind_ms": "m/s",
        "temp_c": "degC",
        "ts": "UTC timestamp",
    }
    assert ratings.attrs["output_unit"] == "MW"
    assert str(ratings.loc[0, "ts"].tz) == "UTC"
    assert ratings.loc[0, "static_mw"] == pytest.approx(300.0)
    assert ratings.loc[1, "dlr_mw"] > ratings.loc[0, "dlr_mw"]
    assert ratings.loc[0, "dlr_mw"] >= ratings.loc[0, "aar_mw"]

    summary = dlr_summary(ratings)
    assert summary["status"] == "ok"
    assert summary["unit"] == "MW"
    assert summary["hours_above_static"] >= 1


def test_clear_sky_solar_uses_texas_central_time_for_utc_weather_timestamps() -> None:
    texas_noon = pd.Timestamp("2026-06-01T12:00:00-05:00")
    same_instant_utc = pd.Timestamp("2026-06-01T17:00:00Z")

    assert _clear_sky_solar_w_m2(texas_noon) == pytest.approx(1000.0)
    assert _clear_sky_solar_w_m2(same_instant_utc) == pytest.approx(1000.0)


def test_hourly_ratings_provenance_labels_texas_central_solar_clock(
    drake: Conductor,
) -> None:
    weather = pd.DataFrame(
        {"ts": ["2026-06-01T17:00:00Z"], "wind_ms": [1.0], "temp_c": [20.0]}
    )

    ratings = hourly_ratings_mw(
        "line-1", drake, weather, base_kv=230.0, rate_a_mw=300.0
    )

    solar_provenance = ratings.attrs["provenance"]["solar"]
    assert "America/Chicago" in solar_provenance
    assert "not UTC or site-specific solar time" in solar_provenance


@pytest.mark.parametrize(
    ("weather", "expected_reason"),
    [
        (
            pd.DataFrame({"ts": ["2026-01-01T00:00:00Z"], "temp_c": [20.0]}),
            "missing required columns",
        ),
        (
            pd.DataFrame(
                {"ts": ["2026-01-01T00:00:00Z"], "wind_ms": [-0.1], "temp_c": [20.0]}
            ),
            "outside the supported",
        ),
        (
            pd.DataFrame(
                {"ts": ["not-a-timestamp"], "wind_ms": [1.0], "temp_c": [20.0]}
            ),
            "missing or non-numeric",
        ),
    ],
)
def test_unavailable_weather_fails_closed(
    drake: Conductor, weather: pd.DataFrame, expected_reason: str
) -> None:
    ratings = hourly_ratings_mw(
        "line-1", drake, weather, base_kv=230.0, rate_a_mw=300.0
    )

    assert ratings.empty
    assert ratings.attrs["status"] == "unavailable"
    assert expected_reason in ratings.attrs["unavailable_reason"]
    summary = dlr_summary(ratings)
    assert summary["status"] == "unavailable"
    assert expected_reason in summary["reason"]


def test_invalid_primitive_inputs_do_not_produce_a_rating(drake: Conductor) -> None:
    weather = pd.DataFrame(
        {"ts": ["2026-01-01T00:00:00Z"], "wind_ms": [1.0], "temp_c": [20.0]}
    )

    ratings = hourly_ratings_mw("line-1", drake, weather, base_kv=0.0, rate_a_mw=300.0)
    assert ratings.attrs["status"] == "unavailable"
    with pytest.raises(ValueError, match="wind_ms"):
        ieee738_ampacity_a(drake, wind_ms=-1.0, temp_amb_c=25.0, t_cond_c=75.0)


def test_numpy_real_scalars_are_accepted_for_conductor_and_line_inputs(
    drake: Conductor,
) -> None:
    numpy_drake = replace(
        drake,
        kcmil=np.int64(795),
        diameter_m=np.float32(drake.diameter_m),
        r_ac_25c_ohm_m=np.float32(drake.r_ac_25c_ohm_m),
        r_ac_75c_ohm_m=np.float32(drake.r_ac_75c_ohm_m),
        t_max_c=np.float32(drake.t_max_c),
        emissivity=np.float32(drake.emissivity),
        absorptivity=np.float32(drake.absorptivity),
    )
    weather = pd.DataFrame(
        {"ts": ["2026-01-01T00:00:00Z"], "wind_ms": [1.0], "temp_c": [20.0]}
    )

    ratings = hourly_ratings_mw(
        "line-1",
        numpy_drake,
        weather,
        base_kv=np.float32(230.0),
        rate_a_mw=np.float32(300.0),
    )

    assert ratings.attrs["status"] == "ok"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", None),
        ("kcmil", "795"),
        ("diameter_m", 1e308),
        ("r_ac_25c_ohm_m", None),
        ("r_ac_75c_ohm_m", 1e308),
        ("t_max_c", 1e308),
        ("emissivity", "0.5"),
        ("absorptivity", 1e308),
    ],
)
def test_malformed_or_extreme_conductor_fields_fail_closed(
    drake: Conductor, field: str, value: object
) -> None:
    malformed = replace(drake, **{field: value})
    weather = pd.DataFrame(
        {"ts": ["2026-01-01T00:00:00Z"], "wind_ms": [1.0], "temp_c": [20.0]}
    )

    ratings = hourly_ratings_mw(
        "line-1", malformed, weather, base_kv=230.0, rate_a_mw=300.0
    )

    assert ratings.empty
    assert ratings.attrs["status"] == "unavailable"
    assert ratings.attrs["unavailable_reason"].startswith("unsupported conductor:")

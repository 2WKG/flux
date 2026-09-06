"""Hourly demand scaling for training samples, read from observed EIA-930 rows.

Per ``docs/specs/12-interactive-simulation.md`` §12.1 the hourly scale of a load
is ``ba_load_hourly[ba_code, h] / ba_load_hourly[ba_code, ts_start]``.

One honest limitation is recorded on every sample instead of being papered
over: ``buses.ba_code`` is not populated in the shipped grid database, so there
is no per-bus balancing-authority assignment to scale against.  This module
therefore applies **one system-wide factor** from a single BA series and reports
``per_bus_ba_code: "unavailable"``.  It never invents a per-bus BA code.  An
hour with no observed demand row is unavailable, not defaulted.
"""

from __future__ import annotations

import copy
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from gnn.contracts import HourPoint, SamplingError, derive_seed
from twin.contracts import SimulationUnavailableError

DEFAULT_BA_CODE = "ERCO"
CALM_QUANTILE = 0.33
STRESS_QUANTILE = 0.90


def hourly_demand_profile(
    db_path: str | Path,
    *,
    ba_code: str = DEFAULT_BA_CODE,
    max_hours: int | None = None,
) -> list[HourPoint]:
    """Read observed hourly demand and turn it into scale factors.

    Hours whose ``demand_mw`` is NULL or non-positive are dropped from the
    profile and can never be sampled; they are not filled in.
    """
    path = Path(db_path)
    if not path.is_file():
        raise SimulationUnavailableError(f"demand database is unavailable: {path}")
    con = duckdb.connect(str(path), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if "ba_load_hourly" not in tables:
            raise SimulationUnavailableError(
                "demand database has no ba_load_hourly table"
            )
        rows = con.execute(
            "SELECT ts, demand_mw FROM ba_load_hourly WHERE ba_code = ? ORDER BY ts",
            [ba_code],
        ).fetchall()
    finally:
        con.close()
    if not rows:
        raise SimulationUnavailableError(
            f"ba_load_hourly has no rows for balancing authority {ba_code!r}"
        )
    observed = [
        (index, ts, float(demand_mw))
        for index, (ts, demand_mw) in enumerate(rows)
        if demand_mw is not None and float(demand_mw) > 0
    ]
    if not observed:
        raise SimulationUnavailableError(
            f"ba_load_hourly has no positive observed demand for {ba_code!r}"
        )
    reference = observed[0][2]
    if max_hours is not None:
        observed = observed[: int(max_hours)]
    values = sorted(demand for _, _, demand in observed)
    calm_edge = values[max(int(CALM_QUANTILE * (len(values) - 1)), 0)]
    stress_edge = values[min(int(STRESS_QUANTILE * (len(values) - 1)), len(values) - 1)]
    profile = [
        HourPoint(
            hour=index,
            ts=_utc_timestamp(ts),
            demand_mw=round(demand, 6),
            scale=round(demand / float(reference), 9),
            band=(
                "calm"
                if demand <= calm_edge
                else ("stress" if demand >= stress_edge else "mid")
            ),
        )
        for index, ts, demand in observed
    ]
    return profile


def _utc_timestamp(value: object) -> str:
    """Render the DuckDB UTC timestamp in the artifact's unambiguous form."""
    if not isinstance(value, datetime):
        raise SimulationUnavailableError("EIA-930 demand timestamp is not a timestamp")
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def select_hours(
    profile: list[HourPoint],
    *,
    count: int,
    seed: int,
    band_weights: dict[str, float] | None = None,
) -> list[HourPoint]:
    """Choose hours spanning calm and stress conditions, deterministically.

    Uniform hour sampling under-represents the stress hours where contingencies
    actually bite, so stress hours are drawn at a higher rate than their share
    of the year while calm hours stay represented.
    """
    if count < 1:
        raise SamplingError("hour count must be at least one")
    if not profile:
        raise SamplingError("hour profile is empty")
    weights = band_weights or {"calm": 0.25, "mid": 0.35, "stress": 0.40}
    by_band: dict[str, list[HourPoint]] = {"calm": [], "mid": [], "stress": []}
    for point in profile:
        by_band[point.band].append(point)
    chosen: list[HourPoint] = []
    for band in ("calm", "mid", "stress"):
        available = by_band[band]
        if not available:
            continue
        want = min(max(round(weights.get(band, 0.0) * count), 1), len(available))
        rng = random.Random(derive_seed(seed, "hours", band))
        chosen.extend(rng.sample(available, want))
    rng = random.Random(derive_seed(seed, "hours", "order"))
    rng.shuffle(chosen)
    # Fewer observed hours than requested returns fewer hours; this function
    # never repeats or invents an hour to hit a target count.
    return sorted(chosen[:count], key=lambda point: point.hour)


def scaled_network(net: Any, point: HourPoint, *, scale_dispatch: bool = True) -> Any:
    """Return a copy of the baseline scaled to one observed demand hour.

    ``scale_dispatch`` also scales in-service generator setpoints by the same
    factor.  Without it the DC slack bus absorbs the entire demand swing at a
    single bus, which distorts corridor flows.  This is a screening choice, it
    is not unit commitment, and it is reported on every sample.
    """
    hourly = copy.deepcopy(net)
    hourly.load.loc[:, "p_mw"] = hourly.load.p_mw * float(point.scale)
    if scale_dispatch and not hourly.gen.empty:
        active = hourly.gen.index[hourly.gen.in_service]
        hourly.gen.loc[active, "p_mw"] = hourly.gen.loc[active, "p_mw"] * float(
            point.scale
        )
    return hourly


def demand_provenance(
    point: HourPoint, *, ba_code: str, scale_dispatch: bool
) -> dict[str, Any]:
    """Describe exactly how this hour's demand was produced."""
    return {
        "hour": point.hour,
        "ts": point.ts,
        "ba_code": ba_code,
        "observed_demand_mw": point.demand_mw,
        "scale": point.scale,
        "band": point.band,
        "basis": "ba_load_hourly demand divided by the first observed hour of the series",
        "per_bus_ba_code": "unavailable",
        "scope": "one system-wide factor applied to every synthetic load",
        "dispatch_scaling": (
            "in-service generator setpoints scaled by the same factor; DC slack absorbs the residual"
            if scale_dispatch
            else "generator setpoints unscaled; DC slack absorbs the whole demand swing"
        ),
    }

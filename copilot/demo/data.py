"""Read-only weather timeline and experimental forecast surfaces for ControlRoom."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import Literal

import duckdb
from fastapi import APIRouter, Query

from copilot.demo.jepa import DEFAULT_JEPA_ARTIFACT, read_experimental_jepa_forecast


def create_demo_data_router(
    *, duckdb_path: Path, jepa_artifact_path: Path = DEFAULT_JEPA_ARTIFACT
) -> APIRouter:
    """Create opt-in `/demo` read routes; callers must pass local artifacts."""

    router = APIRouter(prefix="/demo", tags=["demo"])

    @router.get("/brief")
    async def brief(
        region: Literal["tx", "mn"] = "tx",
        scenario_id: Literal["uri_2021", "beryl_2024"] = "uri_2021",
    ) -> dict[str, object]:
        if region == "mn":
            return {
                "regions": [
                    {"id": "mn", "mode": "aggregate", "availability": "unavailable"}
                ],
                "scenarios": [],
                "topology": None,
                "limitations": [
                    "Minnesota has no topology-backed cascade in this demo."
                ],
            }
        scenario, weather = _weather_timeline(duckdb_path, scenario_id)
        return {
            "regions": [{"id": "tx", "mode": "synthetic", "availability": "available"}],
            "scenarios": [{**scenario, "weather": weather}],
            "topology": {
                "label": "synthetic (ACTIVSg2000)",
                "mode": "synthetic",
                "availability": "available",
                "provenance": ["ACTIVSg2000 MATPOWER case", "current AUX coordinates"],
            },
            "limitations": [
                "Synthetic topology is separate from the physical asset inventory."
            ],
        }

    @router.get("/forecast")
    async def forecast(
        county_fips: str | None = Query(default=None, pattern=r"^\d{5}$"),
    ) -> dict[str, object]:
        return read_experimental_jepa_forecast(
            jepa_artifact_path, county_fips=county_fips
        ).model_dump(mode="json")

    return router


def _weather_timeline(
    path: Path, scenario_id: str
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if not path.is_file():
        return ({"scenario_id": scenario_id, "availability": "unavailable"}, [])
    con = duckdb.connect(str(path), read_only=True)
    try:
        scenario = con.execute(
            "SELECT scenario_id, name, kind, ts_start, ts_end, source_name, source_ref, source_version "
            "FROM scenarios WHERE scenario_id = ?",
            [scenario_id],
        ).fetchone()
        if scenario is None:
            return ({"scenario_id": scenario_id, "availability": "unavailable"}, [])
        rows = con.execute(
            "SELECT ts, avg(wind_ms), avg(gust_ms), avg(temp_c), avg(ice_mm), avg(precip_mm), "
            "min(source_name), min(source_ref), min(source_version) FROM weather_hourly "
            "WHERE ts >= ? AND ts <= ? GROUP BY ts ORDER BY ts",
            [scenario[3], scenario[4]],
        ).fetchall()
    finally:
        con.close()
    frames = [_frame(row) for row in rows]
    return (
        {
            "scenario_id": scenario[0],
            "name": scenario[1],
            "kind": scenario[2],
            "ts_start": _ts(scenario[3]),
            "ts_end": _ts(scenario[4]),
            "provenance": [f"{scenario[5]}:{scenario[6]}", str(scenario[7])],
        },
        frames,
    )


def _frame(row: tuple[object, ...]) -> dict[str, object]:
    ts, wind, gust, temp, ice, precip, source, ref, version = row
    condition, label = _condition(float(temp), float(gust), float(ice), float(precip))
    return {
        "ts": _ts(ts),
        "condition": condition,
        "label": label,
        "observed_or_forecast": "modeled",
        "wind_ms": wind,
        "gust_ms": gust,
        "temp_c": temp,
        "ice_mm": ice,
        "precip_mm": precip,
        "provenance": [f"{source}:{ref}", str(version)],
        "rule": "ice>0=snow; precip>=2=rain; gust>=15=wind; temp<=0=cold; temp>=32=heat; else=cloudy",
    }


def _condition(temp: float, gust: float, ice: float, precip: float) -> tuple[str, str]:
    if ice > 0:
        return "snow", "Frozen precipitation"
    if precip >= 2:
        return "rain", "Precipitation"
    if gust >= 15:
        return "wind", "Wind"
    if temp <= 0:
        return "cold", "Cold"
    if temp >= 32:
        return "heat", "Heat"
    return "cloudy", "Cloud cover / no threshold condition"


def _ts(value: object) -> str:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")

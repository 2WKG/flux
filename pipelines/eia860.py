"""Version-pinned PUDL EIA-860 loader and transparent candidate seeding."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from shapely import wkb
from shapely.geometry import Point

from pipelines.db import log_artifact, replace_frame


def _first(frame: pd.DataFrame, *names: str) -> pd.Series:
    for name in names:
        if name in frame:
            return frame[name]
    return pd.Series(pd.NA, index=frame.index)


def _fuel_mode(values: pd.Series) -> object:
    values = values.dropna()
    return values.mode().iat[0] if not values.empty else pd.NA


def _latest_generator_reports(inventory: pd.DataFrame) -> pd.DataFrame:
    """Return the latest report for each EIA plant/generator unit.

    The inventory table deliberately keeps the complete annual history.  Plant
    summaries, however, describe one point in time and must not add capacity
    from successive reports of the same unit.
    """
    return (
        inventory.sort_values(["plant_id_eia", "generator_id", "report_date"], kind="stable")
        .drop_duplicates(["plant_id_eia", "generator_id"], keep="last")
    )


def _candidate_locations(con, candidates: pd.DataFrame, min_kv: float = 138.0,
                         max_bus_km: float = 40.0) -> pd.DataFrame:
    """Assign county containment and the nearest qualifying synthetic bus.

    Candidate coordinates are real EIA plant locations while the bus topology is
    synthetic, so the assignment stays explicitly geometric.  A location beyond
    the siting contract's 40 km radius remains unconnected instead of receiving
    a misleading statewide nearest-bus match.
    """
    result = candidates.copy()
    counties = con.execute("SELECT county_fips, geom_wkb FROM counties").fetchall()
    county_geometries = [(fips, wkb.loads(bytes(geometry))) for fips, geometry in counties
                         if geometry is not None]
    result["county_fips"] = [
        next((fips for fips, geometry in county_geometries if geometry.covers(Point(lon, lat))), None)
        for lon, lat in zip(result.lon, result.lat, strict=True)
    ]

    buses = con.execute("""SELECT bus_id, lon, lat FROM buses
        WHERE base_kv >= ? AND lon IS NOT NULL AND lat IS NOT NULL""", [min_kv]).fetchdf()
    assigned: list[int | None] = []
    if buses.empty:
        assigned = [None] * len(result)
    else:
        bus_lat = np.radians(buses.lat.to_numpy())
        bus_lon = np.radians(buses.lon.to_numpy())
        for lon, lat in zip(result.lon, result.lat, strict=True):
            candidate_lat, candidate_lon = np.radians([lat, lon])
            haversine = np.sin((bus_lat - candidate_lat) / 2) ** 2
            haversine += np.cos(candidate_lat) * np.cos(bus_lat) * np.sin((bus_lon - candidate_lon) / 2) ** 2
            distance_km = 2 * 6371.0088 * np.arcsin(np.sqrt(haversine))
            nearest_index = int(np.argmin(distance_km))
            assigned.append(int(buses.iloc[nearest_index].bus_id)
                            if distance_km[nearest_index] <= max_bus_km else None)
    result["bus_id"] = pd.array(assigned, dtype="Int64")
    return result


def load_eia860_plants(con, plants_parquet: str, generators_parquet: str, release: str = "v2026.2.0") -> int:
    plants_path, generators_path = Path(plants_parquet), Path(generators_parquet)
    plants = pd.read_parquet(plants_path)
    generators = pd.read_parquet(generators_path)
    for column in ("plant_id_eia", "report_date", "latitude", "longitude", "state"):
        if column not in plants:
            raise ValueError(f"PUDL plants output lacks required column {column}")
    for column in ("plant_id_eia", "generator_id", "report_date", "capacity_mw"):
        if column not in generators:
            raise ValueError(f"PUDL generators output lacks required column {column}")
    generators = generators.copy()
    generators["report_date"] = pd.to_datetime(generators["report_date"], errors="coerce").dt.date
    generators["capacity_mw"] = pd.to_numeric(generators["capacity_mw"], errors="coerce")
    generators["fuel_type_code_pudl"] = _first(generators, "fuel_type_code_pudl")
    generators["retirement_date"] = pd.to_datetime(_first(generators, "generator_retirement_date"), errors="coerce").dt.date
    generators["planned_retirement_date"] = pd.to_datetime(
        _first(generators, "planned_generator_retirement_date"), errors="coerce").dt.date
    inventory = pd.DataFrame({
        "plant_id_eia": generators["plant_id_eia"], "generator_id": generators["generator_id"].astype(str),
        "report_date": generators["report_date"], "capacity_mw": generators["capacity_mw"],
        "prime_mover_code": _first(generators, "prime_mover_code"),
        "energy_source_code_1": _first(generators, "energy_source_code_1"),
        "fuel_type_code_pudl": generators["fuel_type_code_pudl"],
        "operational_status": _first(generators, "operational_status"),
        "retirement_date": generators["retirement_date"], "planned_retirement_date": generators["planned_retirement_date"],
    }).dropna(subset=["plant_id_eia", "generator_id", "report_date"])
    replace_frame(con, "eia_generator_inventory", inventory, where="TRUE")

    plant_dates = plants.copy()
    plant_dates["report_date"] = pd.to_datetime(plant_dates["report_date"], errors="coerce")
    latest = plant_dates.sort_values("report_date").groupby("plant_id_eia", as_index=False).tail(1)
    latest_gen = _latest_generator_reports(inventory).groupby("plant_id_eia")
    aggregate = latest_gen.agg(capacity_mw=("capacity_mw", "sum"), primary_fuel=("fuel_type_code_pudl", _fuel_mode),
                               retirement_year=("retirement_date", lambda values: pd.to_datetime(values, errors="coerce").dt.year.min()),
                               planned_retirement_year=("planned_retirement_date", lambda values: pd.to_datetime(values, errors="coerce").dt.year.min()),
                               operational_status=("operational_status", lambda values: values.dropna().mode().iat[0] if not values.dropna().empty else pd.NA))
    curated = latest.merge(aggregate, on="plant_id_eia", how="left")
    curated = curated[curated["state"].eq("TX")].copy()
    curated["retirement_year"] = curated["retirement_year"].combine_first(curated["planned_retirement_year"])
    plant_frame = pd.DataFrame({
        "plant_id_eia": curated["plant_id_eia"].astype(int), "plant_name": _first(curated, "plant_name_eia").astype(str),
        "lon": pd.to_numeric(curated["longitude"], errors="coerce"), "lat": pd.to_numeric(curated["latitude"], errors="coerce"),
        "state": curated["state"], "county_fips": None, "capacity_mw": curated["capacity_mw"],
        "primary_fuel": curated["primary_fuel"], "retirement_year": curated["retirement_year"].astype("Int64"),
        "operational_status": curated["operational_status"], "report_date": pd.to_datetime(curated["report_date"]).dt.date,
    }).dropna(subset=["lon", "lat"])
    rows = replace_frame(con, "eia_plants", plant_frame, where="state = 'TX'")
    log_artifact(con, source="pudl_eia860", source_release=release, path=plants_path, rows_loaded=rows,
                 schema_fingerprint="out_eia__yearly_plants version-pinned")
    log_artifact(con, source="pudl_eia860", source_release=release, path=generators_path, rows_loaded=len(inventory),
                 schema_fingerprint="out_eia__yearly_generators version-pinned")
    return rows


def seed_site_candidates(con, capacity_slot_mw: float = 300.0) -> int:
    """Seed only documented coal/nuclear candidate classes from EIA inventory."""
    plants = con.execute("SELECT * FROM eia_plants WHERE state = 'TX'").fetchdf()
    inventory = con.execute("SELECT * FROM eia_generator_inventory").fetchdf()
    latest_units = _latest_generator_reports(inventory)
    latest_units["fuel_type_code_pudl"] = latest_units["fuel_type_code_pudl"].astype("string").str.lower()
    latest_units["operational_status"] = latest_units["operational_status"].astype("string").str.lower()

    # A coal site is a brownfield candidate only when all coal units are retired
    # or an operating unit has a documented near-term retirement plan.  The old
    # plant-level fallback labeled every active coal plant with no date as
    # ``coal_retired``.
    coal_units = latest_units[latest_units["fuel_type_code_pudl"].eq("coal")].copy()
    coal_units["is_retired"] = coal_units["operational_status"].eq("retired")
    coal_units["has_near_term_plan"] = (
        pd.to_datetime(coal_units["planned_retirement_date"], errors="coerce").dt.year.le(2032)
    )
    coal_summary = coal_units.groupby("plant_id_eia", as_index=False).agg(
        all_coal_units_retired=("is_retired", "all"),
        has_near_term_plan=("has_near_term_plan", "any"),
    )
    coal_summary["kind"] = np.select(
        [coal_summary["all_coal_units_retired"], coal_summary["has_near_term_plan"]],
        ["coal_retired", "coal_retiring"],
        default=None,
    )
    coal_candidates = coal_summary.dropna(subset=["kind"])[["plant_id_eia", "kind"]]

    nuclear_candidates = plants[plants.primary_fuel.eq("nuclear")][["plant_id_eia"]].copy()
    nuclear_candidates["kind"] = "nuclear_existing"
    candidate_kinds = pd.concat([coal_candidates, nuclear_candidates], ignore_index=True)
    selected = plants.merge(candidate_kinds, on="plant_id_eia", how="inner")
    selected = selected.sort_values("plant_id_eia").reset_index(drop=True)
    selected["site_id"] = np.arange(1, len(selected) + 1)
    candidates = selected.rename(columns={"plant_name": "name"})[
        ["site_id", "name", "kind", "lon", "lat", "county_fips"]
    ]
    candidates = _candidate_locations(con, candidates)
    candidates["capacity_slot_mw"] = capacity_slot_mw
    return replace_frame(con, "site_candidates", candidates, where="kind IN ('coal_retired', 'coal_retiring', 'nuclear_existing')")

"""Version-pinned PUDL EIA-860 loader and transparent candidate seeding."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from shapely import Point, from_wkb

from pipelines.db import log_artifact, replace_frame
from pipelines.state_scope import scope


def _state_where(states) -> str:
    return "state IN (" + ", ".join(repr(code) for code in states.usps) + ")"


def _scope_plants(frame: pd.DataFrame, states=None) -> pd.DataFrame:
    """Select only explicitly requested plant states."""
    return frame[frame["state"].isin(scope(states).usps)].copy()


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


def _county_fips_for_points(con, lon: pd.Series, lat: pd.Series) -> list[str | None]:
    """Assign EIA plant points to the already-loaded canonical county geography."""
    counties = con.execute("SELECT county_fips, geom_wkb FROM counties").fetchall()
    shapes = [(county_fips, from_wkb(bytes(geom_wkb))) for county_fips, geom_wkb in counties]
    return [next((fips for fips, shape in shapes if shape.covers(Point(x, y))), None)
            for x, y in zip(lon, lat, strict=True)]


def _candidate_bus_ids(con, candidates: pd.DataFrame, min_kv: float = 230.0) -> pd.Series:
    """Attach candidates only to high-voltage buses in the same canonical county.

    The topology is synthetic, so an EIA point is never associated by a
    cross-region nearest-neighbour fallback.  A missing same-county bus remains
    explicitly unconnected for downstream scoring.
    """
    buses = con.execute(
        "SELECT bus_id, county_fips, base_kv, lon, lat FROM buses "
        "WHERE base_kv >= ? AND county_fips IS NOT NULL AND lon IS NOT NULL AND lat IS NOT NULL",
        [min_kv],
    ).fetchdf()
    assignments: list[int | None] = []
    for row in candidates.itertuples():
        if pd.isna(row.county_fips):
            assignments.append(None)
            continue
        pool = buses[buses.county_fips.eq(row.county_fips)].copy()
        if pool.empty:
            assignments.append(None)
            continue
        # Exact county equality is the topology-region guard.  Sorting makes
        # coincident/equidistant bus points deterministic across input order.
        distance_sq = (pool.lon - row.lon) ** 2 + (pool.lat - row.lat) ** 2
        pool = pool.assign(_distance_sq=distance_sq).sort_values(["_distance_sq", "bus_id"], kind="stable")
        assignments.append(int(pool.iloc[0].bus_id))
    return pd.Series(assignments, index=candidates.index, dtype="Int64")


def load_eia860_plants(con, plants_parquet: str, generators_parquet: str, release: str = "v2026.2.0", states=None) -> int:
    selected_scope = scope(states)
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
    curated = _scope_plants(curated, selected_scope)
    curated["retirement_year"] = curated["retirement_year"].combine_first(curated["planned_retirement_year"])
    plant_frame = pd.DataFrame({
        "plant_id_eia": curated["plant_id_eia"].astype(int), "plant_name": _first(curated, "plant_name_eia").astype(str),
        "lon": pd.to_numeric(curated["longitude"], errors="coerce"), "lat": pd.to_numeric(curated["latitude"], errors="coerce"),
        "state": curated["state"], "county_fips": _county_fips_for_points(con, curated["longitude"], curated["latitude"]),
        "capacity_mw": curated["capacity_mw"],
        "primary_fuel": curated["primary_fuel"], "retirement_year": curated["retirement_year"].astype("Int64"),
        "operational_status": curated["operational_status"], "report_date": pd.to_datetime(curated["report_date"]).dt.date,
    }).dropna(subset=["lon", "lat"])
    rows = replace_frame(con, "eia_plants", plant_frame, where=_state_where(selected_scope))
    log_artifact(con, source="pudl_eia860", source_release=release, path=plants_path, rows_loaded=rows,
                 schema_fingerprint="out_eia__yearly_plants version-pinned")
    log_artifact(con, source="pudl_eia860", source_release=release, path=generators_path, rows_loaded=len(inventory),
                 schema_fingerprint="out_eia__yearly_generators version-pinned")
    return rows


def seed_site_candidates(con, states=None) -> int:
    """Seed only documented coal/nuclear candidate classes from EIA inventory."""
    selected_scope = scope(states)
    plants = con.execute(f"SELECT * FROM eia_plants WHERE {_state_where(selected_scope)}").fetchdf()
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
    selected = selected.dropna(subset=["county_fips", "capacity_mw"])
    selected = selected[selected["capacity_mw"] > 0].copy()
    selected = selected.sort_values("plant_id_eia", kind="stable").drop_duplicates("plant_id_eia", keep="first")
    # EIA plant IDs are immutable source identities; using them avoids release-
    # order renumbering while source_site_id retains the namespace explicitly.
    selected["site_id"] = selected["plant_id_eia"].astype("int64")
    candidates = selected.rename(columns={"plant_name": "name"})[
        ["site_id", "name", "kind", "lon", "lat", "county_fips"]
    ]
    candidates["bus_id"] = _candidate_bus_ids(con, candidates)
    candidates["capacity_slot_mw"] = selected["capacity_mw"].to_numpy()
    candidates["source_site_id"] = "eia_plant:" + selected["plant_id_eia"].astype(str).to_numpy()
    return replace_frame(con, "site_candidates", candidates, where="kind IN ('coal_retired', 'coal_retiring', 'nuclear_existing')",
                         source_name="pudl_eia860", source_ref="eia_plants", source_version="v2026.2.0",
                         fixture_batch_id="p0-eia860-v2026.2.0")

from __future__ import annotations

import pandas as pd
from shapely.geometry import Polygon

from pipelines.db import connect
from pipelines.eia860 import load_eia860_plants, seed_site_candidates


def _write_eia_parquet(tmp_path, plants: list[dict], generators: list[dict]) -> tuple[str, str]:
    plants_path = tmp_path / "plants.parquet"
    generators_path = tmp_path / "generators.parquet"
    pd.DataFrame(plants).to_parquet(plants_path)
    pd.DataFrame(generators).to_parquet(generators_path)
    return str(plants_path), str(generators_path)


def test_eia_plants_uses_latest_report_per_generator_and_keeps_inventory_history(tmp_path):
    plants_path, generators_path = _write_eia_parquet(
        tmp_path,
        [
            {"plant_id_eia": 1, "report_date": "2024-01-01", "latitude": 30.0, "longitude": -97.0,
             "state": "TX", "plant_name_eia": "Example"},
            {"plant_id_eia": 1, "report_date": "2025-01-01", "latitude": 30.1, "longitude": -97.1,
             "state": "TX", "plant_name_eia": "Example"},
        ],
        [
            {"plant_id_eia": 1, "generator_id": "A", "report_date": "2024-01-01", "capacity_mw": 100,
             "fuel_type_code_pudl": "coal", "operational_status": "operating"},
            {"plant_id_eia": 1, "generator_id": "A", "report_date": "2025-01-01", "capacity_mw": 120,
             "fuel_type_code_pudl": "coal", "operational_status": "operating"},
            {"plant_id_eia": 1, "generator_id": "B", "report_date": "2024-01-01", "capacity_mw": 50,
             "fuel_type_code_pudl": "coal", "operational_status": "retired"},
        ],
    )
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        load_eia860_plants(con, plants_path, generators_path)
        assert con.execute("SELECT count(*) FROM eia_generator_inventory").fetchone()[0] == 3
        assert con.execute("SELECT capacity_mw FROM eia_plants WHERE plant_id_eia = 1").fetchone()[0] == 170
    finally:
        con.close()


def test_site_candidates_exclude_active_coal_and_classify_retired_and_retiring_sites(tmp_path):
    plants = [
        {"plant_id_eia": plant_id, "report_date": "2025-01-01", "latitude": 30.0 + plant_id / 100,
         "longitude": -97.0 - plant_id / 100, "state": "TX", "plant_name_eia": name}
        for plant_id, name in ((1, "Active coal"), (2, "Retired coal"), (3, "Retiring coal"), (4, "Nuclear"))
    ]
    generators = [
        {"plant_id_eia": 1, "generator_id": "A", "report_date": "2025-01-01", "capacity_mw": 100,
         "fuel_type_code_pudl": "coal", "operational_status": "operating"},
        {"plant_id_eia": 2, "generator_id": "A", "report_date": "2025-01-01", "capacity_mw": 100,
         "fuel_type_code_pudl": "coal", "operational_status": "retired", "generator_retirement_date": "2021-06-01"},
        {"plant_id_eia": 2, "generator_id": "B", "report_date": "2025-01-01", "capacity_mw": 100,
         "fuel_type_code_pudl": "coal", "operational_status": "retired", "generator_retirement_date": "2021-06-01"},
        {"plant_id_eia": 3, "generator_id": "A", "report_date": "2025-01-01", "capacity_mw": 100,
         "fuel_type_code_pudl": "coal", "operational_status": "operating",
         "planned_generator_retirement_date": "2030-01-01"},
        {"plant_id_eia": 4, "generator_id": "A", "report_date": "2025-01-01", "capacity_mw": 100,
         "fuel_type_code_pudl": "nuclear", "operational_status": "operating"},
    ]
    plants_path, generators_path = _write_eia_parquet(tmp_path, plants, generators)
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        load_eia860_plants(con, plants_path, generators_path)
        con.execute("INSERT INTO counties VALUES (?, ?, ?, ?, ?)", [
            "48001", "Example", "TX", 1,
            Polygon([(-98, 29), (-96, 29), (-96, 31), (-98, 31), (-98, 29)]).wkb,
        ])
        con.execute("INSERT INTO buses (bus_id, base_kv, lon, lat) VALUES (1, 161, -97, 30)")
        con.execute("INSERT INTO buses (bus_id, base_kv, lon, lat) VALUES (2, 115, -97, 30)")
        seed_site_candidates(con)
        assert con.execute("SELECT name, kind FROM site_candidates ORDER BY name").fetchall() == [
            ("Nuclear", "nuclear_existing"),
            ("Retired coal", "coal_retired"),
            ("Retiring coal", "coal_retiring"),
        ]
        assert con.execute(
            "SELECT DISTINCT county_fips, bus_id FROM site_candidates"
        ).fetchall() == [("48001", 1)]
    finally:
        con.close()

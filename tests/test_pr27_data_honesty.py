from __future__ import annotations

import json

import pandas as pd
from shapely.geometry import Polygon

from pipelines.critical_loads import load_dod
from pipelines.db import connect, replace_frame
from pipelines.eia860 import load_eia860_plants, seed_site_candidates
from pipelines.joins import join_bus_county


def _county_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {"county_fips": "48001", "name": "One", "state": "TX", "pop": 1,
         "geom_wkb": Polygon([(-99, 29), (-97, 29), (-97, 31), (-99, 31)]).wkb},
        {"county_fips": "48003", "name": "Three", "state": "TX", "pop": 1,
         "geom_wkb": Polygon([(-97, 29), (-95, 29), (-95, 31), (-97, 31)]).wkb},
        {"county_fips": "27001", "name": "Minnesota", "state": "MN", "pop": 1,
         "geom_wkb": Polygon([(-94, 44), (-93, 44), (-93, 45), (-94, 45)]).wkb},
    ])


def test_bus_county_ties_choose_lowest_county_fips_independent_of_county_order(tmp_path):
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        counties = _county_frame()
        replace_frame(con, "counties", counties.iloc[::-1], source_name="test", source_ref="counties", fixture_batch_id="test")
        replace_frame(con, "buses", pd.DataFrame([{"bus_id": 1, "name": "boundary", "base_kv": 230,
            "lon": -97.0, "lat": 30.0, "county_fips": None, "ba_code": None, "coord_source": "fixture",
            "zone": None, "area": None}]), source_name="test", source_ref="buses", fixture_batch_id="test")
        assert join_bus_county(con) == 1
        assert con.execute("SELECT county_fips FROM buses WHERE bus_id = 1").fetchone() == ("48001",)
    finally:
        con.close()


def test_eia_candidates_are_source_stable_and_only_attach_to_same_county_high_voltage_bus(tmp_path):
    plants = pd.DataFrame([{"plant_id_eia": 10, "report_date": "2025-01-01", "latitude": 30.0,
                            "longitude": -98.0, "state": "TX", "plant_name_eia": "Retired"}])
    generators = pd.DataFrame([{"plant_id_eia": 10, "generator_id": "A", "report_date": "2025-01-01",
                                "capacity_mw": 725.0, "fuel_type_code_pudl": "coal", "operational_status": "retired"}])
    plants_path, generators_path = tmp_path / "plants.parquet", tmp_path / "generators.parquet"
    plants.to_parquet(plants_path)
    generators.to_parquet(generators_path)
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        replace_frame(con, "counties", _county_frame(), source_name="test", source_ref="counties", fixture_batch_id="test")
        replace_frame(con, "buses", pd.DataFrame([
            {"bus_id": 2, "name": "TX", "base_kv": 230, "lon": -98.1, "lat": 30.0, "county_fips": "48001", "ba_code": None, "coord_source": "fixture", "zone": None, "area": None},
            {"bus_id": 3, "name": "low", "base_kv": 115, "lon": -98.0, "lat": 30.0, "county_fips": "48001", "ba_code": None, "coord_source": "fixture", "zone": None, "area": None},
            {"bus_id": 4, "name": "other", "base_kv": 500, "lon": -98.0, "lat": 30.0, "county_fips": "27001", "ba_code": None, "coord_source": "fixture", "zone": None, "area": None},
        ]), source_name="test", source_ref="buses", fixture_batch_id="test")
        load_eia860_plants(con, str(plants_path), str(generators_path))
        assert seed_site_candidates(con) == 1
        first = con.execute("SELECT site_id, kind, bus_id, capacity_slot_mw, source_site_id FROM site_candidates").fetchall()
        plants.iloc[::-1].to_parquet(plants_path)
        generators.iloc[::-1].to_parquet(generators_path)
        load_eia860_plants(con, str(plants_path), str(generators_path))
        seed_site_candidates(con)
        second = con.execute("SELECT site_id, kind, bus_id, capacity_slot_mw, source_site_id FROM site_candidates").fetchall()
    finally:
        con.close()
    assert first == second == [(10, "coal_retired", 2, 725.0, "eia_plant:10")]


def test_dod_ids_and_geometry_replacement_are_stable_and_do_not_delete_other_sources(tmp_path):
    polygon = Polygon([(-98.2, 29.8), (-97.8, 29.8), (-97.8, 30.2), (-98.2, 30.2)])
    feature = {"type": "Feature", "properties": {"mirtaLocationsIdpk": 77, "featureName": "Fixture Base",
        "stateNameCode": "TX", "siteOperationalStatus": "act", "siteName": "Fixture Base",
        "siteReportingComponent": "usa", "isJointBase": False},
        "geometry": {"type": "Polygon", "coordinates": [list(polygon.exterior.coords)]}}
    geojson = tmp_path / "dod.geojson"
    geojson.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        replace_frame(con, "counties", _county_frame(), source_name="test", source_ref="counties", fixture_batch_id="test")
        con.execute("CREATE TABLE critical_load_geometry(cl_id INTEGER PRIMARY KEY, source_id TEXT, reporting_component TEXT, operational_status TEXT, is_joint_base BOOLEAN, area_km2 DOUBLE, geom_wkb BLOB)")
        con.execute("INSERT INTO critical_load_geometry VALUES (999, 'hospital:stable', NULL, NULL, NULL, NULL, NULL)")
        assert load_dod(con, str(geojson), min_area_km2=1) == 1
        first = con.execute("SELECT cl_id FROM critical_loads WHERE kind = 'dod'").fetchone()[0]
        assert load_dod(con, str(geojson), min_area_km2=1) == 1
        assert con.execute("SELECT cl_id FROM critical_loads WHERE kind = 'dod'").fetchone()[0] == first
        assert con.execute("SELECT source_id FROM critical_load_geometry WHERE cl_id = 999").fetchone() == ("hospital:stable",)
        assert con.execute("SELECT source_id FROM critical_load_geometry WHERE cl_id = ?", [first]).fetchone() == ("mirtaLocationsIdpk:77",)
    finally:
        con.close()

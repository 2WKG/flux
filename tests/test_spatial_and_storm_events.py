from __future__ import annotations

import json

import pandas as pd
import pytest
from shapely.geometry import Polygon

from pipelines.critical_loads import load_dod
from pipelines.db import connect
from pipelines.joins import join_critical_loads_to_bus
from pipelines.storm_events import _cz_timezone, load_storm_events


def test_storm_events_uses_each_rows_cz_timezone(tmp_path):
    details = tmp_path / "details.csv.gz"
    pd.DataFrame([
        {"EVENT_ID": 1, "STATE": "TEXAS", "STATE_FIPS": 48, "CZ_TYPE": "C", "CZ_FIPS": 1,
         "CZ_TIMEZONE": "CST-6", "BEGIN_DATE_TIME": "2021-07-01 12:00:00",
         "END_DATE_TIME": "2021-07-01 13:00:00", "EVENT_TYPE": "High Wind", "MAGNITUDE": 50},
        {"EVENT_ID": 2, "STATE": "TEXAS", "STATE_FIPS": 48, "CZ_TYPE": "C", "CZ_FIPS": 3,
         "CZ_TIMEZONE": "MST-7", "BEGIN_DATE_TIME": "2021-07-01 12:00:00",
         "END_DATE_TIME": "2021-07-01 13:00:00", "EVENT_TYPE": "High Wind", "MAGNITUDE": 50},
    ]).to_csv(details, index=False, compression="gzip")
    crosswalk = tmp_path / "zones.dbx"
    crosswalk.write_text("TX|001|XXX|Example||Example|48001|CST-6\n")
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        assert load_storm_events(con, str(details), str(crosswalk), 2021) == 2
        observed = con.execute("SELECT event_id, ts_begin FROM storm_events ORDER BY event_id").fetchall()
    finally:
        con.close()
    assert observed == [(1, pd.Timestamp("2021-07-01 18:00:00")),
                        (2, pd.Timestamp("2021-07-01 19:00:00"))]


def test_storm_events_rejects_undocumented_timezone():
    with pytest.raises(ValueError, match="unsupported Storm Events CZ_TIMEZONE"):
        _cz_timezone("CDT-5")


def test_dod_county_assignment_prevents_cross_county_bus_matches(tmp_path):
    county = Polygon([(-98, 30), (-96, 30), (-96, 32), (-98, 32), (-98, 30)])
    dod_inside = Polygon([(-97.2, 30.5), (-97.0, 30.5), (-97.0, 30.7), (-97.2, 30.7), (-97.2, 30.5)])
    dod_outside = Polygon([(-100.2, 30.5), (-100.0, 30.5), (-100.0, 30.7), (-100.2, 30.7), (-100.2, 30.5)])
    geojson = tmp_path / "dod.geojson"
    geojson.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"stateNameCode": "TX", "siteOperationalStatus": "act",
          "siteName": "Inside", "siteReportingComponent": "Army", "isJointBase": False},
         "geometry": {"type": "Polygon", "coordinates": [list(dod_inside.exterior.coords)]}},
        {"type": "Feature", "properties": {"stateNameCode": "TX", "siteOperationalStatus": "act",
          "siteName": "Outside", "siteReportingComponent": "Army", "isJointBase": False},
         "geometry": {"type": "Polygon", "coordinates": [list(dod_outside.exterior.coords)]}},
    ]}))
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        con.execute("INSERT INTO counties VALUES (?, ?, ?, ?, ?)", ["48001", "Example", "TX", 1, county.wkb])
        con.execute("INSERT INTO buses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [1, "same county", 115.0, -97.1, 30.6, "48001", None, None, None, None])
        assert load_dod(con, str(geojson), min_area_km2=1) == 2
        assert con.execute("SELECT county_fips FROM critical_loads WHERE name = 'Inside'").fetchone() == ("48001",)
        assert con.execute("SELECT county_fips FROM critical_loads WHERE name = 'Outside'").fetchone() == (None,)
        # A known county without a qualifying bus must not fall back to a bus in a different county.
        con.execute("INSERT INTO critical_loads VALUES (3, 'hospital', 'No local bus', -95, 30.5, NULL, '48003')")
        assert join_critical_loads_to_bus(con) == 1
        assignments = con.execute(
            "SELECT name, bus_id FROM critical_loads ORDER BY cl_id"
        ).fetchall()
        methods = con.execute(
            "SELECT cl_id, bus_id, match_method FROM critical_load_bus_dist ORDER BY cl_id"
        ).fetchall()
    finally:
        con.close()
    assert assignments == [("Inside", 1), ("Outside", None), ("No local bus", None)]
    assert methods == [(1, 1, "same_county"), (2, None, "unassigned_no_county"),
                       (3, None, "unassigned_no_eligible_bus")]

from __future__ import annotations

import json

import pandas as pd
import pytest
from shapely.geometry import Polygon

from pipelines.checks import run_checks
from pipelines.critical_loads import load_dod
from pipelines.joins import join_critical_loads_to_bus
from pipelines.storm_events import _cz_timezone, load_storm_events
from pipelines.texas_db import connect


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


def test_storm_events_warns_when_a_zone_has_no_county_crosswalk(tmp_path):
    details = tmp_path / "details.csv.gz"
    pd.DataFrame([
        {"EVENT_ID": 1, "STATE": "TEXAS", "STATE_FIPS": 48, "CZ_TYPE": "C", "CZ_FIPS": 1,
         "CZ_TIMEZONE": "CST-6", "BEGIN_DATE_TIME": "2021-02-15 12:00:00",
         "END_DATE_TIME": "2021-02-15 13:00:00", "EVENT_TYPE": "Winter Storm"},
        {"EVENT_ID": 2, "STATE": "TEXAS", "STATE_FIPS": 48, "CZ_TYPE": "Z", "CZ_FIPS": 999,
         "CZ_TIMEZONE": "CST-6", "BEGIN_DATE_TIME": "2021-02-15 12:00:00",
         "END_DATE_TIME": "2021-02-15 13:00:00", "EVENT_TYPE": "Winter Storm"},
    ]).to_csv(details, index=False, compression="gzip")
    crosswalk = tmp_path / "zones.dbx"
    crosswalk.write_text("TX|001|XXX|Example||Example|48001|CST-6\n")
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        assert load_storm_events(con, str(details), str(crosswalk), 2021) == 1
        assert con.execute(
            "SELECT source_key, warning FROM ingest_warnings WHERE source = 'noaa_storm_events'"
        ).fetchall() == [
            ("2021:zone:999", "1 Texas zone-type Storm Events had no county crosswalk mapping"),
        ]
        # A corrected crosswalk removes the previous warning on rerun.
        crosswalk.write_text(
            "TX|001|XXX|Example||Example|48001|CST-6\n"
            "TX|999|XXX|Example||Example|48999|CST-6\n"
        )
        assert load_storm_events(con, str(details), str(crosswalk), 2021) == 2
        assert con.execute(
            "SELECT count(*) FROM ingest_warnings WHERE source = 'noaa_storm_events'"
        ).fetchone() == (0,)
    finally:
        con.close()


def test_quality_checks_cover_every_p0_curated_output(tmp_path):
    db_path = tmp_path / "grid.duckdb"
    con = connect(str(db_path))
    try:
        con.execute("""INSERT INTO buses (bus_id, name, base_kv, lon, lat, county_fips, coord_source)
            SELECT id, 'bus-' || id, 230, -97, 31, '48001', 'tamu_aux'
            FROM range(1, 2001) AS rows(id)""")
        con.execute("""INSERT INTO lines (line_id, is_transformer)
            SELECT id, id <= 847 FROM range(1, 3207) AS rows(id)""")
        con.execute("INSERT INTO gens (gen_id) SELECT id FROM range(1, 545) AS rows(id)")
        con.execute("INSERT INTO loads (load_id) SELECT id FROM range(1, 1126) AS rows(id)")
        con.execute("""INSERT INTO counties (county_fips, name, state)
            SELECT CAST(48000 + id AS VARCHAR), 'county-' || id, 'TX'
            FROM range(1, 255) AS rows(id)""")
        con.execute("""INSERT INTO hazard_static (county_fips, nri_score)
            SELECT county_fips, 1 FROM counties""")
        con.execute("""INSERT INTO eaglei_ingest_quality
            (source_year, source_file, source_timezone, raw_tx_rows, valid_rows,
             missing_customers, negative_customers, duplicate_keys, source_counties, loaded_at)
            VALUES (2021, '2021.csv', 'UTC', 1, 1, 0, 0, 0, 1, current_timestamp),
                   (2024, '2024.csv', 'UTC', 1, 1, 0, 0, 0, 1, current_timestamp)""")
        con.execute("""INSERT INTO ba_load_hourly
            SELECT 'ERCO', TIMESTAMP '2021-01-01 07:00:00' + id * INTERVAL 1 HOUR, 65000
            FROM range(0, 4343) AS rows(id)""")
        con.execute("""UPDATE ba_load_hourly SET demand_mw = 49000
            WHERE ba_code = 'ERCO' AND ts = TIMESTAMP '2021-02-15 18:00:00'""")
        con.execute("""INSERT INTO storm_events
            SELECT id, TIMESTAMP '2021-02-15 12:00:00', TIMESTAMP '2021-02-15 13:00:00',
                   '48001', 'Winter Storm', NULL
            FROM range(1, 151) AS rows(id)""")
        con.execute("""INSERT INTO critical_loads
            SELECT id, 'dod', CASE WHEN id = 1 THEN 'Fort Cavazos' ELSE 'base-' || id END,
                   -97, 31, 1, '48001'
            FROM range(1, 13) AS rows(id)""")
        con.execute("""INSERT INTO site_candidates
            SELECT id, 'candidate-' || id,
                   CASE WHEN id <= 15 THEN 'coal_retired' ELSE 'nuclear_existing' END,
                   -97, 31, '48001', 1, 300
            FROM range(1, 18) AS rows(id)""")
    finally:
        con.close()

    checks = {check.name: check for check in run_checks(str(db_path))}
    assert all(check.passed for check in checks.values())

    con = connect(str(db_path))
    try:
        con.execute("UPDATE lines SET is_transformer = FALSE")
    finally:
        con.close()
    checks = {check.name: check for check in run_checks(str(db_path))}
    assert not checks["synthetic-case-counts"].passed


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

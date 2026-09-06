from __future__ import annotations

import json
from datetime import datetime

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from pipelines.common import sha256_file
from pipelines.critical_loads import _ntad_source_ids, _unique_stable_ids, load_dod
from pipelines.db import connect, replace_frame
from pipelines.joins import join_critical_loads_to_bus
from pipelines.storm_events import NwsCrosswalkRelease, _cz_timezone, load_storm_events


def test_storm_events_uses_each_rows_cz_timezone(tmp_path):
    details = tmp_path / "details.csv.gz"
    pd.DataFrame(
        [
            {
                "EVENT_ID": 1,
                "STATE": "TEXAS",
                "STATE_FIPS": 48,
                "CZ_TYPE": "C",
                "CZ_FIPS": 1,
                "CZ_TIMEZONE": "CST-6",
                "BEGIN_DATE_TIME": "2021-07-01 12:00:00",
                "END_DATE_TIME": "2021-07-01 13:00:00",
                "EVENT_TYPE": "High Wind",
                "MAGNITUDE": 50,
            },
            {
                "EVENT_ID": 2,
                "STATE": "TEXAS",
                "STATE_FIPS": 48,
                "CZ_TYPE": "C",
                "CZ_FIPS": 3,
                "CZ_TIMEZONE": "MST-7",
                "BEGIN_DATE_TIME": "2021-07-01 12:00:00",
                "END_DATE_TIME": "2021-07-01 13:00:00",
                "EVENT_TYPE": "High Wind",
                "MAGNITUDE": 50,
            },
        ]
    ).to_csv(details, index=False, compression="gzip")
    crosswalk = tmp_path / "zones.dbx"
    crosswalk.write_text("TX|001|XXX|Example||Example|48001|CST-6\n")
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        replace_frame(
            con,
            "counties",
            pd.DataFrame(
                [
                    {
                        "county_fips": "48001",
                        "name": "Example",
                        "state": "TX",
                        "pop": 1,
                        "geom_wkb": Polygon(
                            [(-99, 29), (-95, 29), (-95, 33), (-99, 33)]
                        ).wkb,
                    },
                    {
                        "county_fips": "48003",
                        "name": "Example 2",
                        "state": "TX",
                        "pop": 1,
                        "geom_wkb": Polygon(
                            [(-106, 29), (-94, 29), (-94, 33), (-106, 33)]
                        ).wkb,
                    },
                ]
            ),
            source_name="test",
            source_ref="storm-fixture",
            fixture_batch_id="test",
        )
        assert load_storm_events(con, str(details), str(crosswalk), 2021) == 2
        observed = con.execute(
            "SELECT event_id, ts_begin FROM storm_events ORDER BY event_id"
        ).fetchall()
    finally:
        con.close()
    assert observed == [
        (1, pd.Timestamp("2021-07-01 18:00:00")),
        (2, pd.Timestamp("2021-07-01 19:00:00")),
    ]


def test_storm_events_rejects_undocumented_timezone():
    with pytest.raises(ValueError, match="unsupported Storm Events CZ_TIMEZONE"):
        _cz_timezone("PST-8")


def test_storm_events_accepts_ncei_daylight_offset_labels():
    assert _cz_timezone("CDT-5") == "Etc/GMT+5"
    assert _cz_timezone("MDT-6") == "Etc/GMT+6"


def test_ntad_source_ids_resolve_hash_collisions_and_reserve_other_load_ids(
    monkeypatch,
):
    monkeypatch.setattr("pipelines.critical_loads._stable_id", lambda *_args: 17)

    ids = _unique_stable_ids(pd.Series(["OBJECTID:2", "OBJECTID:1"]), reserved={17})

    assert ids.nunique() == 2
    assert set(ids).isdisjoint({17})


def test_ntad_source_ids_fall_back_to_unique_objectid_when_primary_id_is_blank():
    active = gpd.GeoDataFrame(
        {"mirtaLocationsIdpk": ["", ""], "OBJECTID": [11, 12]},
        geometry=[
            Polygon([(-99, 29), (-98, 29), (-98, 30), (-99, 29)]),
            Polygon([(-97, 29), (-96, 29), (-96, 30), (-97, 29)]),
        ],
        crs=4326,
    )

    assert _ntad_source_ids(active).tolist() == ["OBJECTID:11", "OBJECTID:12"]


def test_storm_events_records_unmatched_zone_assignments(tmp_path):
    details = tmp_path / "details.csv.gz"
    pd.DataFrame(
        [
            {
                "EVENT_ID": 1,
                "STATE": "TEXAS",
                "STATE_FIPS": 48,
                "CZ_TYPE": "Z",
                "CZ_FIPS": 999,
                "CZ_TIMEZONE": "CST-6",
                "BEGIN_DATE_TIME": "2021-07-01 12:00:00",
                "END_DATE_TIME": "2021-07-01 13:00:00",
                "EVENT_TYPE": "High Wind",
                "MAGNITUDE": 50,
            }
        ]
    ).to_csv(details, index=False, compression="gzip")
    crosswalk = tmp_path / "zones.dbx"
    crosswalk.write_text("TX|001|XXX|Example||Example|48001|CST-6\n")
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        assert (
            load_storm_events(
                con,
                str(details),
                [
                    NwsCrosswalkRelease(
                        release="fixture",
                        path=crosswalk,
                        valid_from=datetime.fromisoformat("2021-01-01"),
                        valid_until=datetime.fromisoformat("2022-01-01"),
                        source_url="https://example.test/nws/fixture.dbx",
                        sha256=sha256_file(crosswalk),
                    )
                ],
                2021,
            )
            == 0
        )
        assert con.execute(
            "SELECT source_key, warning FROM ingest_warnings"
        ).fetchall() == [
            (
                "2021:scope:tx:zone:999",
                "1 Texas zone-type Storm Events had no county crosswalk mapping",
            ),
        ]
    finally:
        con.close()


def test_dod_county_assignment_prevents_cross_county_bus_matches(tmp_path):
    county = Polygon([(-98, 30), (-96, 30), (-96, 32), (-98, 32), (-98, 30)])
    dod_inside = Polygon(
        [(-97.2, 30.5), (-97.0, 30.5), (-97.0, 30.7), (-97.2, 30.7), (-97.2, 30.5)]
    )
    dod_outside = Polygon(
        [(-100.2, 30.5), (-100.0, 30.5), (-100.0, 30.7), (-100.2, 30.7), (-100.2, 30.5)]
    )
    geojson = tmp_path / "dod.geojson"
    geojson.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "stateNameCode": "TX",
                            "siteOperationalStatus": "act",
                            "siteName": "Inside",
                            "siteReportingComponent": "Army",
                            "isJointBase": False,
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [list(dod_inside.exterior.coords)],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {
                            "stateNameCode": "TX",
                            "siteOperationalStatus": "act",
                            "siteName": "Outside",
                            "siteReportingComponent": "Army",
                            "isJointBase": False,
                        },
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [list(dod_outside.exterior.coords)],
                        },
                    },
                ],
            }
        )
    )
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        replace_frame(
            con,
            "counties",
            pd.DataFrame(
                [
                    {
                        "county_fips": "48001",
                        "name": "Example",
                        "state": "TX",
                        "pop": 1,
                        "geom_wkb": county.wkb,
                    },
                    {
                        "county_fips": "48003",
                        "name": "Other",
                        "state": "TX",
                        "pop": 1,
                        "geom_wkb": Polygon(
                            [(-96, 30), (-94, 30), (-94, 32), (-96, 32)]
                        ).wkb,
                    },
                ]
            ),
            source_name="test",
            source_ref="spatial-fixture",
            fixture_batch_id="test",
        )
        replace_frame(
            con,
            "buses",
            pd.DataFrame(
                [
                    {
                        "bus_id": 1,
                        "name": "same county",
                        "base_kv": 115.0,
                        "lon": -97.1,
                        "lat": 30.6,
                        "county_fips": "48001",
                        "ba_code": None,
                        "coord_source": "test",
                        "zone": None,
                        "area": None,
                    }
                ]
            ),
            source_name="test",
            source_ref="spatial-fixture",
            fixture_batch_id="test",
        )
        assert load_dod(con, str(geojson), min_area_km2=1) == 1
        assert con.execute(
            "SELECT county_fips FROM critical_loads WHERE name = 'Inside'"
        ).fetchone() == ("48001",)
        assert con.execute(
            "SELECT count(*) FROM critical_loads WHERE name = 'Outside'"
        ).fetchone() == (0,)
        # A known county without a qualifying bus must not fall back to a bus in a different county.
        replace_frame(
            con,
            "critical_loads",
            pd.DataFrame(
                [
                    {
                        "cl_id": 3,
                        "kind": "hospital",
                        "name": "No local bus",
                        "lon": -95,
                        "lat": 30.5,
                        "bus_id": None,
                        "county_fips": "48003",
                    }
                ]
            ),
            where="cl_id = 3",
            source_name="test",
            source_ref="spatial-fixture",
            fixture_batch_id="test",
        )
        assert join_critical_loads_to_bus(con) == 1
        assignments = con.execute(
            "SELECT name, bus_id FROM critical_loads ORDER BY cl_id"
        ).fetchall()
        methods = con.execute(
            "SELECT cl_id, bus_id, match_method FROM critical_load_bus_dist ORDER BY cl_id"
        ).fetchall()
    finally:
        con.close()
    assert assignments == [("Inside", 1), ("No local bus", None)]
    assert methods == [(1, 1, "same_county"), (3, None, "unassigned_no_eligible_bus")]


def _storm_details(tmp_path, cz_timezone: str):
    details = tmp_path / "details.csv.gz"
    pd.DataFrame(
        [
            {
                "EVENT_ID": 1,
                "STATE": "TEXAS",
                "STATE_FIPS": 48,
                "CZ_TYPE": "C",
                "CZ_FIPS": 1,
                "CZ_TIMEZONE": cz_timezone,
                "BEGIN_DATE_TIME": "2021-07-01 12:00:00",
                "END_DATE_TIME": "2021-07-01 13:00:00",
                "EVENT_TYPE": "High Wind",
                "MAGNITUDE": 50,
            }
        ]
    ).to_csv(details, index=False, compression="gzip")
    crosswalk = tmp_path / "zones.dbx"
    crosswalk.write_text("TX|001|XXX|Example||Example|48001|CST-6\n")
    return details, crosswalk


def _seed_one_county(con):
    replace_frame(
        con,
        "counties",
        pd.DataFrame(
            [
                {
                    "county_fips": "48001",
                    "name": "Example",
                    "state": "TX",
                    "pop": 1,
                    "geom_wkb": Polygon(
                        [(-99, 29), (-95, 29), (-95, 33), (-99, 33)]
                    ).wkb,
                }
            ]
        ),
        source_name="test",
        source_ref="storm-fixture",
        fixture_batch_id="test",
    )


def test_load_storm_events_applies_ncei_daylight_label_offsets(tmp_path):
    # Wire test: the CDT-5 label is honoured at the loader, not only in the
    # helper.  12:00 at UTC-5 is 17:00 UTC.
    details, crosswalk = _storm_details(tmp_path, "CDT-5")
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        _seed_one_county(con)
        assert load_storm_events(con, str(details), str(crosswalk), 2021) == 1
        observed = con.execute("SELECT ts_begin FROM storm_events").fetchall()
    finally:
        con.close()
    assert observed == [(pd.Timestamp("2021-07-01 17:00:00"),)]


def test_load_storm_events_rejects_undocumented_timezone_loudly(tmp_path):
    # The pre-2WKG-414 negative example was CDT-5; that label is now documented,
    # so an undocumented label must still fail the load instead of guessing.
    details, crosswalk = _storm_details(tmp_path, "PST-8")
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        _seed_one_county(con)
        with pytest.raises(ValueError, match="unsupported Storm Events CZ_TIMEZONE"):
            load_storm_events(con, str(details), str(crosswalk), 2021)
        assert con.execute("SELECT count(*) FROM storm_events").fetchone() == (0,)
    finally:
        con.close()


def test_load_dod_never_reuses_a_cl_id_owned_by_another_facility_kind(tmp_path):
    # Wire test for the reserved-id rule at the load_dod call site: a hospital
    # row already holding the NTAD-derived id must survive, and the DoD row
    # must take a different id.
    from pipelines.critical_loads import _stable_id

    polygon = Polygon([(-98.2, 29.8), (-97.8, 29.8), (-97.8, 30.2), (-98.2, 30.2)])
    feature = {
        "type": "Feature",
        "properties": {
            "mirtaLocationsIdpk": 77,
            "stateNameCode": "TX",
            "siteOperationalStatus": "act",
            "siteName": "Fixture Base",
            "siteReportingComponent": "usa",
            "isJointBase": False,
        },
        "geometry": {"type": "Polygon", "coordinates": [list(polygon.exterior.coords)]},
    }
    geojson = tmp_path / "dod.geojson"
    geojson.write_text(json.dumps({"type": "FeatureCollection", "features": [feature]}))
    reserved = _stable_id("ntad_military_bases", "mirtaLocationsIdpk:77")
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        _seed_one_county(con)
        replace_frame(
            con,
            "critical_loads",
            pd.DataFrame(
                [
                    {
                        "cl_id": reserved,
                        "kind": "hospital",
                        "name": "Fixture Hospital",
                        "lon": -98.0,
                        "lat": 30.0,
                        "bus_id": None,
                        "county_fips": "48001",
                    }
                ]
            ),
            where="kind = 'hospital'",
            source_name="test",
            source_ref="hospitals",
            fixture_batch_id="test",
        )
        assert load_dod(con, str(geojson), min_area_km2=1) == 1
        rows = con.execute(
            "SELECT kind, cl_id FROM critical_loads ORDER BY kind"
        ).fetchall()
    finally:
        con.close()
    assert rows[1] == ("hospital", reserved)
    assert rows[0][0] == "dod"
    assert rows[0][1] != reserved
    assert rows[0][1] > 0

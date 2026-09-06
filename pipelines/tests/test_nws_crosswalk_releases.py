from datetime import datetime

import pandas as pd
from shapely.geometry import Polygon

from pipelines.db import connect, replace_frame
from pipelines.common import sha256_file
from pipelines.storm_events import (
    NwsCrosswalkRelease,
    load_storm_events,
    select_nws_crosswalk_release,
)


def _release(name, path, start, end):
    return NwsCrosswalkRelease(
        release=name,
        path=path,
        valid_from=datetime.fromisoformat(start),
        valid_until=datetime.fromisoformat(end),
        source_url=f"https://example.test/nws/{name}.dbx",
        sha256=sha256_file(path) if path.exists() else "0" * 64,
    )


def _zone_event(event_id, when, zone):
    return {
        "EVENT_ID": event_id,
        "STATE": "TEXAS",
        "STATE_FIPS": 48,
        "CZ_TYPE": "Z",
        "CZ_FIPS": zone,
        "CZ_TIMEZONE": "CST-6",
        "BEGIN_DATE_TIME": when,
        "END_DATE_TIME": when,
        "EVENT_TYPE": "Winter Storm",
        "MAGNITUDE": None,
    }


def _seed_county(con):
    replace_frame(
        con,
        "counties",
        pd.DataFrame(
            [
                {
                    "county_fips": "48001",
                    "name": "Fixture",
                    "state": "TX",
                    "pop": 1,
                    "geom_wkb": Polygon(
                        [(-99, 29), (-95, 29), (-95, 33), (-99, 33)]
                    ).wkb,
                },
                {
                    "county_fips": "48002",
                    "name": "Fixture 2",
                    "state": "TX",
                    "pop": 1,
                    "geom_wkb": Polygon(
                        [(-98, 29), (-94, 29), (-94, 33), (-98, 33)]
                    ).wkb,
                },
                {
                    "county_fips": "48003",
                    "name": "Fixture 3",
                    "state": "TX",
                    "pop": 1,
                    "geom_wkb": Polygon(
                        [(-97, 29), (-93, 29), (-93, 33), (-97, 33)]
                    ).wkb,
                },
                {
                    "county_fips": "48004",
                    "name": "Fixture 4",
                    "state": "TX",
                    "pop": 1,
                    "geom_wkb": Polygon(
                        [(-96, 29), (-92, 29), (-92, 33), (-96, 33)]
                    ).wkb,
                },
            ]
        ),
        source_name="test",
        source_ref="fixture",
        fixture_batch_id="test",
    )


def test_release_selection_is_half_open_and_never_falls_forward(tmp_path):
    uri = _release("bp10nv20", tmp_path / "uri.dbx", "2021-02-11", "2021-02-21")
    beryl = _release("bp05mr24", tmp_path / "beryl.dbx", "2024-07-07", "2024-07-11")

    assert (
        select_nws_crosswalk_release(datetime.fromisoformat("2021-02-11"), [uri, beryl])
        == uri
    )
    assert (
        select_nws_crosswalk_release(datetime.fromisoformat("2021-02-21"), [uri, beryl])
        is None
    )
    assert (
        select_nws_crosswalk_release(datetime.fromisoformat("2024-07-07"), [uri, beryl])
        == beryl
    )
    assert (
        select_nws_crosswalk_release(datetime.fromisoformat("2024-07-11"), [uri, beryl])
        is None
    )


def test_loader_selects_releases_after_cst_and_cdt_utc_normalization(tmp_path):
    detail, crosswalk = tmp_path / "boundary.csv.gz", tmp_path / "release.dbx"
    crosswalk.write_text("TX|215|||||48001|CST-6\n")
    rows = [
        _zone_event(1, "2021-02-10 18:00:00", 215),
        _zone_event(2, "2021-02-20 18:00:00", 215),
        {**_zone_event(3, "2024-07-06 19:00:00", 215), "CZ_TIMEZONE": "CDT-5"},
        {**_zone_event(4, "2024-07-10 19:00:00", 215), "CZ_TIMEZONE": "CDT-5"},
    ]
    pd.DataFrame(rows).to_csv(detail, index=False, compression="gzip")
    con = connect(tmp_path / "grid.duckdb")
    try:
        _seed_county(con)
        assert (
            load_storm_events(
                con,
                str(detail),
                [
                    _release("uri", crosswalk, "2021-02-11", "2021-02-21"),
                    _release("beryl", crosswalk, "2024-07-07", "2024-07-11"),
                ],
                2021,
            )
            == 2
        )
        assert con.execute(
            "SELECT event_id FROM storm_events ORDER BY event_id"
        ).fetchall() == [(1,), (3,)]
    finally:
        con.close()


def test_uri_legacy_zones_recover_all_22_rows_with_the_historical_release(tmp_path):
    detail, crosswalk = tmp_path / "uri.csv.gz", tmp_path / "bp10nv20.dbx"
    zones = (215, 216, 256, 257)
    crosswalk.write_text(
        "".join(
            f"TX|{zone:03d}|||||48{index:03d}|CST-6\n"
            for index, zone in enumerate(zones, 1)
        )
    )
    pd.DataFrame(
        [
            _zone_event(943000 + index, "2021-02-15 12:00:00", zones[index % 4])
            for index in range(22)
        ]
    ).to_csv(detail, index=False, compression="gzip")
    con = connect(tmp_path / "grid.duckdb")
    try:
        _seed_county(con)
        assert (
            load_storm_events(
                con,
                str(detail),
                [_release("bp10nv20", crosswalk, "2021-02-11", "2021-02-21")],
                2021,
            )
            == 22
        )
        assert con.execute("SELECT count(*) FROM storm_events").fetchone() == (22,)
        assert con.execute(
            "SELECT DISTINCT assignment_method FROM storm_event_attributes"
        ).fetchall() == [("nws_crosswalk:bp10nv20",)]
        assert con.execute(
            "SELECT source_release FROM ingest_log WHERE source = 'nws_zone_county'"
        ).fetchall() == [("bp10nv20",)]
    finally:
        con.close()


def test_partial_interval_fails_closed_and_beryl_uses_its_valid_release(tmp_path):
    detail, crosswalk = tmp_path / "storms.csv.gz", tmp_path / "bp05mr24.dbx"
    crosswalk.write_text("TX|039|||||48001|CST-6\n")
    pd.DataFrame(
        [
            _zone_event(1, "2021-02-20 12:00:00", 39),
            _zone_event(2, "2024-07-09 12:00:00", 39),
        ]
    ).to_csv(detail, index=False, compression="gzip")
    con = connect(tmp_path / "grid.duckdb")
    try:
        _seed_county(con)
        assert (
            load_storm_events(
                con,
                str(detail),
                [
                    _release("bp10nv20", crosswalk, "2021-02-11", "2021-02-20"),
                    _release("bp05mr24", crosswalk, "2024-07-07", "2024-07-11"),
                ],
                2024,
            )
            == 1
        )
        assert con.execute("SELECT event_id FROM storm_events").fetchall() == [(2,)]
        assert con.execute(
            "SELECT source_key FROM ingest_warnings WHERE source = 'noaa_storm_events'"
        ).fetchall() == [("2024:interval:039",)]
        assert con.execute(
            "SELECT source_release FROM ingest_log WHERE source = 'nws_zone_county'"
        ).fetchall() == [("bp05mr24",)]
    finally:
        con.close()

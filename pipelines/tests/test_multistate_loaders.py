from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from shapely.geometry import Polygon

import pipelines.build as build_module
from pipelines.build import _dod_filename, _missing_p0_inputs, build
from pipelines.common import sha256_file
from pipelines.db import connect, replace_frame
from pipelines.eia860 import _scope_plants, load_eia860_plants, seed_site_candidates
from pipelines.state_scope import StateScope, scope
from pipelines.storm_events import (
    NwsCrosswalkRelease,
    _scope_events,
    _zone_crosswalk,
    load_storm_events,
)


def test_minnesota_storm_event_and_zone_inputs_are_not_filtered_to_texas(tmp_path):
    crosswalk = tmp_path / "zones.txt"
    crosswalk.write_text("TX|001||| | |48001\nMN|002||| | |27001\n")
    events = pd.DataFrame({"STATE": ["TEXAS", "MINNESOTA"], "EVENT_ID": [1, 2]})

    assert _scope_events(events, "MN").EVENT_ID.tolist() == [2]
    assert _zone_crosswalk(crosswalk, "MN") == {"002": ["27001"]}


def test_minnesota_eia_plants_are_retained_by_scope():
    plants = pd.DataFrame({"state": ["TX", "MN"], "plant_id_eia": [1, 2]})
    assert _scope_plants(plants, "MN").plant_id_eia.tolist() == [2]


def test_builder_uses_scope_derived_dod_filename():
    assert _dod_filename("MN") == "mn.geojson"
    assert _dod_filename(["MN", "TX"]) == "mn-tx.geojson"


# --- DoD input contract (catalog: ntad_military_bases/fy2024/texas.geojson) ---


def test_default_dod_filename_is_the_catalog_texas_fixture():
    # The dataset catalog and downloader only produce texas.geojson; the Texas
    # P0 build must keep resolving to it whether the scope is implied or named.
    assert _dod_filename(None) == "texas.geojson"
    assert _dod_filename("TX") == "texas.geojson"
    assert _dod_filename(["TX"]) == "texas.geojson"
    assert _dod_filename(scope("48")) == "texas.geojson"


def test_dod_catalog_entry_matches_the_default_builder_filename():
    # Guard against renaming the catalog entry without updating the builder.
    catalog = json.loads(build_module.P0_RAW_INPUTS_CATALOG.read_text())
    labels = [item["label"] for item in catalog["p0_raw_inputs"]]
    assert f"ntad_military_bases/fy2024/{_dod_filename(None)}" in labels


def _touch_every_catalog_input(raw: Path) -> None:
    for _label, alternatives in build_module._p0_raw_inputs():
        for parts in alternatives:
            path = raw.joinpath(*parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()


def test_texas_preflight_passes_on_a_catalog_conformant_raw_dir(tmp_path):
    raw = tmp_path / "raw"
    _touch_every_catalog_input(raw)
    assert (raw / "ntad_military_bases" / "fy2024" / "texas.geojson").exists()

    assert _missing_p0_inputs(raw, "UTC") == []
    assert _missing_p0_inputs(raw, "UTC", scope("TX")) == []


def test_preflight_names_the_missing_dod_file_once(tmp_path):
    raw = tmp_path / "raw"
    _touch_every_catalog_input(raw)
    (raw / "ntad_military_bases" / "fy2024" / "texas.geojson").unlink()

    assert _missing_p0_inputs(raw, "UTC") == [
        "ntad_military_bases/fy2024/texas.geojson"
    ]
    with pytest.raises(build_module.IncompleteP0BuildError, match="texas.geojson"):
        build(str(raw), str(tmp_path / "grid.duckdb"), "UTC")
    assert not (tmp_path / "grid.duckdb").exists()


def test_preflight_requires_the_scoped_dod_file_for_a_named_scope(tmp_path):
    raw = tmp_path / "raw"
    _touch_every_catalog_input(raw)

    assert _missing_p0_inputs(raw, "UTC", "MN") == [
        "ntad_military_bases/fy2024/mn.geojson"
    ]
    (raw / "ntad_military_bases" / "fy2024" / "mn.geojson").touch()
    assert _missing_p0_inputs(raw, "UTC", "MN") == []


def _received_scope(args: tuple, kwargs: dict) -> StateScope | None:
    if "states" in kwargs:
        return kwargs["states"]
    return next((arg for arg in args if isinstance(arg, StateScope)), None)


def test_build_mutating_threads_scope_to_every_loader_and_the_dod_path(
    tmp_path, monkeypatch
):
    raw = tmp_path / "raw"
    _touch_every_catalog_input(raw)
    sentinel = raw / "ntad_military_bases" / "fy2024" / "sentinel.geojson"
    sentinel.touch()
    monkeypatch.setattr(
        build_module, "_dod_filename", lambda states=None: "sentinel.geojson"
    )

    class _Con:
        def close(self) -> None:
            pass

    calls: dict[str, tuple[tuple, dict]] = {}

    def recorder(name: str, result):
        def record(*args, **kwargs):
            calls[name] = (args, kwargs)
            return result

        return record

    scoped_loaders = (
        "load_counties",
        "load_nri",
        "load_eia860_plants",
        "seed_site_candidates",
        "load_storm_events",
        "load_county_customers",
        "load_coverage_history",
        "load_eaglei",
        "load_dod",
    )
    monkeypatch.setattr(build_module, "connect", lambda _path: _Con())
    for name in scoped_loaders + (
        "join_bus_county",
        "load_eia930",
        "join_critical_loads_to_bus",
    ):
        monkeypatch.setattr(build_module, name, recorder(name, 1))
    monkeypatch.setattr(build_module, "load_activsg", recorder("load_activsg", {}))
    monkeypatch.setattr(build_module, "_verified_activsg_retrieval", lambda *_a: None)
    monkeypatch.setattr(build_module, "validate_schema", lambda _con: None)
    monkeypatch.setattr(build_module, "export_parquet", lambda _con, _dir: None)

    counts = build_module._build_mutating(
        str(raw), str(tmp_path / "stage.duckdb"), "UTC", str(tmp_path / "parquet")
    )

    assert counts["critical_loads_dod"] == 1
    # The DoD extract is resolved through the scope-derived filename, not a literal.
    assert calls["load_dod"][0][1] == str(sentinel)
    # Every state-aware loader receives the one parsed scope (Texas by default).
    for name in scoped_loaders:
        args, kwargs = calls[name]
        assert _received_scope(args, kwargs) == scope("TX"), name


# --- Wire tests: TX+MN fixtures through the real loaders and a real DuckDB ---

STORM_ROWS = [
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
        "STATE": "MINNESOTA",
        "STATE_FIPS": 27,
        "CZ_TYPE": "C",
        "CZ_FIPS": 1,
        "CZ_TIMEZONE": "CST-6",
        "BEGIN_DATE_TIME": "2021-07-01 12:00:00",
        "END_DATE_TIME": "2021-07-01 13:00:00",
        "EVENT_TYPE": "Hail",
        "MAGNITUDE": 1.0,
    },
    {
        "EVENT_ID": 3,
        "STATE": "TEXAS",
        "STATE_FIPS": 48,
        "CZ_TYPE": "Z",
        "CZ_FIPS": 999,
        "CZ_TIMEZONE": "CST-6",
        "BEGIN_DATE_TIME": "2021-07-01 12:00:00",
        "END_DATE_TIME": "2021-07-01 13:00:00",
        "EVENT_TYPE": "Blizzard",
        "MAGNITUDE": None,
    },
    {
        "EVENT_ID": 4,
        "STATE": "MINNESOTA",
        "STATE_FIPS": 27,
        "CZ_TYPE": "Z",
        "CZ_FIPS": 2,
        "CZ_TIMEZONE": "CST-6",
        "BEGIN_DATE_TIME": "2021-07-01 12:00:00",
        "END_DATE_TIME": "2021-07-01 13:00:00",
        "EVENT_TYPE": "Blizzard",
        "MAGNITUDE": None,
    },
]
ZONE_CROSSWALK = "TX|001|XXX|Ex||Ex|48001|CST-6\nMN|002|YYY|Ex||Ex|27001|CST-6\n"
PLANTS = [
    {
        "plant_id_eia": 1,
        "report_date": "2024-01-01",
        "latitude": 30.0,
        "longitude": -97.0,
        "state": "TX",
        "plant_name_eia": "TexPlant",
    },
    {
        "plant_id_eia": 2,
        "report_date": "2024-01-01",
        "latitude": 46.0,
        "longitude": -93.5,
        "state": "MN",
        "plant_name_eia": "MinnPlant",
    },
]
GENERATORS = [
    {
        "plant_id_eia": 1,
        "generator_id": "A",
        "report_date": "2024-01-01",
        "capacity_mw": 100,
        "fuel_type_code_pudl": "coal",
        "operational_status": "retired",
    },
    {
        "plant_id_eia": 2,
        "generator_id": "A",
        "report_date": "2024-01-01",
        "capacity_mw": 200,
        "fuel_type_code_pudl": "coal",
        "operational_status": "retired",
    },
]

# Output of origin/master (Texas-only loaders) for the same fixture; the
# parameterised loaders must reproduce it exactly for the default scope.
MASTER_TEXAS_STORM_EVENTS = [
    (
        1,
        pd.Timestamp("2021-07-01 18:00:00"),
        pd.Timestamp("2021-07-01 19:00:00"),
        "48001",
        "High Wind",
        50.0,
        "noaa_storm_events",
        "details.csv.gz",
        "2021",
        "p0-storm-events-2021",
    ),
]
MASTER_TEXAS_STORM_ATTRIBUTES = [(1, "48001", 2021, None, None, "direct_county")]
MASTER_TEXAS_STORM_WARNINGS = [
    (
        "noaa_storm_events",
        "2021:zone:999",
        "1 Texas zone-type Storm Events had no county crosswalk mapping",
    ),
]
MASTER_TEXAS_EIA_PLANTS = [
    (1, "TexPlant", -97.0, 30.0, "TX", "48001", 100.0, "coal", None, "retired"),
]
MASTER_TEXAS_SITE_CANDIDATES = [
    (
        1,
        "TexPlant",
        "coal_retired",
        -97.0,
        30.0,
        "48001",
        None,
        100.0,
        "eia_plant:1",
        "pudl_eia860",
        "eia_plants",
        "v2026.2.0",
        "p0-eia860-v2026.2.0",
    ),
]


def _storm_inputs(tmp_path: Path) -> tuple[str, list[NwsCrosswalkRelease]]:
    details = tmp_path / "details.csv.gz"
    pd.DataFrame(STORM_ROWS).to_csv(details, index=False, compression="gzip")
    crosswalk = tmp_path / "zones.dbx"
    crosswalk.write_text(ZONE_CROSSWALK)
    return str(details), [
        NwsCrosswalkRelease(
            release="fixture",
            path=crosswalk,
            valid_from=datetime.fromisoformat("2021-01-01"),
            valid_until=datetime.fromisoformat("2022-01-01"),
            source_url="https://example.test/nws/fixture.dbx",
            sha256=sha256_file(crosswalk),
        )
    ]


def _eia_inputs(tmp_path: Path) -> tuple[str, str]:
    plants, generators = tmp_path / "plants.parquet", tmp_path / "generators.parquet"
    pd.DataFrame(PLANTS).to_parquet(plants)
    pd.DataFrame(GENERATORS).to_parquet(generators)
    return str(plants), str(generators)


def _seed_counties(con) -> None:
    replace_frame(
        con,
        "counties",
        pd.DataFrame(
            [
                {
                    "county_fips": "48001",
                    "name": "Anderson",
                    "state": "TX",
                    "pop": 1,
                    "geom_wkb": Polygon(
                        [(-99, 29), (-95, 29), (-95, 33), (-99, 33)]
                    ).wkb,
                },
                {
                    "county_fips": "27001",
                    "name": "Aitkin",
                    "state": "MN",
                    "pop": 1,
                    "geom_wkb": Polygon(
                        [(-95, 45), (-92, 45), (-92, 48), (-95, 48)]
                    ).wkb,
                },
            ]
        ),
        source_name="test",
        source_ref="multistate-fixture",
        fixture_batch_id="test",
    )


STORM_SELECT = (
    "SELECT event_id, ts_begin, ts_end, county_fips, type, magnitude, source_name, "
    "source_ref, source_version, fixture_batch_id FROM storm_events ORDER BY event_id"
)
ATTR_SELECT = (
    "SELECT event_id, county_fips, source_year, episode_id, magnitude_type, "
    "assignment_method FROM storm_event_attributes ORDER BY event_id"
)
WARN_SELECT = "SELECT source, source_key, warning FROM ingest_warnings ORDER BY source, source_key"
PLANT_SELECT = (
    "SELECT plant_id_eia, plant_name, lon, lat, state, county_fips, capacity_mw, "
    "primary_fuel, retirement_year, operational_status FROM eia_plants "
    "ORDER BY plant_id_eia"
)
SITE_SELECT = (
    "SELECT site_id, name, kind, lon, lat, county_fips, bus_id, capacity_slot_mw, "
    "source_site_id, source_name, source_ref, source_version, fixture_batch_id "
    "FROM site_candidates ORDER BY site_id"
)


def test_load_storm_events_default_scope_matches_master_texas_output(tmp_path):
    details, crosswalk = _storm_inputs(tmp_path)
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        _seed_counties(con)
        assert load_storm_events(con, details, crosswalk, 2021) == 1
        assert con.execute(STORM_SELECT).fetchall() == MASTER_TEXAS_STORM_EVENTS
        assert con.execute(ATTR_SELECT).fetchall() == MASTER_TEXAS_STORM_ATTRIBUTES
        assert con.execute(WARN_SELECT).fetchall() == MASTER_TEXAS_STORM_WARNINGS
    finally:
        con.close()


def test_load_storm_events_minnesota_scope_loads_only_minnesota_rows(tmp_path):
    details, crosswalk = _storm_inputs(tmp_path)
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        _seed_counties(con)
        assert load_storm_events(con, details, crosswalk, 2021, "MN") == 2
        rows = con.execute(
            "SELECT event_id, county_fips, type FROM storm_events ORDER BY event_id"
        ).fetchall()
        methods = con.execute(ATTR_SELECT).fetchall()
        warnings = con.execute(WARN_SELECT).fetchall()
    finally:
        con.close()
    # Event 4 is a Minnesota forecast zone: it only maps when the crosswalk is
    # read for Minnesota, not for Texas.
    assert rows == [(2, "27001", "Hail"), (4, "27001", "Blizzard")]
    assert methods == [
        (2, "27001", 2021, None, None, "direct_county"),
        (4, "27001", 2021, None, None, "nws_crosswalk:fixture"),
    ]
    assert warnings == []


def test_load_storm_events_minnesota_refresh_keeps_texas_rows(tmp_path):
    details, crosswalk = _storm_inputs(tmp_path)
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        _seed_counties(con)
        assert load_storm_events(con, details, crosswalk, 2021) == 1
        assert load_storm_events(con, details, crosswalk, 2021, "MN") == 2
        assert load_storm_events(con, details, crosswalk, 2021, "MN") == 2
        rows = con.execute(
            "SELECT event_id, county_fips FROM storm_events ORDER BY event_id"
        ).fetchall()
        attributes = con.execute(
            "SELECT event_id, county_fips FROM storm_event_attributes ORDER BY event_id"
        ).fetchall()
        # A Texas refresh after the Minnesota loads must still find its own
        # attribute rows (the delete is keyed through them) and change nothing.
        assert load_storm_events(con, details, crosswalk, 2021) == 1
        refreshed = con.execute(
            "SELECT event_id, county_fips FROM storm_events ORDER BY event_id"
        ).fetchall()
    finally:
        con.close()
    assert rows == [(1, "48001"), (2, "27001"), (4, "27001")]
    assert attributes == rows
    assert refreshed == rows


def test_load_eia860_plants_default_scope_matches_master_texas_output(tmp_path):
    plants, generators = _eia_inputs(tmp_path)
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        _seed_counties(con)
        assert load_eia860_plants(con, plants, generators) == 1
        assert seed_site_candidates(con) == 1
        assert con.execute(PLANT_SELECT).fetchall() == MASTER_TEXAS_EIA_PLANTS
        assert con.execute(SITE_SELECT).fetchall() == MASTER_TEXAS_SITE_CANDIDATES
        assert con.execute(WARN_SELECT).fetchall() == []
    finally:
        con.close()


def test_load_eia860_plants_minnesota_scope_replaces_only_minnesota_rows(tmp_path):
    plants, generators = _eia_inputs(tmp_path)
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        _seed_counties(con)
        assert load_eia860_plants(con, plants, generators) == 1
        assert seed_site_candidates(con) == 1
        assert load_eia860_plants(con, plants, generators, states="MN") == 1
        plant_rows = con.execute(
            "SELECT plant_id_eia, state, county_fips FROM eia_plants ORDER BY plant_id_eia"
        ).fetchall()
        assert seed_site_candidates(con, "MN") == 1
        sites = con.execute(
            "SELECT name, kind, county_fips FROM site_candidates ORDER BY site_id"
        ).fetchall()
    finally:
        con.close()
    # The Texas release rows survive a Minnesota reload: the delete predicates
    # are scoped, and Minnesota plants land in Minnesota counties.
    assert plant_rows == [(1, "TX", "48001"), (2, "MN", "27001")]
    assert sites == [
        ("TexPlant", "coal_retired", "48001"),
        ("MinnPlant", "coal_retired", "27001"),
    ]


def test_load_eia860_plants_minnesota_scope_from_empty_db(tmp_path):
    plants, generators = _eia_inputs(tmp_path)
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        _seed_counties(con)
        assert load_eia860_plants(con, plants, generators, states="MN") == 1
        assert seed_site_candidates(con, "MN") == 1
        states = con.execute("SELECT state FROM eia_plants").fetchall()
        sites = con.execute("SELECT name FROM site_candidates").fetchall()
    finally:
        con.close()
    assert states == [("MN",)]
    assert sites == [("MinnPlant",)]


# --- A scope with no rows is reported, never silently loaded as 0 ---


def test_scope_with_no_source_rows_is_reported_in_ingest_warnings(tmp_path):
    details, crosswalk = _storm_inputs(tmp_path)
    plants, generators = _eia_inputs(tmp_path)
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        _seed_counties(con)
        assert load_storm_events(con, details, crosswalk, 2021, "WY") == 0
        assert load_eia860_plants(con, plants, generators, states="WY") == 0
        warnings = con.execute(WARN_SELECT).fetchall()
        # Replaying the same scope keeps exactly one warning per source.
        assert load_storm_events(con, details, crosswalk, 2021, "WY") == 0
        assert load_eia860_plants(con, plants, generators, states="WY") == 0
        replayed = con.execute(WARN_SELECT).fetchall()
    finally:
        con.close()
    assert warnings == [
        (
            "noaa_storm_events",
            "2021:scope:wy",
            (
                "0 Storm Events rows in details.csv.gz for scope wy; "
                "the source has no rows for Wyoming"
            ),
        ),
        (
            "pudl_eia860",
            "scope:wy",
            (
                "0 EIA-860 plants in plants.parquet for scope wy; "
                "the source has no rows for WY"
            ),
        ),
    ]
    assert replayed == warnings

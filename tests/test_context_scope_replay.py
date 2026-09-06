import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from pipelines.build import _nws_crosswalk_releases
from pipelines.common import sha256_file
from pipelines.counties import load_counties
from pipelines.db import connect, replace_frame
from pipelines.eaglei import load_eaglei
from pipelines.nri import load_nri


def seed(con):
    frame = pd.DataFrame(
        [
            {
                "county_fips": fips,
                "name": name,
                "state": state,
                "pop": 10,
                "geom_wkb": b"fixture",
            }
            for fips, name, state in [
                ("27001", "Aitkin", "MN"),
                ("55001", "Adams", "WI"),
            ]
        ]
    )
    replace_frame(
        con,
        "counties",
        frame,
        source_name="test",
        source_ref="fixture",
        fixture_batch_id="test",
    )


def test_state_replay_preserves_other_state_and_clears_empty_denominator(tmp_path):
    con = connect(tmp_path / "grid.duckdb")
    seed(con)
    path = tmp_path / "outages.csv"
    pd.DataFrame(
        [
            {
                "fips_code": "27001",
                "county": "Aitkin",
                "state": "Minnesota",
                "customers_out": 2,
                "run_start_time": "2024-12-31 20:00:00",
                "total_customers": 10,
            },
            {
                "fips_code": "55001",
                "county": "Adams",
                "state": "Wisconsin",
                "customers_out": 3,
                "run_start_time": "2024-12-31 20:00:00",
                "total_customers": 20,
            },
        ]
    ).to_csv(path, index=False)
    try:
        load_eaglei(con, path, 2024, "America/Chicago", "MN")
        load_eaglei(con, path, 2024, "America/Chicago", "WI")
        assert con.execute(
            "SELECT county_fips FROM eaglei_outages ORDER BY 1"
        ).fetchall() == [("27001",), ("55001",)]
        assert con.execute(
            "SELECT count(*) FROM eaglei_outage_observations"
        ).fetchone() == (2,)
        pd.read_csv(path).iloc[0:0].to_csv(path, index=False)
        load_eaglei(con, path, 2024, "America/Chicago", "MN")
        assert con.execute("SELECT county_fips FROM eaglei_outages").fetchall() == [
            ("55001",)
        ]
        assert con.execute("SELECT county_fips FROM county_customers").fetchall() == [
            ("55001",)
        ]
    finally:
        con.close()


def test_numeric_tiger_state_reruns_with_related_hazards(tmp_path, monkeypatch):
    source = tmp_path / "nri.json"
    source.write_text(
        json.dumps(
            {
                "features": [
                    {
                        "attributes": {
                            "STCOFIPS": "27001",
                            "STATEABBRV": "MN",
                            "POPULATION": 10,
                            "RISK_SCORE": 5,
                        }
                    }
                ]
            }
        )
    )
    tiger = tmp_path / "tiger.zip"
    tiger.write_bytes(b"fixture")
    geometry = gpd.GeoDataFrame(
        {
            "STATEFP": [27],
            "GEOID": ["27001"],
            "NAME": ["Aitkin"],
            "ALAND": [1],
            "AWATER": [0],
        },
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])],
        crs=4326,
    )
    monkeypatch.setattr("pipelines.counties.gpd.read_file", lambda _: geometry.copy())
    con = connect(tmp_path / "grid.duckdb")
    try:
        load_counties(con, tiger, source, "MN")
        load_nri(con, source, states="MN")
        load_counties(con, tiger, source, "MN")
        assert con.execute("SELECT county_fips,state FROM counties").fetchall() == [
            ("27001", "MN")
        ]
        assert con.execute("SELECT count(*) FROM hazard_static").fetchone() == (1,)
    finally:
        con.close()


def test_invalid_nri_population_preserves_previous_hazard(tmp_path):
    con = connect(tmp_path / "grid.duckdb")
    seed(con)
    path = tmp_path / "nri.json"

    def write(population):
        path.write_text(
            json.dumps(
                {
                    "features": [
                        {
                            "attributes": {
                                "STCOFIPS": "27001",
                                "STATEABBRV": "MN",
                                "POPULATION": population,
                                "RISK_SCORE": 5,
                            }
                        }
                    ]
                }
            )
        )

    try:
        write(10)
        load_nri(con, path, states="MN")
        write(None)
        with pytest.raises(ValueError, match="population"):
            load_nri(con, path, states="MN")
        assert con.execute("SELECT nri_score FROM hazard_static").fetchone() == (5,)
    finally:
        con.close()


def test_quality_and_audit_retain_each_state_on_combined_and_separate_replay(tmp_path):
    con = connect(tmp_path / "grid.duckdb")
    seed(con)
    path = tmp_path / "national.csv"
    path.write_text(
        "fips_code,county,state,customers_out,run_start_time\n"
        "27001,Aitkin,Minnesota,2,2024-01-01 00:00:00\n"
        "55001,Adams,Wisconsin,,2024-01-01 00:00:00\n"
    )
    try:
        load_eaglei(con, path, 2024, "UTC", ["MN", "WI"])
        load_eaglei(con, path, 2024, "UTC", "MN")
        load_eaglei(con, path, 2024, "UTC", "WI")
        assert con.execute(
            "SELECT state_fips, raw_rows, valid_rows, missing_customers FROM eaglei_ingest_quality_by_state ORDER BY 1"
        ).fetchall() == [("27", 1, 1, 0), ("55", 1, 0, 1)]
        assert con.execute(
            "SELECT source_release, rows_loaded FROM ingest_log WHERE source = 'eaglei' ORDER BY 1"
        ).fetchall() == [
            ("2024;scope=mn", 1),
            ("2024;scope=mn-wi", 1),
            ("2024;scope=wi", 0),
        ]
    finally:
        con.close()


def test_mismatched_source_state_fails_before_replacement(tmp_path):
    con = connect(tmp_path / "grid.duckdb")
    seed(con)
    path = tmp_path / "national.csv"
    path.write_text(
        "fips_code,county,state,customers_out,run_start_time\n27001,Aitkin,Minnesota,2,2024-01-01 00:00:00\n"
    )
    try:
        load_eaglei(con, path, 2024, "UTC", "MN")
        before = con.execute("SELECT * FROM eaglei_outages").fetchall()
        path.write_text(
            "fips_code,county,state,customers_out,run_start_time\n55001,Adams,Minnesota,3,2024-01-01 00:00:00\n"
        )
        with pytest.raises(ValueError, match="does not match"):
            load_eaglei(con, path, 2024, "UTC", "MN")
        assert con.execute("SELECT * FROM eaglei_outages").fetchall() == before
    finally:
        con.close()


def test_context_cli_rejects_malformed_year_before_database_creation(tmp_path, capsys):
    from pipelines.build_state_context import main

    with pytest.raises(SystemExit) as error:
        main(
            [
                "--state",
                "MN",
                "--db-root",
                str(tmp_path),
                "--eaglei",
                "nonsense",
                "--eaglei-source-tz",
                "UTC",
            ]
        )
    assert error.value.code == 2
    assert "YEAR=PATH" in capsys.readouterr().err
    assert not (tmp_path / "grid.duckdb").exists()


def test_context_cli_reports_missing_counties(tmp_path, capsys):
    from pipelines.build_state_context import main

    source = tmp_path / "outages.csv"
    source.write_text(
        "fips_code,county,state,customers_out,run_start_time\n27001,Aitkin,Minnesota,2,2024-01-01 00:00:00\n"
    )
    with pytest.raises(SystemExit) as error:
        main(
            [
                "--state",
                "MN",
                "--db-root",
                str(tmp_path),
                "--eaglei",
                f"2024={source}",
                "--eaglei-source-tz",
                "UTC",
            ]
        )
    assert error.value.code == 2
    assert "requires loaded counties for MN" in capsys.readouterr().err


def test_context_build_late_failure_preserves_database_and_parquet(
    tmp_path, monkeypatch
):
    from pipelines import build_state_context

    live = tmp_path / "grid.duckdb"
    con = connect(live)
    seed(con)
    con.close()
    before = live.read_bytes()
    parquet = tmp_path / "parquet"
    parquet.mkdir()
    marker = parquet / "other.parquet"
    marker.write_bytes(b"existing")
    tiger, nri, outages = (
        tmp_path / name for name in ("tiger.zip", "nri.json", "outages.csv")
    )
    tiger.write_bytes(b"fixture")
    nri.write_bytes(b"fixture")
    outages.write_text("invalid_column\ninvalid\n")
    monkeypatch.setattr(
        build_state_context,
        "load_counties",
        lambda con, *args: con.execute(
            "UPDATE counties SET pop = 99 WHERE county_fips = '27001'"
        ),
    )
    monkeypatch.setattr(build_state_context, "load_nri", lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="missing EAGLE-I columns"):
        build_state_context.main(
            [
                "--state",
                "MN",
                "--db-root",
                str(tmp_path),
                "--parquet-dir",
                str(parquet),
                "--tiger",
                str(tiger),
                "--nri",
                str(nri),
                "--eaglei",
                f"2024={outages}",
                "--eaglei-source-tz",
                "UTC",
            ]
        )
    assert live.read_bytes() == before
    assert marker.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".context-stage-*"))


def test_context_build_publishes_scoped_outages_and_preserves_other_tables(tmp_path):
    from pipelines.build_state_context import main

    live = tmp_path / "grid.duckdb"
    con = connect(live)
    seed(con)
    con.execute("CREATE TABLE mn_marker (value INTEGER)")
    con.execute("INSERT INTO mn_marker VALUES (7)")
    con.close()
    source = tmp_path / "outages.csv"
    source.write_text(
        "fips_code,county,state,customers_out,run_start_time\n27001,Aitkin,Minnesota,2,2024-01-01 00:00:00\n"
    )
    arguments = [
        "--state",
        "MN",
        "--db-root",
        str(tmp_path),
        "--parquet-dir",
        str(tmp_path / "parquet"),
        "--eaglei",
        f"2024={source}",
        "--eaglei-source-tz",
        "UTC",
    ]
    assert main(arguments) == 0
    assert main(arguments) == 0
    con = connect(live)
    try:
        assert con.execute("SELECT value FROM mn_marker").fetchone() == (7,)
        assert con.execute("SELECT county_fips FROM eaglei_outages").fetchall() == [
            ("27001",)
        ]
        assert (tmp_path / "parquet" / "eaglei_outages.parquet").exists()
    finally:
        con.close()


def test_coverage_invalid_year_preserves_existing_scope(tmp_path):
    from pipelines.eaglei import load_coverage_history

    con = connect(tmp_path / "grid.duckdb")
    path = tmp_path / "coverage.csv"
    header = "year,state,total_customers,min_covered,max_covered,min_pct_covered,max_pct_covered\n"
    try:
        path.write_text(header + "2024-01-01,MN,10,5,10,50,100\n")
        load_coverage_history(con, path, "MN")
        before = con.execute("SELECT * FROM eaglei_coverage").fetchall()
        path.write_text(header + "invalid,MN,10,5,10,50,100\n")
        with pytest.raises(ValueError, match="valid state/year"):
            load_coverage_history(con, path, "MN")
        assert con.execute("SELECT * FROM eaglei_coverage").fetchall() == before
    finally:
        con.close()


def test_context_cli_publishes_storm_events_and_denominators_for_a_context_state(
    tmp_path, monkeypatch
):
    """The context CLI reaches the same county-grain relations the Texas P0 fills."""
    from pipelines import build_state_context
    from pipelines.build_state_context import main

    live = tmp_path / "grid.duckdb"
    con = connect(live)
    seed(con)
    con.close()
    # The pinned crosswalk editions live in gitignored raw data, so this builds
    # its own catalog over fixture .dbx bytes and their real digests.
    raw = tmp_path / "raw"
    entries = []
    for release, valid_from, valid_until in (
        ("edition-a", "2021-01-01T00:00:00", "2021-06-01T00:00:00"),
        ("edition-b", "2024-01-01T00:00:00", "2024-06-01T00:00:00"),
    ):
        target = raw / "nws_zone_county" / release / f"{release}.dbx"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"MN|001|MPX|Fixture Zone {release}|MN001|Aitkin|27001|C||46.0|-93.0\n",
            encoding="utf-8",
        )
        entries.append(
            {
                "release": release,
                "path": ["nws_zone_county", release, f"{release}.dbx"],
                "valid_from": valid_from,
                "valid_until": valid_until,
                "source_url": f"https://example.invalid/{release}.dbx",
                "sha256": sha256_file(target),
            }
        )
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps({"nws_crosswalk_releases": entries}), encoding="utf-8"
    )
    monkeypatch.setattr(
        build_state_context,
        "_nws_crosswalk_releases",
        lambda root, catalog_path=catalog: _nws_crosswalk_releases(root, catalog_path),
    )
    details = tmp_path / "storm.csv.gz"
    frame = pd.DataFrame(
        [
            {
                "EVENT_ID": 1,
                "STATE": "MINNESOTA",
                "STATE_FIPS": 27,
                "CZ_TYPE": "C",
                "CZ_FIPS": 1,
                "EVENT_TYPE": "Winter Storm",
                "BEGIN_DATE_TIME": "01-JAN-21 06:00:00",
                "END_DATE_TIME": "01-JAN-21 12:00:00",
                "CZ_TIMEZONE": "CST-6",
                "MAGNITUDE": None,
            }
        ]
    )
    frame.to_csv(details, index=False, compression="gzip")
    mcc = tmp_path / "MCC.csv"
    mcc.write_text("County_FIPS,Customers\n27001,1234\n55001,99\n")
    coverage = tmp_path / "coverage.csv"
    coverage.write_text(
        "year,state,total_customers,min_covered,max_covered,min_pct_covered,max_pct_covered\n"
        "2021-01-01,MN,10,5,10,0.5,1.0\n2021-01-01,WI,10,5,10,0.5,1.0\n"
    )
    assert (
        main(
            [
                "--state",
                "MN",
                "--db-root",
                str(tmp_path),
                "--parquet-dir",
                str(tmp_path / "parquet"),
                "--raw-dir",
                str(raw),
                "--storm-events",
                f"2021={details}",
                "--mcc",
                str(mcc),
                "--coverage",
                str(coverage),
            ]
        )
        == 0
    )
    con = connect(live)
    try:
        assert con.execute("SELECT county_fips FROM storm_events").fetchall() == [
            ("27001",)
        ]
        assert con.execute(
            "SELECT county_fips, customers FROM county_customers WHERE source = 'mcc_2022'"
        ).fetchall() == [("27001", 1234)]
        assert con.execute("SELECT state FROM eaglei_coverage").fetchall() == [("MN",)]
    finally:
        con.close()


def test_context_cli_requires_counties_before_storm_events(tmp_path, capsys):
    from pipelines.build_state_context import main

    details = tmp_path / "storm.csv.gz"
    pd.DataFrame(
        [
            {
                "EVENT_ID": 1,
                "STATE": "MINNESOTA",
                "STATE_FIPS": 27,
                "CZ_TYPE": "C",
                "CZ_FIPS": 1,
                "EVENT_TYPE": "Winter Storm",
                "BEGIN_DATE_TIME": "01-JAN-21 06:00:00",
                "END_DATE_TIME": "01-JAN-21 12:00:00",
                "CZ_TIMEZONE": "CST-6",
                "MAGNITUDE": None,
            }
        ]
    ).to_csv(details, index=False, compression="gzip")
    with pytest.raises(SystemExit) as error:
        main(
            [
                "--state",
                "MN",
                "--db-root",
                str(tmp_path),
                "--storm-events",
                f"2021={details}",
            ]
        )
    assert error.value.code == 2
    assert "requires loaded counties for MN" in capsys.readouterr().err

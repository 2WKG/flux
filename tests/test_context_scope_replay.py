import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

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

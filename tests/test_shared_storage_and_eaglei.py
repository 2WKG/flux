from __future__ import annotations

import pandas as pd

from pipelines.db import CONTRACT_TABLES, connect, export_parquet, replace_frame
from pipelines.eaglei import load_eaglei
from pipelines.storm_events import load_storm_events


def _write_eaglei(path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows, columns=[
        "fips_code", "county", "state", "customers_out", "run_start_time", "total_customers",
    ]).to_csv(path, index=False)


def test_shared_store_replaces_empty_slice_and_exports_parquet(tmp_path) -> None:
    con = connect(tmp_path / "grid.duckdb")
    try:
        seed = pd.DataFrame([{"county_fips": "48001", "name": "Anderson", "state": "TX", "pop": 1,
                              "geom_wkb": b"fixture"}])
        replace_frame(con, "counties", seed, source_name="test", source_ref="fixture",
                      fixture_batch_id="test-counties")
        assert replace_frame(con, "counties", seed.iloc[0:0], where="county_fips = '48001'",
                             source_name="test", source_ref="fixture", fixture_batch_id="test-counties") == 0
        assert con.execute("SELECT count(*) FROM counties").fetchone()[0] == 0
        target = tmp_path / "parquet's target"
        written = export_parquet(con, target)
        assert len(written) == len(CONTRACT_TABLES)
        assert all(path.exists() for path in written)
        assert con.execute("SELECT count(*) FROM read_parquet(?)", [str(target / "buses.parquet")]).fetchone()[0] == 0
    finally:
        con.close()


def test_eaglei_replay_uses_source_year_not_utc_year(tmp_path) -> None:
    source = tmp_path / "eaglei_outages_2021.csv"
    _write_eaglei(source, [{
        "fips_code": "48001", "county": "Anderson", "state": "Texas", "customers_out": 7,
        "run_start_time": "2021-12-31 20:00:00", "total_customers": 10,
    }])
    con = connect(tmp_path / "grid.duckdb")
    try:
        counties = pd.DataFrame([{"county_fips": "48001", "name": "Anderson", "state": "TX", "pop": 1,
                                  "geom_wkb": b"fixture"}])
        replace_frame(con, "counties", counties, source_name="test", source_ref="fixture",
                      fixture_batch_id="test-counties")
        assert load_eaglei(con, str(source), 2021, "America/Chicago") == 1
        # This source-year's UTC timestamp lies in 2022, exercising the
        # replacement boundary that cannot safely use EXTRACT(year FROM ts).
        assert con.execute("SELECT EXTRACT(year FROM ts) FROM eaglei_outages").fetchone()[0] == 2022
        _write_eaglei(source, [])
        assert load_eaglei(con, str(source), 2021, "America/Chicago") == 0
        assert con.execute("SELECT count(*) FROM eaglei_outages").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM eaglei_outage_observations").fetchone()[0] == 0
    finally:
        con.close()


def test_legacy_and_minnesota_namespaces_coexist(tmp_path) -> None:
    con = connect(tmp_path / "grid.duckdb")
    try:
        con.execute("CREATE TABLE mn_schema_meta (contract_version TEXT PRIMARY KEY)")
        con.execute("INSERT INTO mn_schema_meta VALUES ('2.0.0-mn')")
        con.close()
        con = connect(tmp_path / "grid.duckdb")
        assert con.execute("SELECT value FROM schema_meta WHERE key = 'contract_version'").fetchone() == ("1.0.0",)
        assert con.execute("SELECT contract_version FROM mn_schema_meta").fetchone() == ("2.0.0-mn",)
    finally:
        con.close()


def test_storm_replay_uses_source_year_not_converted_timestamp_year(tmp_path) -> None:
    detail = tmp_path / "storms.csv.gz"
    crosswalk = tmp_path / "zones.dbx"
    pd.DataFrame([{
        "EVENT_ID": 1, "BEGIN_DATE_TIME": "31-DEC-21 20:00:00", "END_DATE_TIME": "31-DEC-21 21:00:00",
        "EVENT_TYPE": "Winter Storm", "CZ_TYPE": "C", "CZ_FIPS": 1, "STATE_FIPS": 48,
        "CZ_TIMEZONE": "CST-6", "STATE": "TEXAS", "MAGNITUDE": 1.0,
    }]).to_csv(detail, index=False, compression="gzip")
    crosswalk.write_text("TX|001|||Anderson|Anderson|48001|CST-6\n")
    con = connect(tmp_path / "grid.duckdb")
    try:
        counties = pd.DataFrame([{"county_fips": "48001", "name": "Anderson", "state": "TX", "pop": 1,
                                  "geom_wkb": b"fixture"}])
        replace_frame(con, "counties", counties, source_name="test", source_ref="fixture",
                      fixture_batch_id="test-counties")
        assert load_storm_events(con, str(detail), str(crosswalk), 2021) == 1
        assert con.execute("SELECT EXTRACT(year FROM ts_begin) FROM storm_events").fetchone()[0] == 2022
        pd.DataFrame(columns=[
            "EVENT_ID", "BEGIN_DATE_TIME", "END_DATE_TIME", "EVENT_TYPE", "CZ_TYPE", "CZ_FIPS", "STATE_FIPS",
            "CZ_TIMEZONE", "STATE", "MAGNITUDE",
        ]).to_csv(detail, index=False, compression="gzip")
        assert load_storm_events(con, str(detail), str(crosswalk), 2021) == 0
        assert con.execute("SELECT count(*) FROM storm_events").fetchone()[0] == 0
    finally:
        con.close()

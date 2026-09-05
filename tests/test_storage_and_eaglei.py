from __future__ import annotations

import pandas as pd

from pipelines.eaglei import load_eaglei
from pipelines.texas_db import (
    TEXAS_DB_PATH,
    TEXAS_PARQUET_DIR,
    connect,
    export_parquet,
    replace_frame,
)


def test_empty_replacement_removes_the_selected_slice(tmp_path) -> None:
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        con.execute("INSERT INTO counties VALUES ('48001', 'Anderson', 'TX', 1, NULL)")
        empty = pd.DataFrame(columns=["county_fips", "name", "state", "pop", "geom_wkb"])
        assert replace_frame(con, "counties", empty, where="county_fips = '48001'") == 0
        assert con.execute("SELECT count(*) FROM counties").fetchone()[0] == 0
    finally:
        con.close()


def test_texas_storage_defaults_never_target_the_shared_release(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    con = connect()
    try:
        written = export_parquet(con)
    finally:
        con.close()

    assert TEXAS_DB_PATH == "data/duck/texas.duckdb"
    assert TEXAS_PARQUET_DIR == "data/parquet/texas"
    assert tmp_path / TEXAS_DB_PATH != tmp_path / "data/duck/grid.duckdb"
    assert (tmp_path / TEXAS_DB_PATH).exists()
    assert written and all((tmp_path / path).is_relative_to(tmp_path / TEXAS_PARQUET_DIR) for path in written)


def test_export_parquet_uses_a_copy_target_duckdb_accepts(tmp_path) -> None:
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        target = tmp_path / "parquet's target"
        written = export_parquet(con, str(target))
        assert len(written) == 13
        assert all(path.exists() for path in written)
        assert con.execute("SELECT count(*) FROM read_parquet(?)", [str(target / "buses.parquet")]).fetchone()[0] == 0
    finally:
        con.close()


def _write_eaglei(path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows, columns=[
        "fips_code", "county", "state", "customers_out", "run_start_time", "total_customers",
    ]).to_csv(path, index=False)


def test_eaglei_sql_loader_replaces_an_empty_annual_slice(tmp_path) -> None:
    source = tmp_path / "eaglei_outages_2021.csv"
    _write_eaglei(source, [{
        "fips_code": "48001", "county": "Anderson", "state": "Texas", "customers_out": 7,
        "run_start_time": "2021-02-16 19:00:00", "total_customers": 10,
    }])
    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        assert load_eaglei(con, str(source), 2021, "America/Chicago") == 1
        assert con.execute("SELECT county_fips, ts, customers_out FROM eaglei_outages").fetchall() == [
            ("48001", pd.Timestamp("2021-02-17 01:00:00"), 7),
        ]
        assert con.execute(
            "SELECT customers FROM county_customers WHERE source = 'eaglei_file'"
        ).fetchall() == [(10,)]

        _write_eaglei(source, [])
        assert load_eaglei(con, str(source), 2021, "America/Chicago") == 0
        assert con.execute("SELECT count(*) FROM eaglei_outages").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM eaglei_outage_observations").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM county_customers WHERE source = 'eaglei_file'").fetchone()[0] == 0
        assert con.execute(
            "SELECT raw_tx_rows, valid_rows FROM eaglei_ingest_quality WHERE source_year = 2021"
        ).fetchall() == [(0, 0)]
    finally:
        con.close()

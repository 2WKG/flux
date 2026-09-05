from __future__ import annotations

import pandas as pd
import pytest

from pipelines import eaglei
from pipelines.db import connect, replace_frame


def _seed_county(con) -> None:
    county = pd.DataFrame([{
        "county_fips": "48001", "name": "Anderson", "state": "TX", "pop": 1, "geom_wkb": b"fixture",
    }])
    replace_frame(con, "counties", county, source_name="test", source_ref="fixture", fixture_batch_id="test")


def _write(path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows, columns=[
        "fips_code", "county", "state", "customers_out", "run_start_time", "total_customers",
    ]).to_csv(path, index=False)


def test_streams_eaglei_and_selects_latest_actual_denominator(tmp_path, monkeypatch) -> None:
    source = tmp_path / "eaglei_outages_2021.csv"
    _write(source, [
        {"fips_code": "48001", "county": "Anderson", "state": "Texas", "customers_out": 7,
         "run_start_time": "2021-12-31 19:00:00", "total_customers": 10},
        {"fips_code": "48001", "county": "Anderson", "state": "Texas", "customers_out": 8,
         "run_start_time": "2021-12-31 20:00:00", "total_customers": 12},
    ])
    con = connect(tmp_path / "grid.duckdb")
    try:
        _seed_county(con)
        monkeypatch.setattr(eaglei.pd, "read_csv", lambda *_args, **_kwargs: pytest.fail("annual CSV hit pandas"))
        assert eaglei.load_eaglei(con, str(source), 2021, "America/Chicago") == 2
        assert con.execute("SELECT customers FROM county_customers WHERE source = 'eaglei_file'").fetchone() == (12,)
        assert con.execute("SELECT EXTRACT(year FROM ts) FROM eaglei_outages ORDER BY ts DESC LIMIT 1").fetchone() == (2022,)
        assert eaglei.load_eaglei(con, str(source), 2021, "America/Chicago") == 2
        assert con.execute("SELECT count(*) FROM eaglei_outages").fetchone() == (2,)
        assert con.execute("SELECT count(*) FROM county_customers WHERE source = 'eaglei_file'").fetchone() == (1,)
    finally:
        con.close()


def test_empty_source_year_removes_prior_slice_without_pandas(tmp_path, monkeypatch) -> None:
    source = tmp_path / "eaglei_outages_2021.csv"
    _write(source, [{"fips_code": "48001", "county": "Anderson", "state": "Texas", "customers_out": 7,
                     "run_start_time": "2021-02-16 19:00:00", "total_customers": 10}])
    con = connect(tmp_path / "grid.duckdb")
    try:
        _seed_county(con)
        monkeypatch.setattr(eaglei.pd, "read_csv", lambda *_args, **_kwargs: pytest.fail("annual CSV hit pandas"))
        eaglei.load_eaglei(con, str(source), 2021, "America/Chicago")
        _write(source, [])
        assert eaglei.load_eaglei(con, str(source), 2021, "America/Chicago") == 0
        assert con.execute("SELECT count(*) FROM eaglei_outages").fetchone() == (0,)
        assert con.execute("SELECT count(*) FROM county_customers WHERE source = 'eaglei_file'").fetchone() == (0,)
    finally:
        con.close()


def test_duplicate_county_timestamp_rejects_before_replacing_slice(tmp_path) -> None:
    source = tmp_path / "eaglei_outages_2021.csv"
    _write(source, [{"fips_code": "48001", "county": "Anderson", "state": "Texas", "customers_out": 7,
                     "run_start_time": "2021-02-16 19:00:00", "total_customers": 10}])
    con = connect(tmp_path / "grid.duckdb")
    try:
        _seed_county(con)
        eaglei.load_eaglei(con, str(source), 2021, "America/Chicago")
        _write(source, [
            {"fips_code": "48001", "county": "Anderson", "state": "Texas", "customers_out": 7,
             "run_start_time": "2021-02-16 19:00:00", "total_customers": 10},
            {"fips_code": "48001", "county": "Anderson", "state": "Texas", "customers_out": 8,
             "run_start_time": "2021-02-16 19:00:00", "total_customers": 12},
        ])
        with pytest.raises(ValueError, match="duplicate"):
            eaglei.load_eaglei(con, str(source), 2021, "America/Chicago")
        assert con.execute("SELECT customers_out FROM eaglei_outages").fetchone() == (7,)
    finally:
        con.close()

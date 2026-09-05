from __future__ import annotations

import pandas as pd

from pipelines.db import connect
from pipelines.eia930 import load_eia930


def _write_eia930(path, timestamp: str, demand: int, adjusted: int | None = None) -> None:
    pd.DataFrame({
        "Balancing Authority": ["ERCO"],
        "UTC Time at End of Hour": [timestamp],
        "Demand (MW)": [demand],
        "Demand (MW) (Adjusted)": [adjusted],
    }).to_csv(path, index=False)


def test_partial_eia930_reload_preserves_other_ba_hours(tmp_path) -> None:
    early = tmp_path / "EIA930_BALANCE_2021_Jan_Jun.csv"
    later = tmp_path / "EIA930_BALANCE_2024_Jul_Dec.csv"
    _write_eia930(early, "2021-02-15 07:00:00+00:00", 65_255)
    _write_eia930(later, "2024-07-08 09:00:00+00:00", 12_000, 11_900)

    con = connect(str(tmp_path / "grid.duckdb"))
    try:
        load_eia930(con, [str(early)])
        load_eia930(con, [str(later)])

        assert con.execute(
            "SELECT ts, demand_mw FROM ba_load_hourly WHERE ba_code = 'ERCO' ORDER BY ts"
        ).fetchall() == [
            (pd.Timestamp("2021-02-15 07:00:00"), 65_255.0),
            (pd.Timestamp("2024-07-08 09:00:00"), 11_900.0),
        ]
        assert con.execute(
            "SELECT count(*) FROM ba_operations_hourly WHERE ba_code = 'ERCO'"
        ).fetchone()[0] == 2
        assert con.execute(
            "SELECT source_release, source_file, rows_loaded FROM ingest_log "
            "WHERE source = 'eia930' ORDER BY source_release"
        ).fetchall() == [
            ("2021_h1", "EIA930_BALANCE_2021_Jan_Jun.csv", 1),
            ("2024_h2", "EIA930_BALANCE_2024_Jul_Dec.csv", 1),
        ]
    finally:
        con.close()

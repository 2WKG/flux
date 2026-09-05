"""EIA-930 hourly BA demand and compact operations-context loader."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pipelines.db import contract_frame, log_artifact


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce") if column in frame else pd.Series(pd.NA, index=frame.index)


def _upsert_frame(con, table: str, frame: pd.DataFrame, *, source_ref: str) -> int:
    """Apply incoming BA-hours without removing history from other source files."""
    con.register("_incoming", contract_frame(frame, table, source_name="eia930", source_ref=source_ref,
                                              source_version="p0", fixture_batch_id="p0-eia930"))
    try:
        con.execute(f"INSERT OR REPLACE INTO {table} BY NAME SELECT * FROM _incoming")
    finally:
        con.unregister("_incoming")
    return len(frame)


def load_eia930(con, csv_paths: list[str], ba_codes: tuple[str, ...] = ("ERCO", "EPE", "SWPP", "MISO")) -> int:
    operations: list[pd.DataFrame] = []
    for filename in csv_paths:
        path = Path(filename)
        raw = pd.read_csv(path, dtype={"Balancing Authority": "string"}, low_memory=False)
        required = {"Balancing Authority", "UTC Time at End of Hour", "Demand (MW)"}
        if missing := required - set(raw.columns):
            raise ValueError(f"{path.name} missing EIA-930 columns: {sorted(missing)}")
        rows = raw[raw["Balancing Authority"].isin(ba_codes)].copy()
        timestamp = pd.to_datetime(rows["UTC Time at End of Hour"], utc=True, errors="coerce")
        if timestamp.isna().any():
            raise ValueError(f"{path.name} has unparseable EIA-930 UTC timestamps")
        operations.append(pd.DataFrame({
            "ba_code": rows["Balancing Authority"].astype(str), "ts": timestamp.dt.tz_localize(None),
            "demand_raw_mw": _numeric(rows, "Demand (MW)"),
            "demand_adjusted_mw": _numeric(rows, "Demand (MW) (Adjusted)"),
            "demand_imputed_mw": _numeric(rows, "Demand (MW) (Imputed)"),
            "demand_forecast_mw": _numeric(rows, "Demand Forecast (MW)"),
            "net_generation_mw": _numeric(rows, "Net Generation (MW)"),
            "total_interchange_mw": _numeric(rows, "Total Interchange (MW)"),
            "valid_dibas_mw": _numeric(rows, "Sum(Valid DIBAs) (MW)"),
        }))
    combined = pd.concat(operations, ignore_index=True)
    if combined.duplicated(["ba_code", "ts"]).any():
        raise ValueError("EIA-930 source files overlap on BA/hour")
    contracts = combined[["ba_code", "ts"]].copy()
    contracts["demand_mw"] = combined.demand_adjusted_mw.fillna(combined.demand_raw_mw)
    if contracts.demand_mw.isna().any():
        raise ValueError("EIA-930 has demand rows without adjusted or raw demand")
    # A build may receive one six-month file at a time.  Replacing the whole BA
    # slice here would silently erase all other periods already curated.
    con.execute("BEGIN TRANSACTION")
    try:
        _upsert_frame(con, "ba_load_hourly", contracts, source_ref=";".join(Path(path).name for path in csv_paths))
        _upsert_frame(con, "ba_operations_hourly", combined, source_ref=";".join(Path(path).name for path in csv_paths))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    for filename in csv_paths:
        log_artifact(con, source="eia930", source_release=Path(filename).stem, path=filename,
                     rows_loaded=len(combined), schema_fingerprint="BA,UTC end hour,demand,forecast,generation,interchange")
    return len(contracts)

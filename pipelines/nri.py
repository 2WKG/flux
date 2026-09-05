"""FEMA National Risk Index county loader with a compact long-form hazard helper."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

from pipelines.common import fips5
from pipelines.texas_db import log_artifact, replace_frame

# v1.20 exposes inland flooding as IFLD (not the older RFLD shorthand).
HIGH_VALUE_HAZARDS = ("WNTW", "HRCN", "SWND", "ISTM", "WFIR", "IFLD", "CFLD", "HWAV", "TRND", "LTNG")


def _county_csv(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv") and "count" in name.lower()]
        if not names:
            raise ValueError("NRI zip does not contain a county CSV")
        with archive.open(names[0]) as source:
            return pd.read_csv(source, dtype={"STCOFIPS": "string"}, low_memory=False)


def _county_records(path: Path) -> pd.DataFrame:
    """Read either FEMA's bulk CSV archive or its official ArcGIS response."""
    if path.suffix.lower() == ".zip":
        return _county_csv(path)
    payload = json.loads(path.read_text())
    records = [feature.get("attributes", feature) for feature in payload.get("features", [])]
    if not records:
        raise ValueError("NRI service response did not contain any county records")
    return pd.DataFrame.from_records(records)


def _number(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce") if column in frame else pd.Series(pd.NA, index=frame.index)


def load_nri(con, source_path: str, release: str = "v1.20", state: str = "TX") -> int:
    path = Path(source_path)
    source = _county_records(path)
    selected = source[source["STATEABBRV"].eq(state)].copy()
    selected["county_fips"] = selected["STCOFIPS"].map(fips5)
    selected = selected[selected.county_fips.notna()]
    hazard = pd.DataFrame({
        "county_fips": selected.county_fips,
        "nri_score": _number(selected, "RISK_SCORE"),
        "wildfire_hazard": pd.NA,
        "seismic_pga": pd.NA,
    })
    replace_frame(con, "hazard_static", hazard, where="county_fips LIKE '48%'")
    # Population belongs in the canonical county table, while the source remains in NRI provenance.
    population = pd.DataFrame({"county_fips": selected.county_fips, "pop": _number(selected, "POPULATION").astype("Int64")})
    con.register("_nri_pop", population)
    try:
        con.execute("UPDATE counties AS c SET pop = p.pop FROM _nri_pop AS p WHERE c.county_fips = p.county_fips")
    finally:
        con.unregister("_nri_pop")

    records: list[pd.DataFrame] = []
    for code in HIGH_VALUE_HAZARDS:
        score, rating, eal = f"{code}_RISKS", f"{code}_RISKR", f"{code}_EALT"
        if score not in selected:
            continue
        records.append(pd.DataFrame({
            "county_fips": selected.county_fips, "hazard_code": code,
            "risk_score": _number(selected, score), "risk_rating": selected.get(rating),
            "eal_value": _number(selected, eal), "source_release": release,
        }))
    if records:
        replace_frame(con, "nri_hazards", pd.concat(records, ignore_index=True), where=f"source_release = '{release}'")
    log_artifact(con, source="fema_nri", source_release=release, path=path, rows_loaded=len(hazard),
                 schema_fingerprint="STCOFIPS,POPULATION,RISK_SCORE,hazard risk/eal columns")
    return len(hazard)

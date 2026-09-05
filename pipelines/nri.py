"""FEMA National Risk Index county loader with a compact long-form hazard helper."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

from pipelines.common import fips5
from pipelines.db import log_artifact, replace_frame
from pipelines.state_scope import StateScope, scope


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


def load_nri(con, source_path: str, release: str = "v1.20", states=None, *, state: str | None = None) -> int:
    path = Path(source_path)
    if state is not None:
        if states is not None: raise ValueError("pass state or states, not both")
        states = state
    selected_scope = states if isinstance(states, StateScope) else scope(states)
    source = _county_records(path)
    selected = source[source["STATEABBRV"].isin(selected_scope.source_values("fema_nri"))].copy()
    selected["county_fips"] = selected["STCOFIPS"].map(fips5)
    if selected.county_fips.isna().any() or not selected.county_fips.str[:2].isin(selected_scope.fips).all():
        raise ValueError("NRI has invalid or inconsistent county FIPS")
    population_values = _number(selected, "POPULATION")
    if population_values.isna().any() or (population_values < 0).any():
        raise ValueError("NRI population is required and must be nonnegative")
    hazard = pd.DataFrame({
        "county_fips": selected.county_fips,
        "nri_score": _number(selected, "RISK_SCORE"),
        "wildfire_hazard": pd.NA,
        "seismic_pga": pd.NA,
    })
    state_where = selected_scope.county_where()
    replace_frame(con, "hazard_static", hazard, where=state_where, source_name="fema_nri",
                  source_ref=path.name, source_version=release, fixture_batch_id=f"p0-nri-{release}-{selected_scope.slug}")
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
    helper = pd.concat(records, ignore_index=True) if records else pd.DataFrame()
    escaped_release = release.replace("'", "''")
    replace_frame(con, "nri_hazards", helper, where=f"source_release = '{escaped_release}' AND ({state_where})")
    log_artifact(con, source="fema_nri", source_release=release, path=path, rows_loaded=len(hazard),
                 schema_fingerprint="STCOFIPS,POPULATION,RISK_SCORE,hazard risk/eal columns")
    return len(hazard)

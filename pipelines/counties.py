"""Census TIGER county geometry loader."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from pipelines.common import fips5
from pipelines.db import log_artifact, replace_frame
from pipelines.nri import _county_records
from pipelines.state_scope import StateScope, scope


def load_counties(con, tiger_zip: str, nri_source: str, states=None, vintage: str = "2024") -> int:
    path = Path(tiger_zip)
    selected_scope = states if isinstance(states, StateScope) else scope(states)
    counties = gpd.read_file(f"zip://{path}")
    selected = counties[counties["STATEFP"].astype(str).str.zfill(2).isin(selected_scope.fips)].copy().to_crs(4326)
    nri = _county_records(Path(nri_source))
    population = pd.to_numeric(nri.get("POPULATION"), errors="coerce")
    population_by_fips = pd.Series(population.to_numpy(), index=nri["STCOFIPS"].map(fips5))
    selected_population = selected["GEOID"].map(population_by_fips)
    if selected_population.isna().any() or (selected_population < 0).any():
        raise ValueError("NRI population is required for every loaded canonical county")
    state_abbr = {state.fips: state.usps for state in selected_scope.states}
    frame = pd.DataFrame({
        "county_fips": selected["GEOID"].astype(str).str.zfill(5),
        "name": selected["NAME"], "state": selected["STATEFP"].map(state_abbr).fillna(selected["STATEFP"]),
        "pop": selected_population.astype("int64"),
        "geom_wkb": selected.geometry.to_wkb(),
    })
    meta = pd.DataFrame({
        "county_fips": selected["GEOID"].astype(str).str.zfill(5), "tiger_vintage": vintage,
        "aland_m2": selected["ALAND"], "awater_m2": selected["AWATER"],
    })
    # P0 is Texas; keeping the replacement scoped to selected postal states makes later expansion safe.
    postal_states = selected_scope.usps
    quoted = ", ".join(repr(state) for state in postal_states)
    rows = replace_frame(con, "counties", frame, where=f"state IN ({quoted})", source_name="census_tiger_county+fema_nri",
                         source_ref=f"{path.name};{Path(nri_source).name}", source_version=f"{vintage};v1.20",
                         fixture_batch_id=f"p0-tiger-nri-{vintage}-{selected_scope.slug}")
    con.execute("DELETE FROM county_geo_meta WHERE tiger_vintage = ? AND substr(county_fips,1,2) IN (" + ", ".join("?" for _ in selected_scope.fips) + ")", [vintage, *selected_scope.fips])
    if not meta.empty:
        con.register("_county_meta", meta)
        try:
            con.execute("INSERT INTO county_geo_meta BY NAME SELECT * FROM _county_meta")
        finally:
            con.unregister("_county_meta")
    log_artifact(con, source="census_tiger_county", source_release=vintage, path=path,
                 rows_loaded=rows, schema_fingerprint="GEOID,NAME,STUSPS,ALAND,AWATER,geometry")
    return rows

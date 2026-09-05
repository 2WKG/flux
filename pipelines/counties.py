"""Census TIGER county geometry loader."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from pipelines.texas_db import log_artifact, replace_frame


def load_counties(con, tiger_zip: str, states: tuple[str, ...] = ("48",), vintage: str = "2024") -> int:
    path = Path(tiger_zip)
    counties = gpd.read_file(f"zip://{path}")
    selected = counties[counties["STATEFP"].isin(states)].copy().to_crs(4326)
    state_abbr = {"48": "TX"}
    frame = pd.DataFrame({
        "county_fips": selected["GEOID"].astype(str).str.zfill(5),
        "name": selected["NAME"], "state": selected["STATEFP"].map(state_abbr).fillna(selected["STATEFP"]), "pop": None,
        "geom_wkb": selected.geometry.to_wkb(),
    })
    meta = pd.DataFrame({
        "county_fips": selected["GEOID"].astype(str).str.zfill(5), "tiger_vintage": vintage,
        "aland_m2": selected["ALAND"], "awater_m2": selected["AWATER"],
    })
    # P0 is Texas; keeping the replacement scoped to selected postal states makes later expansion safe.
    postal_states = tuple(sorted(frame.state.unique()))
    quoted = ", ".join(repr(state) for state in postal_states)
    rows = replace_frame(con, "counties", frame, where=f"state IN ({quoted})")
    replace_frame(con, "county_geo_meta", meta, where=f"tiger_vintage = '{vintage}'")
    log_artifact(con, source="census_tiger_county", source_release=vintage, path=path,
                 rows_loaded=rows, schema_fingerprint="GEOID,NAME,STUSPS,ALAND,AWATER,geometry")
    return rows

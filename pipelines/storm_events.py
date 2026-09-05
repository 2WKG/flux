"""NOAA Storm Events loader with explicit county versus forecast-zone lineage."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pipelines.common import fips5, utc_naive
from pipelines.db import log_artifact, replace_frame

# Storm Events timestamps use local *standard* time year-round.  The Texas-only
# loader maps NOAA's POSIX-style labels to fixed-offset IANA zones (whose signs
# are intentionally reversed) so daylight saving time is never applied.
_TEXAS_CZ_TIMEZONES = {
    "CST-6": "Etc/GMT+6",
    "MST-7": "Etc/GMT+7",
}


def _cz_timezone(value: object) -> str:
    """Return the IANA timezone documented by a NOAA CZ_TIMEZONE value."""
    if value is None or pd.isna(value):
        raise ValueError("Storm Events row is missing CZ_TIMEZONE")
    label = str(value).strip().upper()
    try:
        return _TEXAS_CZ_TIMEZONES[label]
    except KeyError as error:
        raise ValueError(f"unsupported Storm Events CZ_TIMEZONE {label!r}") from error


def _zone_crosswalk(path: str | Path) -> dict[str, list[str]]:
    raw = pd.read_csv(path, sep="|", header=None, dtype="string")
    # NWS correlation layout: state|zone|cwa|name|state_zone|county|fips|timezone|…
    texas = raw[raw[0].eq("TX")]
    mapping: dict[str, list[str]] = {}
    for zone, fips in zip(texas[1], texas[6], strict=True):
        normalized = fips5(fips)
        if normalized:
            mapping.setdefault(str(zone).zfill(3), []).append(normalized)
    return mapping


def load_storm_events(con, detail_gzip: str, zone_crosswalk: str, year: int) -> int:
    path = Path(detail_gzip)
    raw = pd.read_csv(path, compression="gzip", low_memory=False)
    texas = raw[raw["STATE"].eq("TEXAS")].copy()
    required = {
        "EVENT_ID", "BEGIN_DATE_TIME", "END_DATE_TIME", "EVENT_TYPE", "CZ_TYPE", "CZ_FIPS",
        "STATE_FIPS", "CZ_TIMEZONE",
    }
    if missing := required - set(texas.columns):
        raise ValueError(f"Storm Events file missing {sorted(missing)}")
    zones = _zone_crosswalk(zone_crosswalk)
    records: list[dict[str, object]] = []
    for row in texas.itertuples(index=False):
        event = row._asdict()
        source_tz = _cz_timezone(event["CZ_TIMEZONE"])
        if event["CZ_TYPE"] == "C":
            targets = [fips5(int(event["STATE_FIPS"]) * 1000 + int(event["CZ_FIPS"]))]
            method = "direct_county"
        else:
            targets = zones.get(str(int(event["CZ_FIPS"])).zfill(3), [])
            method = "nws_crosswalk"
        for county_fips in targets:
            if county_fips is None:
                continue
            records.append({
                "event_id": int(event["EVENT_ID"]),
                "ts_begin": utc_naive(event["BEGIN_DATE_TIME"], source_tz),
                "ts_end": utc_naive(event["END_DATE_TIME"], source_tz),
                "county_fips": county_fips, "type": event["EVENT_TYPE"],
                "magnitude": pd.to_numeric(event.get("MAGNITUDE"), errors="coerce"),
                "assignment_method": method, "episode_id": event.get("EPISODE_ID"),
                "magnitude_type": event.get("MAGNITUDE_TYPE"), "source_year": year,
            })
    expanded = pd.DataFrame(records)
    if expanded.empty:
        raise ValueError("Storm Events produced no Texas county records")
    contract = expanded[["event_id", "ts_begin", "ts_end", "county_fips", "type", "magnitude"]]
    # Attribute table is intentionally narrow: the compressed raw file retains narratives and all other fields.
    con.execute("""CREATE TABLE IF NOT EXISTS storm_event_attributes(event_id BIGINT, county_fips TEXT,
        source_year INTEGER, episode_id BIGINT, magnitude_type TEXT, assignment_method TEXT,
        PRIMARY KEY(event_id, county_fips, source_year))""")
    attributes = expanded[["event_id", "county_fips", "source_year", "episode_id", "magnitude_type", "assignment_method"]]
    replace_frame(con, "storm_events", contract, where=f"EXTRACT(year FROM ts_begin) = {year}")
    rows = replace_frame(con, "storm_event_attributes", attributes, where=f"source_year = {year}")
    log_artifact(con, source="noaa_storm_events", source_release=str(year), path=path, rows_loaded=rows,
                 schema_fingerprint="event id,time,type,county/zone,magnitude")
    log_artifact(con, source="nws_zone_county", source_release="bp16ap26", path=zone_crosswalk,
                 rows_loaded=len(zones), schema_fingerprint="state,zone,county_fips")
    return rows

"""NOAA Storm Events loader with explicit county versus forecast-zone lineage."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from pipelines.common import fips5, utc_naive
from pipelines.db import log_artifact, replace_frame
from pipelines.state_scope import scope

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


def _zone_crosswalk(path: str | Path, states=None) -> dict[str, list[str]]:
    raw = pd.read_csv(path, sep="|", header=None, dtype="string")
    # NWS correlation layout: state|zone|cwa|name|state_zone|county|fips|timezone|…
    selected = raw[raw[0].isin(scope(states).usps)]
    mapping: dict[str, list[str]] = {}
    for zone, fips in zip(selected[1], selected[6], strict=True):
        normalized = fips5(fips)
        if normalized:
            mapping.setdefault(str(zone).zfill(3), []).append(normalized)
    return mapping


def _scope_events(raw: pd.DataFrame, states=None) -> pd.DataFrame:
    """Select only full state-name rows requested by the caller's scope."""
    return raw[
        raw["STATE"]
        .str.upper()
        .isin(tuple(name.upper() for name in scope(states).names))
    ].copy()


def load_storm_events(
    con, detail_gzip: str, zone_crosswalk: str, year: int, states=None
) -> int:
    path = Path(detail_gzip)
    raw = pd.read_csv(path, compression="gzip", low_memory=False)
    selected_scope = scope(states)
    selected = _scope_events(raw, selected_scope)
    required = {
        "EVENT_ID",
        "BEGIN_DATE_TIME",
        "END_DATE_TIME",
        "EVENT_TYPE",
        "CZ_TYPE",
        "CZ_FIPS",
        "STATE_FIPS",
        "CZ_TIMEZONE",
    }
    if missing := required - set(selected.columns):
        raise ValueError(f"Storm Events file missing {sorted(missing)}")
    zones = _zone_crosswalk(zone_crosswalk, selected_scope)
    records: list[dict[str, object]] = []
    unmatched_zones: dict[str, int] = {}
    for row in selected.itertuples(index=False):
        event = row._asdict()
        source_tz = _cz_timezone(event["CZ_TIMEZONE"])
        if event["CZ_TYPE"] == "C":
            targets = [fips5(int(event["STATE_FIPS"]) * 1000 + int(event["CZ_FIPS"]))]
            method = "direct_county"
        else:
            targets = zones.get(str(int(event["CZ_FIPS"])).zfill(3), [])
            method = "nws_crosswalk"
            if not targets:
                zone = str(int(event["CZ_FIPS"])).zfill(3)
                unmatched_zones[zone] = unmatched_zones.get(zone, 0) + 1
        for county_fips in targets:
            if county_fips is None:
                continue
            records.append(
                {
                    "event_id": int(event["EVENT_ID"]),
                    "ts_begin": utc_naive(event["BEGIN_DATE_TIME"], source_tz),
                    "ts_end": utc_naive(event["END_DATE_TIME"], source_tz),
                    "county_fips": county_fips,
                    "type": event["EVENT_TYPE"],
                    "magnitude": pd.to_numeric(event.get("MAGNITUDE"), errors="coerce"),
                    "assignment_method": method,
                    "episode_id": event.get("EPISODE_ID"),
                    "magnitude_type": event.get("MAGNITUDE_TYPE"),
                    "source_year": year,
                }
            )
    expanded = pd.DataFrame(
        records,
        columns=[
            "event_id",
            "ts_begin",
            "ts_end",
            "county_fips",
            "type",
            "magnitude",
            "assignment_method",
            "episode_id",
            "magnitude_type",
            "source_year",
        ],
    )
    contract = expanded[
        ["event_id", "ts_begin", "ts_end", "county_fips", "type", "magnitude"]
    ]
    # Attribute table is intentionally narrow: the compressed raw file retains narratives and all other fields.
    con.execute("""CREATE TABLE IF NOT EXISTS storm_event_attributes(event_id BIGINT, county_fips TEXT,
        source_year INTEGER, episode_id BIGINT, magnitude_type TEXT, assignment_method TEXT,
        PRIMARY KEY(event_id, county_fips, source_year))""")
    attributes = expanded[
        [
            "event_id",
            "county_fips",
            "source_year",
            "episode_id",
            "magnitude_type",
            "assignment_method",
        ]
    ]
    # Source year is authoritative.  UTC conversion can move an event across
    # a calendar-year boundary, so timestamp predicates are not replay-safe.
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            """DELETE FROM storm_events AS events
               WHERE EXISTS (SELECT 1 FROM storm_event_attributes AS attrs
                             WHERE attrs.source_year = ?
                               AND ({scope})
                               AND attrs.event_id = events.event_id
                               AND attrs.county_fips = events.county_fips)""".format(
                scope=selected_scope.county_where("attrs.county_fips")
            ),
            [year],
        )
        rows = replace_frame(
            con,
            "storm_event_attributes",
            attributes,
            where=f"source_year = {year} AND ({selected_scope.county_where()})",
        )
        incoming = contract.copy()
        incoming["source_name"] = "noaa_storm_events"
        incoming["source_ref"] = path.name
        incoming["source_version"] = str(year)
        incoming["source_retrieved_at"] = None
        incoming["fixture_batch_id"] = f"p0-storm-events-{year}"
        con.register("_storm_events_incoming", incoming)
        try:
            con.execute(
                "INSERT INTO storm_events BY NAME SELECT * FROM _storm_events_incoming"
            )
        finally:
            con.unregister("_storm_events_incoming")
        con.execute(
            "DELETE FROM ingest_warnings WHERE source = ? AND source_key LIKE ?",
            ["noaa_storm_events", f"{year}:zone:%"],
        )
        scope_label = "Texas" if selected_scope.is_texas_only else "scoped"
        for zone, count in unmatched_zones.items():
            con.execute(
                "INSERT INTO ingest_warnings VALUES (?, ?, ?, current_timestamp)",
                [
                    "noaa_storm_events",
                    f"{year}:zone:{zone}",
                    f"{count} {scope_label} zone-type Storm Events had no county crosswalk mapping",
                ],
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    log_artifact(
        con,
        source="noaa_storm_events",
        source_release=str(year),
        path=path,
        rows_loaded=rows,
        schema_fingerprint="event id,time,type,county/zone,magnitude",
    )
    log_artifact(
        con,
        source="nws_zone_county",
        source_release="bp16ap26",
        path=zone_crosswalk,
        rows_loaded=len(zones),
        schema_fingerprint="state,zone,county_fips",
    )
    return rows

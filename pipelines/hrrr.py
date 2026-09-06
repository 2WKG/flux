"""Range-subset HRRR historical weather into the county-hour contract.

The historical source rule is deliberately narrow: instantaneous f00 fields
are valid at ``ts`` while the accumulated f01 fields are initialized at
``ts - 1 hour``.  The checked-in Task7 feasibility manifest declares those
windows; it is not itself a completed ingest receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import xarray as xr

from pipelines.common import utc_now
from pipelines.db import connect, replace_frame
from pipelines.state_scope import StateScope, scope

MANIFEST_PATH = Path("data/sources/texas-hrrr-manifest-feasibility.json")
RAW_DIR = Path("data/raw/hrrr")
INDEX_CACHE = Path("data/parquet/hrrr_county_index.parquet")
S3_ROOT = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
# ``.idx`` keys are ``VAR:level:fcst``.  The trailing forecast descriptor is
# part of the identity, not decoration: a single ``wrfsfcf01`` index carries
# ``WEASD:surface`` twice (``1 hour fcst`` and ``0-1 hour acc fcst``), and the
# ``f00`` index carries ``APCP:surface`` as an all-zero ``0-0 day acc fcst``.
# Dropping it would let a ``VAR:level`` prefix select the wrong message.
ANALYSIS_FIELDS = {
    "wind_u": "UGRD:10 m above ground:anl",
    "wind_v": "VGRD:10 m above ground:anl",
    "gust_ms": "GUST:surface:anl",
    "temp_k": "TMP:2 m above ground:anl",
}
ACCUMULATION_FIELDS = {
    "precip_mm": "APCP:surface:0-1 hour acc fcst",
    "ice_mm": "FRZR:surface:0-1 hour acc fcst",
}
PROVIDER = "NOAA HRRR archive on AWS Open Data"
SOURCE_URL = "https://registry.opendata.aws/noaa-hrrr-pds/"
LICENSE_ACCESS = "U.S. government public data"
CAPTURE_METHOD = "HTTP range request bounded by the published .grib2.idx byte offsets"


@dataclass(frozen=True)
class GribMessage:
    value: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    attrs: dict[str, Any]
    init: datetime
    valid: datetime
    step_hours: int


@dataclass(frozen=True)
class PreparedHour:
    """A fully validated hour which has not touched the database."""

    valid: datetime
    frame: pd.DataFrame
    receipt_path: Path
    receipt_payload: dict[str, Any]
    source_run: dict[str, Any]


def _as_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _windows(manifest_path: Path | None = None) -> dict[str, tuple[datetime, datetime]]:
    manifest_path = manifest_path or MANIFEST_PATH
    try:
        payload = json.loads(manifest_path.read_text())
        declared = payload["fixed_contract_windows"]
        rule = payload["reproducible_manifest_rule"]
    except (OSError, KeyError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"HRRR feasibility manifest is required: {manifest_path}"
        ) from error
    required = ("f00", "f01", "one hour earlier", "APCP", "FRZR")
    if not all(token.lower() in rule.lower() for token in required):
        raise RuntimeError(
            "HRRR feasibility manifest does not declare the required f00/f01 crosswalk"
        )
    result = {}
    for scenario_id, value in declared.items():
        start, end = value.split("..", maxsplit=1)
        result[scenario_id] = (_as_utc(start), _as_utc(end))
    return result


def _url(init: datetime, fxx: int) -> str:
    return f"{S3_ROOT}/hrrr.{init:%Y%m%d}/conus/hrrr.t{init:%H}z.wrfsfcf{fxx:02d}.grib2"


def _index(url: str) -> list[tuple[int, int, str]]:
    response = requests.get(f"{url}.idx", timeout=30)
    response.raise_for_status()
    rows = []
    for line in response.text.splitlines():
        pieces = line.split(":")
        if len(pieces) >= 6:
            rows.append((int(pieces[0]), int(pieces[1]), ":".join(pieces[3:6])))
    return rows


def _message_bounds(url: str, field: str) -> tuple[int, int]:
    rows = _index(url)
    matches = [offset for offset, row in enumerate(rows) if row[2] == field]
    if not matches:
        raise RuntimeError(f"HRRR field {field!r} is absent from {url}.idx")
    if len(matches) > 1:
        raise RuntimeError(
            f"HRRR field {field!r} matches {len(matches)} messages in {url}.idx; "
            "the index key does not identify one message"
        )
    offset = matches[0]
    start = rows[offset][1]
    end = rows[offset + 1][1] - 1 if offset + 1 < len(rows) else -1
    return start, end


def _fetch_message(url: str, field: str, raw_dir: Path) -> tuple[Path, dict[str, Any]]:
    start, end = _message_bounds(url, field)
    headers = {"Range": f"bytes={start}-{'' if end < 0 else end}"}
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    if response.status_code != 206:
        raise RuntimeError(f"HRRR range request was not partial content: {url}")
    content_range = response.headers.get("Content-Range")
    if not content_range:
        raise RuntimeError(f"HRRR range response omitted Content-Range: {url}")
    try:
        unit, range_and_total = content_range.split(" ", maxsplit=1)
        received, total = range_and_total.split("/", maxsplit=1)
        received_start, received_end = (
            int(part) for part in received.split("-", maxsplit=1)
        )
        total_bytes = int(total)
    except (ValueError, TypeError) as error:
        raise RuntimeError(f"malformed HRRR Content-Range {content_range!r}") from error
    if unit != "bytes" or received_start != start or (end >= 0 and received_end != end):
        raise RuntimeError(
            f"HRRR Content-Range does not match requested field: {content_range!r}"
        )
    if (
        received_end < received_start
        or total_bytes <= received_end
        or len(response.content) != received_end - received_start + 1
    ):
        raise RuntimeError(
            "HRRR range response body length does not match Content-Range"
        )
    digest = hashlib.sha256(response.content).hexdigest()
    target = raw_dir / digest[:2] / f"{digest}.grib2"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)
    return target, {
        "url": url,
        "field": field,
        "range": [start, end],
        "etag": response.headers.get("ETag", "").strip('"'),
        "sha256": digest,
        "bytes": len(response.content),
        "object_bytes": total_bytes,
    }


def _decode(path: Path) -> GribMessage:
    dataset = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    try:
        variable = next(iter(dataset.data_vars.values()))
        return GribMessage(
            value=np.asarray(variable.values),
            latitude=np.asarray(dataset.latitude.values),
            longitude=np.asarray(dataset.longitude.values),
            attrs=dict(variable.attrs),
            init=pd.Timestamp(dataset.time.values).to_pydatetime().replace(tzinfo=UTC),
            valid=pd.Timestamp(dataset.valid_time.values)
            .to_pydatetime()
            .replace(tzinfo=UTC),
            step_hours=int(pd.Timedelta(dataset.step.values).total_seconds() // 3600),
        )
    finally:
        dataset.close()


def _grid_signature(latitude: np.ndarray, longitude: np.ndarray) -> str:
    return hashlib.sha256(
        np.stack([latitude, longitude]).astype("float64").tobytes()
    ).hexdigest()


def _county_identity(con, selected: StateScope) -> tuple[pd.DataFrame, str, str | None]:
    counties = con.execute(
        f"SELECT county_fips, geom_wkb FROM counties WHERE {selected.county_where()}"
    ).fetchdf()
    if counties.empty:
        raise ValueError("counties must be loaded before HRRR aggregation")
    digest = hashlib.sha256()
    for row in counties.sort_values("county_fips").itertuples(index=False):
        digest.update(row.county_fips.encode())
        digest.update(bytes(row.geom_wkb))
    vintage = con.execute(
        f"SELECT string_agg(DISTINCT tiger_vintage, ',' ORDER BY tiger_vintage) "
        f"FROM county_geo_meta WHERE {selected.county_where()}"
    ).fetchone()[0]
    return counties, digest.hexdigest(), vintage


def _county_index_from_grid(
    con, latitude: np.ndarray, longitude: np.ndarray, selected: StateScope
) -> pd.DataFrame:
    counties, county_fingerprint, county_vintage = _county_identity(con, selected)
    county_geo = gpd.GeoDataFrame(
        counties[["county_fips"]],
        geometry=gpd.GeoSeries.from_wkb(counties.geom_wkb.map(bytes)),
        crs=4326,
    )
    west, south, east, north = county_geo.total_bounds
    lon = np.where(longitude > 180, longitude - 360, longitude)
    mask = (lon >= west) & (lon <= east) & (latitude >= south) & (latitude <= north)
    positions = np.flatnonzero(mask.ravel())
    cells = gpd.GeoDataFrame(
        {"flat_index": positions},
        geometry=gpd.points_from_xy(
            lon.ravel()[positions], latitude.ravel()[positions]
        ),
        crs=4326,
    )
    joined = gpd.sjoin(cells, county_geo, how="inner", predicate="within")
    return (
        joined[["flat_index", "county_fips"]]
        .sort_values(["county_fips", "flat_index"])
        .assign(
            grid_signature=_grid_signature(latitude, longitude),
            grid_shape=json.dumps(list(latitude.shape)),
            state_scope=selected.slug,
            county_fingerprint=county_fingerprint,
            county_vintage=county_vintage,
        )
    )


def _cache_matches(con, index: pd.DataFrame, selected: StateScope) -> bool:
    if index.empty or not {
        "state_scope",
        "county_fingerprint",
        "grid_signature",
        "grid_shape",
    }.issubset(index.columns):
        return False
    _, fingerprint, _ = _county_identity(con, selected)
    return (
        index.state_scope.nunique() == 1
        and index.state_scope.iloc[0] == selected.slug
        and index.county_fingerprint.nunique() == 1
        and index.county_fingerprint.iloc[0] == fingerprint
    )


def _expected_field(field: str) -> tuple[str, str, str]:
    expected = {
        "UGRD:10 m above ground:anl": ("10u", "instant", "m s**-1"),
        "VGRD:10 m above ground:anl": ("10v", "instant", "m s**-1"),
        "GUST:surface:anl": ("gust", "instant", "m s**-1"),
        "TMP:2 m above ground:anl": ("2t", "instant", "K"),
        "APCP:surface:0-1 hour acc fcst": ("tp", "accum", "kg m**-2"),
        "FRZR:surface:0-1 hour acc fcst": ("frzr", "accum", "kg m**-2"),
    }
    return expected[field]


def _validate_message(
    message: GribMessage,
    *,
    field: str,
    init: datetime,
    lead: int,
    index: pd.DataFrame,
) -> None:
    short_name, step_type, units = _expected_field(field)
    attrs = message.attrs
    if (
        attrs.get("GRIB_shortName") != short_name
        or attrs.get("GRIB_stepType") != step_type
    ):
        raise RuntimeError(f"decoded HRRR field identity does not match {field}")
    if attrs.get("units") != units or attrs.get("GRIB_units") != units:
        raise RuntimeError(f"decoded HRRR units do not match {field}")
    if (
        message.init != init
        or message.valid != init + timedelta(hours=lead)
        or message.step_hours != lead
    ):
        raise RuntimeError(f"decoded HRRR time/lead does not match {field}")
    signature = _grid_signature(message.latitude, message.longitude)
    if signature != str(index.grid_signature.iloc[0]) or json.dumps(
        list(message.value.shape)
    ) != str(index.grid_shape.iloc[0]):
        raise RuntimeError("decoded HRRR grid does not match the county index")


def build_county_index(
    con, cache: str | None = None, states: tuple[str, ...] | StateScope = ("TX",)
) -> pd.DataFrame:
    """Cache grid-cell centroids assigned to selected counties for groupby means."""
    path = Path(cache) if cache is not None else INDEX_CACHE
    if path.exists():
        cached = pd.read_parquet(path)
        if _cache_matches(con, cached, scope(states)):
            return cached
    # A single TMP range message provides the fixed HRRR grid coordinates.
    raw, _ = _fetch_message(
        _url(datetime(2021, 2, 15, tzinfo=UTC), 0), ANALYSIS_FIELDS["temp_k"], RAW_DIR
    )
    message = _decode(raw)
    index = _county_index_from_grid(
        con, message.latitude, message.longitude, scope(states)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    index.to_parquet(path, index=False)
    return index


def _mean_by_county(index: pd.DataFrame, values: np.ndarray) -> pd.Series:
    flattened = np.asarray(values).reshape(-1)
    selected = index.assign(value=flattened[index.flat_index.to_numpy()])
    return selected.groupby("county_fips", sort=True).value.mean()


def _receipt_path(
    raw_dir: Path,
    scenario_id: str,
    valid: datetime,
    source_records: list[dict[str, Any]],
    index_version: str,
) -> Path:
    identity = json.dumps(
        {
            "scenario_id": scenario_id,
            "valid_ts": valid.isoformat(),
            "sources": source_records,
            "index_version": index_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return raw_dir / "receipts" / scenario_id / f"{valid:%Y%m%dT%H%M%SZ}-{digest}.json"


def _logical_name(url: str, field: str) -> str:
    """Name one range subset the way a checked-in source receipt names a file."""
    return f"{url.rsplit('/', maxsplit=1)[-1]}#{field}"


def _cached_messages(
    receipt_path: Path,
) -> tuple[dict[str, Path], list[dict[str, Any]]] | None:
    """Reuse byte-verified raw subsets named by an existing receipt."""
    try:
        files = json.loads(receipt_path.read_text())["files"]
        sources = list(files.values())
    except (AttributeError, OSError, KeyError, json.JSONDecodeError):
        return None
    ordered_fields = [*ANALYSIS_FIELDS.values(), *ACCUMULATION_FIELDS.values()]
    by_field: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for source in sources:
        if not isinstance(source, dict):
            return None
        field, digest = source.get("field"), source.get("sha256")
        if not isinstance(digest, str) or field not in ordered_fields:
            return None
        path = receipt_path.parents[2] / digest[:2] / f"{digest}.grib2"
        # Re-verify the bytes, never the receipt's word for them: a truncated or
        # edited cache file must be refetched rather than silently reused.
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return None
        paths[field] = path
        by_field[field] = source
    if set(paths) != set(ordered_fields):
        return None
    # Rebuild the declared field order; the receipt is written with sorted keys.
    return paths, [by_field[field] for field in ordered_fields]


def _persist_source_run(con, source_run: dict[str, Any]) -> None:
    columns = (
        "scenario_id",
        "valid_ts",
        "source",
        "source_release",
        "source_file",
        "model",
        "grid_signature",
        "analysis_init",
        "analysis_lead_h",
        "accumulation_init",
        "accumulation_lead_h",
        "analysis_url",
        "accumulation_url",
        "analysis_etag",
        "accumulation_etag",
        "analysis_fields_json",
        "accumulation_fields_json",
        "analysis_ranges_json",
        "accumulation_ranges_json",
        "county_index_version",
        "receipt_path",
        "retrieved_at",
        "fallback_kind",
        "loaded_at",
    )
    values = [
        json.dumps(source_run[column], sort_keys=True)
        if column.endswith("_json")
        else source_run[column]
        for column in columns
    ]
    try:
        con.execute(
            f"INSERT OR REPLACE INTO weather_source_runs ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            values,
        )
    except Exception as error:
        raise RuntimeError(
            f"weather_source_runs helper is required for HRRR ingestion: {error!r}"
        ) from error


def bounded_ordered_prepare(
    hours, prepare, write, *, workers: int | None = None
) -> int:
    """Prepare disjoint hours concurrently and commit them in declared order."""
    workers = (
        int(os.environ.get("HRRR_PREPARE_WORKERS", "1")) if workers is None else workers
    )
    if workers < 1:
        raise ValueError("HRRR_PREPARE_WORKERS must be positive")
    iterator = iter(hours)
    pending = {}
    submitted = 0
    completed = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:

        def submit():
            nonlocal submitted
            try:
                hour = next(iterator)
            except StopIteration:
                return False
            pending[pool.submit(prepare, hour)] = submitted
            submitted += 1
            return True

        for _ in range(workers):
            if not submit():
                break
        next_write = 0
        total = 0
        try:
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    completed[pending.pop(future)] = future.result()
                while next_write in completed:
                    total += write(completed.pop(next_write))
                    next_write += 1
                # Bound both queued work and prepared payloads.  In particular,
                # a slow first hour cannot make later decoded GRIB arrays pile up.
                while len(pending) + len(completed) < workers and submit():
                    pass
        except Exception:
            for future in pending:
                future.cancel()
            raise
    return total


def _prepare_hrrr_hour(
    *,
    scenario_id: str,
    valid: datetime,
    index: pd.DataFrame,
    wanted_counties: set[str],
) -> PreparedHour:
    """Fetch, decode, validate, and aggregate one hour without database access."""
    analysis_url, accum_url = _url(valid, 0), _url(valid - timedelta(hours=1), 1)
    decoded: dict[str, GribMessage] = {}
    candidates = sorted(
        (RAW_DIR / "receipts" / scenario_id).glob(f"{valid:%Y%m%dT%H%M%SZ}-*.json")
    )
    cached = next(
        (
            item
            for item in (_cached_messages(path) for path in candidates)
            if item is not None
        ),
        None,
    )
    source_records: list[dict[str, Any]] = [] if cached is None else cached[1]
    for name, field in ANALYSIS_FIELDS.items():
        if cached is None:
            path, receipt = _fetch_message(analysis_url, field, RAW_DIR)
            source_records.append(receipt | {"init": valid.isoformat(), "lead": 0})
        else:
            path = cached[0][field]
        decoded[name] = _decode(path)
        _validate_message(decoded[name], field=field, init=valid, lead=0, index=index)
    for name, field in ACCUMULATION_FIELDS.items():
        if cached is None:
            path, receipt = _fetch_message(accum_url, field, RAW_DIR)
            source_records.append(
                receipt | {"init": (valid - timedelta(hours=1)).isoformat(), "lead": 1}
            )
        else:
            path = cached[0][field]
        decoded[name] = _decode(path)
        _validate_message(
            decoded[name],
            field=field,
            init=valid - timedelta(hours=1),
            lead=1,
            index=index,
        )
    values = {
        "wind_ms": _mean_by_county(
            index, np.hypot(decoded["wind_u"].value, decoded["wind_v"].value)
        ),
        "gust_ms": _mean_by_county(index, decoded["gust_ms"].value),
        "temp_c": _mean_by_county(index, decoded["temp_k"].value - 273.15),
        "precip_mm": _mean_by_county(index, decoded["precip_mm"].value),
        "ice_mm": _mean_by_county(index, decoded["ice_mm"].value),
    }
    frame = pd.DataFrame(values).rename_axis("county_fips").reset_index()
    frame["ts"] = valid.replace(tzinfo=None)
    frame = frame[frame.county_fips.isin(wanted_counties)]
    if set(frame.county_fips) != wanted_counties:
        raise RuntimeError("county index does not cover every requested county")
    receipt_path = _receipt_path(
        RAW_DIR, scenario_id, valid, source_records, str(index.grid_signature.iloc[0])
    )
    analysis_sources = source_records[: len(ANALYSIS_FIELDS)]
    accumulation_sources = source_records[len(ANALYSIS_FIELDS) :]
    source_run = {
        "scenario_id": scenario_id,
        "valid_ts": valid.isoformat(),
        "source": "noaa_hrrr",
        "source_release": "hrrr-sfc-3km",
        "source_file": str(receipt_path),
        "loaded_at": utc_now().replace(tzinfo=UTC).isoformat(),
        "model": "hrrr",
        "grid_signature": str(index.grid_signature.iloc[0]),
        "analysis_init": valid.isoformat(),
        "analysis_lead_h": 0,
        "accumulation_init": (valid - timedelta(hours=1)).isoformat(),
        "accumulation_lead_h": 1,
        "analysis_url": analysis_url,
        "accumulation_url": accum_url,
        "analysis_etag": analysis_sources[0]["etag"],
        "accumulation_etag": accumulation_sources[0]["etag"],
        "analysis_fields_json": {
            item["field"]: item["sha256"] for item in analysis_sources
        },
        "accumulation_fields_json": {
            item["field"]: item["sha256"] for item in accumulation_sources
        },
        "analysis_ranges_json": {
            item["field"]: item["range"] for item in analysis_sources
        },
        "accumulation_ranges_json": {
            item["field"]: item["range"] for item in accumulation_sources
        },
        "county_index_version": str(index.grid_signature.iloc[0]),
        "receipt_path": str(receipt_path),
        "retrieved_at": utc_now().replace(tzinfo=UTC).isoformat(),
        "fallback_kind": None,
    }
    return PreparedHour(
        valid=valid,
        frame=frame,
        receipt_path=receipt_path,
        receipt_payload={
            "retrieved_at": source_run["retrieved_at"],
            "provider": PROVIDER,
            "source_url": SOURCE_URL,
            "license_access": LICENSE_ACCESS,
            "capture_method": CAPTURE_METHOD,
            "scenario_id": scenario_id,
            "valid_ts": valid.isoformat(),
            "files": {
                _logical_name(record["url"], record["field"]): record
                for record in source_records
            },
            "verification": {
                "content_range_matched_request": True,
                "sha256_computed_from_response_body": True,
                "decoded_field_identity_checked": True,
                "grid_signature": str(index.grid_signature.iloc[0]),
                "county_index_version": str(index.grid_signature.iloc[0]),
                "index_path": str(INDEX_CACHE),
            },
            "weather_source_run": source_run,
            "uncertainty": (
                "This receipt covers the retrieved GRIB range subsets and the "
                "county-hour aggregation of this one hour. It is not a validation "
                "of the HRRR model itself."
            ),
        },
        source_run=source_run,
    )


def _write_prepared_hrrr_hour(con, prepared: PreparedHour, selected: StateScope) -> int:
    """Persist one prepared hour in a paired, single-writer transaction."""
    prepared.receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if not prepared.receipt_path.exists():
        temporary_receipt = prepared.receipt_path.with_suffix(".json.tmp")
        temporary_receipt.write_text(
            json.dumps(prepared.receipt_payload, indent=2, sort_keys=True) + "\n"
        )
        temporary_receipt.replace(prepared.receipt_path)
    retrieved_at = _as_utc(prepared.source_run["retrieved_at"])
    con.execute("BEGIN TRANSACTION")
    try:
        rows = replace_frame(
            con,
            "weather_hourly",
            prepared.frame,
            where=(
                f"({selected.county_where()}) AND ts = "
                f"TIMESTAMP '{prepared.valid:%Y-%m-%d %H:%M:%S}'"
            ),
            source_name="noaa_hrrr",
            source_ref=str(prepared.receipt_path),
            source_version="hrrr-sfc-3km",
            source_retrieved_at=retrieved_at,
            fixture_batch_id=(
                f"hrrr-{prepared.source_run['scenario_id']}-{prepared.valid:%Y%m%d%H}"
            ),
        )
        _persist_source_run(con, prepared.source_run)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return rows


def load_hrrr_window(
    con,
    scenario_id: str,
    states: tuple[str, ...] = ("TX",),
    fxx: int = 0,
    *,
    workers: int | None = None,
) -> int:
    """Load a declared historical window using only indexed HTTP range requests."""
    if fxx != 0:
        raise ValueError(
            "historical HRRR uses f00 at valid time; forecast belongs to load_hrrr_forecast"
        )
    selected = scope(states)
    windows = _windows()
    if scenario_id not in windows:
        raise ValueError(f"no declared historical HRRR window for {scenario_id!r}")
    start, end = windows[scenario_id]
    index = build_county_index(con, states=selected)
    wanted_counties = set(
        con.execute(f"SELECT county_fips FROM counties WHERE {selected.county_where()}")
        .fetchdf()
        .county_fips
    )
    if not wanted_counties:
        raise ValueError("counties must be loaded before HRRR aggregation")
    hour_count = int((end - start).total_seconds() // 3600)
    hours = tuple(start + timedelta(hours=offset) for offset in range(hour_count))
    return bounded_ordered_prepare(
        hours,
        lambda valid: _prepare_hrrr_hour(
            scenario_id=scenario_id,
            valid=valid,
            index=index,
            wanted_counties=wanted_counties,
        ),
        lambda prepared: _write_prepared_hrrr_hour(con, prepared, selected),
        workers=workers,
    )


def load_hrrr_forecast(con, run: datetime | None = None, horizon_h: int = 48) -> int:
    raise NotImplementedError(
        "forecast HRRR loading is outside the historical intake slice"
    )


def main(argv: list[str] | None = None) -> int:
    """Explicit entry point: ``python -m pipelines.hrrr --scenario uri_2021``.

    ``pipelines.build`` does not call this.  A declared window is thousands of
    HTTP range requests against a public bucket, so it is run deliberately;
    wiring it into the P0 build order is a separate decision.
    """
    parser = argparse.ArgumentParser(description="Load one declared HRRR window.")
    parser.add_argument("--scenario", required=True, help="declared scenario_id")
    parser.add_argument("--db", default="data/duck/grid.duckdb")
    parser.add_argument(
        "--states",
        action="append",
        help="USPS codes, full names, FIPS, or comma-separated scope (default: Texas)",
    )
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args(argv)
    con = connect(args.db)
    try:
        rows = load_hrrr_window(
            con, args.scenario, scope(args.states), workers=args.workers
        )
    finally:
        con.close()
    print(f"weather_hourly: {rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

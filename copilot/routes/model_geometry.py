"""Read-only full synthetic Texas model geometry for the renderer."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
from pathlib import Path
from typing import Annotated

import duckdb
from fastapi import APIRouter, Query

from copilot.api import UnavailableError

router = APIRouter(prefix="/demo", tags=["synthetic-model"])
_duckdb_path: Path | None = None
_artifact_path = Path(__file__).resolve().parents[2] / "data/artifacts/synthetic_topology/tx/activsg2000-current-v1.json.gz"


def configure_model_geometry(*, duckdb_path: Path) -> None:
    global _duckdb_path
    _duckdb_path = duckdb_path


@router.get("/model")
async def model(
    element_id: Annotated[list[str] | None, Query(max_length=64)] = None,
) -> dict[str, object]:
    """Serve a static synthetic model projection; it does not run a solve."""
    try:
        if _duckdb_path is None:
            raise RuntimeError("synthetic model geometry has no configured database")
        payload = await asyncio.to_thread(_read_or_packaged_geometry, _duckdb_path)
        return _select_elements(payload, element_id)
    except Exception as exc:
        raise UnavailableError(
            "Synthetic model geometry is unavailable.",
            details={"artifact": "synthetic_model_geometry", "reason": "unavailable"},
        ) from exc


def _read_or_packaged_geometry(path: Path) -> dict[str, object]:
    if path.is_file():
        return _read_model_geometry(path, None)
    return _read_packaged_geometry()


def _read_packaged_geometry() -> dict[str, object]:
    manifest_path = _artifact_path.with_suffix(".manifest.json")
    if not _artifact_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(_artifact_path)
    compressed = _artifact_path.read_bytes()
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("compressed_sha256") != hashlib.sha256(compressed).hexdigest():
        raise ValueError("packaged synthetic topology checksum does not match its manifest")
    raw = gzip.decompress(compressed)
    if manifest.get("content_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("packaged synthetic topology content checksum does not match its manifest")
    artifact = json.loads(raw)
    payload = artifact.get("payload")
    if not isinstance(payload, dict) or artifact.get("artifact_id") != "tx:synthetic-topology:activsg2000-current-v1":
        raise ValueError("packaged synthetic topology artifact is invalid")
    return payload


def _read_model_geometry(path: Path, element_ids: list[str] | None) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    con = duckdb.connect(str(path), read_only=True)
    try:
        _require_schema(con)
        bus_rows = con.execute("SELECT bus_id, lon, lat, coord_source FROM buses ORDER BY bus_id").fetchall()
        if not bus_rows or any(str(row[3]) != "tamu_aux" for row in bus_rows):
            raise ValueError("current AUX bus coordinates are unavailable")
        buses = {f"bus:{int(bus_id)}": _point(f"bus:{int(bus_id)}", "bus", int(bus_id), float(lon), float(lat)) for bus_id, lon, lat, _ in bus_rows}
        line_rows = con.execute(
            "SELECT l.line_id, l.from_bus, l.to_bus, l.is_transformer, first.lon, first.lat, second.lon, second.lat "
            "FROM lines AS l JOIN buses AS first ON first.bus_id = l.from_bus "
            "JOIN buses AS second ON second.bus_id = l.to_bus ORDER BY l.line_id"
        ).fetchall()
        branches = {
            (f"impedance:{int(line_id)}" if transformer else f"line:{int(line_id)}"):
            _branch(int(line_id), int(from_bus), int(to_bus), bool(transformer), float(from_lon), float(from_lat), float(to_lon), float(to_lat))
            for line_id, from_bus, to_bus, transformer, from_lon, from_lat, to_lon, to_lat in line_rows
        }
        generator_rows = con.execute("SELECT g.gen_id, g.bus_id, b.lon, b.lat FROM gens AS g JOIN buses AS b ON b.bus_id = g.bus_id ORDER BY g.gen_id").fetchall()
        generators = {f"generator:{int(gen_id)}": _point(f"generator:{int(gen_id)}", "generator", int(bus_id), float(lon), float(lat)) for gen_id, bus_id, lon, lat in generator_rows}
        load_rows = con.execute("SELECT l.load_id, l.bus_id, b.lon, b.lat FROM loads AS l JOIN buses AS b ON b.bus_id = l.bus_id ORDER BY l.load_id").fetchall()
        loads = {f"load:{int(load_id)}": _point(f"load:{int(load_id)}", "load", int(bus_id), float(lon), float(lat)) for load_id, bus_id, lon, lat in load_rows}
    finally:
        con.close()
    return _select_elements(_payload(buses, branches, generators, loads), element_ids)


def _payload(buses: dict[str, object], branches: dict[str, object], generators: dict[str, object], loads: dict[str, object]) -> dict[str, object]:
    all_elements = buses | branches | generators | loads
    return {
        "status": "available",
        "data": {
            "topology": {"label": "synthetic (ACTIVSg2000)", "synthetic": True, "model_mode": "static_topology", "solver": "not_run"},
            "elements": [all_elements[key] for key in sorted(all_elements)],
            "counts": {"buses": len(buses), "branches": len(branches), "lines": sum(key.startswith("line:") for key in branches), "impedance_branches": sum(key.startswith("impedance:") for key in branches)},
            "capabilities": {"selected_component_failure": True},
            "provenance": {"coordinate_source": "tamu_aux", "mapping": "Flux DuckDB synthetic electrical tables with current ACTIVSg2000 AUX bus coordinates", "physical_inventory_equivalence": False},
        },
    }


def _select_elements(payload: dict[str, object], element_ids: list[str] | None) -> dict[str, object]:
    data = payload["data"]
    assert isinstance(data, dict)
    full = data["elements"]
    assert isinstance(full, list)
    by_id = {str(item["element_id"]): item for item in full if isinstance(item, dict) and isinstance(item.get("element_id"), str)}
    requested = sorted(by_id) if element_ids is None else [str(value) for value in element_ids]
    elements = [by_id.get(value, {"element_id": value, "resolved": False, "reason": "unknown synthetic model element"}) for value in requested]
    unresolved = any(not bool(item["resolved"]) for item in elements)
    result = {"status": "partial" if unresolved else "available", "data": {**data, "elements": elements}}
    if unresolved:
        result["reason"] = "one or more requested synthetic elements could not be resolved"
    return result


def _require_schema(con: duckdb.DuckDBPyConnection) -> None:
    tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
    required = {"buses", "lines", "gens", "loads"}
    if not required.issubset(tables):
        raise ValueError("synthetic model tables are unavailable")
    columns = {"buses": {"bus_id", "lon", "lat", "coord_source"}, "lines": {"line_id", "from_bus", "to_bus", "is_transformer"}, "gens": {"gen_id", "bus_id"}, "loads": {"load_id", "bus_id"}}
    for table, needed in columns.items():
        actual = {str(row[1]) for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()}
        if not needed.issubset(actual):
            raise ValueError(f"synthetic model table {table} is incomplete")


def _point(element_id: str, role: str, source_bus_id: int, lon: float, lat: float) -> dict[str, object]:
    return {"element_id": element_id, "resolved": True, "role": role, "source_id": element_id, "source_bus_ids": [source_bus_id], "coordinates": {"lon": lon, "lat": lat}, "geometry": {"type": "Point", "coordinates": [lon, lat]}, "provenance": {"topology": "synthetic (ACTIVSg2000)", "coordinate_source": "tamu_aux"}}


def _branch(line_id: int, from_bus: int, to_bus: int, transformer: bool, from_lon: float, from_lat: float, to_lon: float, to_lat: float) -> dict[str, object]:
    element_id = f"impedance:{line_id}" if transformer else f"line:{line_id}"
    return {"element_id": element_id, "resolved": True, "role": "impedance_branch" if transformer else "line", "source_id": element_id, "source_bus_ids": [from_bus, to_bus], "coordinates": {"from": {"lon": from_lon, "lat": from_lat}, "to": {"lon": to_lon, "lat": to_lat}}, "geometry": {"type": "LineString", "coordinates": [[from_lon, from_lat], [to_lon, to_lat]]}, "provenance": {"topology": "synthetic (ACTIVSg2000)", "coordinate_source": "tamu_aux"}}

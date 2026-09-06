"""Read-only full synthetic Texas model geometry for the renderer."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import duckdb
from fastapi import APIRouter, Query

from copilot.api import UnavailableError

router = APIRouter(prefix="/demo", tags=["synthetic-model"])
_duckdb_path: Path | None = None


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
        return await asyncio.to_thread(_read_model_geometry, _duckdb_path, element_id)
    except Exception as exc:
        raise UnavailableError(
            "Synthetic model geometry is unavailable.",
            details={"artifact": "synthetic_model_geometry", "reason": "unavailable"},
        ) from exc


def _read_model_geometry(
    path: Path, element_ids: list[str] | None
) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    con = duckdb.connect(str(path), read_only=True)
    try:
        _require_schema(con)
        bus_rows = con.execute(
            "SELECT bus_id, lon, lat, coord_source FROM buses ORDER BY bus_id"
        ).fetchall()
        if not bus_rows or any(str(row[3]) != "tamu_aux" for row in bus_rows):
            raise ValueError("current AUX bus coordinates are unavailable")
        buses = {
            f"bus:{int(bus_id)}": _point(
                f"bus:{int(bus_id)}", "bus", int(bus_id), float(lon), float(lat)
            )
            for bus_id, lon, lat, _ in bus_rows
        }
        line_rows = con.execute(
            "SELECT l.line_id, l.from_bus, l.to_bus, l.is_transformer, first.lon, first.lat, second.lon, second.lat "
            "FROM lines AS l JOIN buses AS first ON first.bus_id = l.from_bus "
            "JOIN buses AS second ON second.bus_id = l.to_bus ORDER BY l.line_id"
        ).fetchall()
        branches = {
            (
                f"impedance:{int(line_id)}" if transformer else f"line:{int(line_id)}"
            ): _branch(
                int(line_id),
                int(from_bus),
                int(to_bus),
                bool(transformer),
                float(from_lon),
                float(from_lat),
                float(to_lon),
                float(to_lat),
            )
            for line_id, from_bus, to_bus, transformer, from_lon, from_lat, to_lon, to_lat in line_rows
        }
        generator_rows = con.execute(
            "SELECT g.gen_id, g.bus_id, b.lon, b.lat FROM gens AS g JOIN buses AS b ON b.bus_id = g.bus_id ORDER BY g.gen_id"
        ).fetchall()
        generators = {
            f"generator:{int(gen_id)}": _point(
                f"generator:{int(gen_id)}",
                "generator",
                int(bus_id),
                float(lon),
                float(lat),
            )
            for gen_id, bus_id, lon, lat in generator_rows
        }
        load_rows = con.execute(
            "SELECT l.load_id, l.bus_id, b.lon, b.lat FROM loads AS l JOIN buses AS b ON b.bus_id = l.bus_id ORDER BY l.load_id"
        ).fetchall()
        loads = {
            f"load:{int(load_id)}": _point(
                f"load:{int(load_id)}", "load", int(bus_id), float(lon), float(lat)
            )
            for load_id, bus_id, lon, lat in load_rows
        }
    finally:
        con.close()
    all_elements = buses | branches | generators | loads
    requested = (
        sorted(all_elements)
        if element_ids is None
        else [str(value) for value in element_ids]
    )
    elements = [
        all_elements.get(
            value,
            {
                "element_id": value,
                "resolved": False,
                "reason": "unknown synthetic model element",
            },
        )
        for value in requested
    ]
    unresolved = any(not bool(item["resolved"]) for item in elements)
    return {
        "status": "partial" if unresolved else "available",
        **(
            {"reason": "one or more requested synthetic elements could not be resolved"}
            if unresolved
            else {}
        ),
        "data": {
            "topology": {
                "label": "synthetic (ACTIVSg2000)",
                "synthetic": True,
                "model_mode": "static_topology",
                "solver": "not_run",
            },
            "elements": elements,
            "counts": {
                "buses": len(buses),
                "branches": len(branches),
                "lines": sum(key.startswith("line:") for key in branches),
                "impedance_branches": sum(
                    key.startswith("impedance:") for key in branches
                ),
                "generators": len(generators),
                "loads": len(loads),
            },
            "capabilities": {"selected_component_failure": True},
            "provenance": {
                "coordinate_source": "tamu_aux",
                "mapping": "Flux DuckDB synthetic electrical tables with current ACTIVSg2000 AUX bus coordinates",
                "physical_inventory_equivalence": False,
            },
        },
    }


def _require_schema(con: duckdb.DuckDBPyConnection) -> None:
    tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
    required = {"buses", "lines", "gens", "loads"}
    if not required.issubset(tables):
        raise ValueError("synthetic model tables are unavailable")
    columns = {
        "buses": {"bus_id", "lon", "lat", "coord_source"},
        "lines": {"line_id", "from_bus", "to_bus", "is_transformer"},
        "gens": {"gen_id", "bus_id"},
        "loads": {"load_id", "bus_id"},
    }
    for table, needed in columns.items():
        actual = {
            str(row[1])
            for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()
        }
        if not needed.issubset(actual):
            raise ValueError(f"synthetic model table {table} is incomplete")


def _point(
    element_id: str, role: str, source_bus_id: int, lon: float, lat: float
) -> dict[str, object]:
    return {
        "element_id": element_id,
        "resolved": True,
        "role": role,
        "source_id": element_id,
        "source_bus_ids": [source_bus_id],
        "coordinates": {"lon": lon, "lat": lat},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "provenance": {
            "topology": "synthetic (ACTIVSg2000)",
            "coordinate_source": "tamu_aux",
        },
    }


def _branch(
    line_id: int,
    from_bus: int,
    to_bus: int,
    transformer: bool,
    from_lon: float,
    from_lat: float,
    to_lon: float,
    to_lat: float,
) -> dict[str, object]:
    element_id = f"impedance:{line_id}" if transformer else f"line:{line_id}"
    return {
        "element_id": element_id,
        "resolved": True,
        "role": "impedance_branch" if transformer else "line",
        "source_id": element_id,
        "source_bus_ids": [from_bus, to_bus],
        "coordinates": {
            "from": {"lon": from_lon, "lat": from_lat},
            "to": {"lon": to_lon, "lat": to_lat},
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [[from_lon, from_lat], [to_lon, to_lat]],
        },
        "provenance": {
            "topology": "synthetic (ACTIVSg2000)",
            "coordinate_source": "tamu_aux",
        },
    }

"""Build the ACTIVSg2000 synthetic pandapower network.

The MATPOWER case is the electrical source of truth.  Geography is optional
and is hydrated only from the already-validated, current-version ``buses``
records produced by :mod:`pipelines.activsg`; no historic 2016 coordinate
bundle is read here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
from pandapower.converter.matpower import from_mpc

from twin.contracts import SYNTHETIC_TOPOLOGY_LABEL, SimulationUnavailableError

DEFAULT_CASE_RELATIVE_PATH = Path("data/raw/activsg2000_current/case_ACTIVSg2000.m")
_BASE_NETWORK_CACHE: dict[tuple[str, str | None, int | None, int | None], Any] = {}


def default_case_path() -> Path:
    """Return the conventional current case path or fail with an actionable error."""
    path = Path.cwd() / DEFAULT_CASE_RELATIVE_PATH
    if not path.is_file():
        raise SimulationUnavailableError(
            "ACTIVSg2000 MATPOWER case is unavailable; provide case_path explicitly or "
            f"place the current case at {path}"
        )
    return path


def build_network(
    case_path: str | Path | None = None,
    *,
    db_path: str | Path | None = None,
    f_hz: int = 60,
) -> Any:
    """Import the current ACTIVSg2000 MATPOWER case through ``from_mpc``.

    ``pandapower`` splits this case's 847 voltage-changing branches into
    ``net.impedance``.  We preserve that representation because the cascade
    loop explicitly monitors it.  The returned object has a synthetic label so
    callers cannot mistake it for physical Texas inventory.
    """
    path = Path(case_path) if case_path is not None else default_case_path()
    if not path.is_file():
        raise SimulationUnavailableError(f"MATPOWER case is unavailable: {path}")
    try:
        net = from_mpc(path, f_hz=f_hz)
    except Exception as exc:  # converter errors differ by pandapower release
        raise SimulationUnavailableError(
            f"could not import MATPOWER case {path}: {exc}"
        ) from exc

    net["flux_topology"] = SYNTHETIC_TOPOLOGY_LABEL
    net["flux_case_path"] = str(path)
    _attach_element_ids(net)
    if db_path is not None:
        attach_current_bus_coordinates(net, db_path)
    return net


def cached_base_network(
    case_path: str | Path | None = None,
    *,
    db_path: str | Path | None = None,
    f_hz: int = 60,
) -> Any:
    """Keep one immutable-process baseline for fast callers that deepcopy it.

    This function is internal-facing by convention: callers must never mutate
    the returned network.  :func:`twin.cascade.run_cascade` immediately deep
    copies it before applying any scenario edit.  File mtimes form the cache
    key, so replacing the case or coordinate DB produces a new base network.
    """
    case = Path(case_path) if case_path is not None else default_case_path()
    db = Path(db_path) if db_path is not None else None
    if not case.is_file():
        raise SimulationUnavailableError(f"MATPOWER case is unavailable: {case}")
    if db is not None and not db.is_file():
        raise SimulationUnavailableError(f"coordinate database is unavailable: {db}")
    key = (
        str(case.resolve()),
        str(db.resolve()) if db is not None else None,
        case.stat().st_mtime_ns,
        db.stat().st_mtime_ns if db is not None else None,
    )
    if key not in _BASE_NETWORK_CACHE:
        _BASE_NETWORK_CACHE.clear()
        _BASE_NETWORK_CACHE[key] = build_network(case, db_path=db, f_hz=f_hz)
    return _BASE_NETWORK_CACHE[key]


def _attach_element_ids(net: Any) -> None:
    """Retain original MATPOWER branch and generator positions as stable ids."""
    branch_lookup = net.get("_from_ppc_lookups", {}).get("branch")
    if branch_lookup is not None:
        for source_index, row in branch_lookup.iterrows():
            element_type = str(row["element_type"])
            element = int(row["element"])
            if element_type == "line":
                net.line.loc[element, "flux_element_id"] = (
                    f"line:{int(source_index) + 1}"
                )
            elif element_type == "impedance":
                net.impedance.loc[element, "flux_element_id"] = (
                    f"impedance:{int(source_index) + 1}"
                )
    if "flux_element_id" not in net.line:
        net.line["flux_element_id"] = [f"line:{index + 1}" for index in net.line.index]
    if "flux_element_id" not in net.impedance:
        net.impedance["flux_element_id"] = [
            f"impedance:{index + 1}" for index in net.impedance.index
        ]
    gen_lookup = net.get("_from_ppc_lookups", {}).get("gen")
    if gen_lookup is not None:
        for source_index, row in gen_lookup.iterrows():
            element_type = str(row["element_type"])
            element = int(row["element"])
            source_id = int(source_index) + 1
            if element_type in {"gen", "sgen"}:
                net[element_type].loc[element, "flux_element_id"] = (
                    f"generator:{source_id}"
                )
            elif element_type == "ext_grid":
                net.ext_grid.loc[element, "flux_element_id"] = f"slack:{source_id}"
    if "flux_element_id" not in net.gen:
        net.gen["flux_element_id"] = [
            f"generator:{index + 1}" for index in net.gen.index
        ]
    if "flux_element_id" not in net.sgen:
        net.sgen["flux_element_id"] = [
            f"generator:{index + 1}" for index in net.sgen.index
        ]
    if "flux_element_id" not in net.ext_grid:
        net.ext_grid["flux_element_id"] = [
            f"slack:{index + 1}" for index in net.ext_grid.index
        ]
    net.load["flux_element_id"] = [f"load:{index + 1}" for index in net.load.index]


def attach_current_bus_coordinates(net: Any, db_path: str | Path) -> None:
    """Attach only validated current AUX coordinates from the ingest database.

    The ingest path validates ``ACTIVSg2000.aux`` against the MATPOWER IDs and
    nominal voltages before writing ``coord_source='tamu_aux'``.  A partial or
    differently sourced table is rejected rather than silently mixing the old
    June-2016 bus numbering into the current electrical model.
    """
    path = Path(db_path)
    if not path.is_file():
        raise SimulationUnavailableError(f"coordinate database is unavailable: {path}")
    con = duckdb.connect(str(path), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        if "buses" not in tables:
            raise SimulationUnavailableError("coordinate database has no buses table")
        columns = {
            row[1] for row in con.execute("PRAGMA table_info('buses')").fetchall()
        }
        required_columns = {"bus_id", "name", "base_kv", "lon", "lat", "coord_source"}
        if not required_columns.issubset(columns):
            raise SimulationUnavailableError(
                "coordinate database buses table lacks the current AUX mapping columns"
            )
        frame = con.execute(
            "SELECT bus_id, name, base_kv, lon, lat, coord_source FROM buses "
            "WHERE coord_source = 'tamu_aux' ORDER BY bus_id"
        ).fetchdf()
    finally:
        con.close()
    if frame.empty:
        raise SimulationUnavailableError(
            "current AUX coordinates are unavailable in buses; refusing non-current coordinates"
        )
    if frame.bus_id.duplicated().any() or frame.name.duplicated().any():
        raise SimulationUnavailableError(
            "current AUX coordinate records contain duplicate bus_id or name values"
        )
    required = {str(value) for value in net.bus.name}
    actual = {str(value) for value in frame.name}
    if actual != required:
        raise SimulationUnavailableError(
            "current AUX coordinate names do not exactly match imported MATPOWER buses"
        )
    by_name = frame.set_index("name")
    mismatched = [
        bus_id
        for bus_id in net.bus.index
        if abs(
            float(net.bus.at[bus_id, "vn_kv"])
            - float(by_name.at[str(net.bus.at[bus_id, "name"]), "base_kv"])
        )
        > 1e-4
    ]
    if mismatched:
        raise SimulationUnavailableError(
            "current AUX nominal voltages do not match imported MATPOWER buses"
        )
    net.bus["flux_source_bus_id"] = [
        int(by_name.at[str(net.bus.at[bus_id, "name"]), "bus_id"])
        for bus_id in net.bus.index
    ]
    net.bus.loc[:, "geo"] = [
        json.dumps(
            {
                "type": "Point",
                "coordinates": [
                    float(by_name.at[str(net.bus.at[bus_id, "name"]), "lon"]),
                    float(by_name.at[str(net.bus.at[bus_id, "name"]), "lat"]),
                ],
            }
        )
        for bus_id in net.bus.index
    ]
    net["flux_coordinate_source"] = "tamu_aux"


def network_summary(net: Any) -> dict[str, int | str]:
    """A small, explicit adapter summary useful to build and health callers."""
    return {
        "topology": str(net.get("flux_topology", SYNTHETIC_TOPOLOGY_LABEL)),
        "buses": len(net.bus),
        "lines": len(net.line),
        "impedance_branches": len(net.impedance),
        "loads": len(net.load),
        "generators": len(net.gen),
    }


def model_geometry(net: Any, element_ids: list[str] | None = None) -> dict[str, Any]:
    """Resolve synthetic model elements to current-AUX geometry, never inventory.

    ``net`` must have been built with ``db_path`` so its bus points were
    validated through the current AUX ingest records.  Unknown IDs and missing
    coordinates are returned as explicit unresolved elements instead of a map
    guess.  IDs remain model/MATPOWER identities, never physical assets.
    """
    if "flux_coordinate_source" not in net or "flux_source_bus_id" not in net.bus:
        raise SimulationUnavailableError(
            "model geometry requires build_network(..., db_path=<validated current AUX database>)"
        )
    all_elements: dict[str, tuple[str, int]] = {}
    for table in ("line", "impedance", "gen", "sgen", "ext_grid", "load"):
        if "flux_element_id" not in net[table]:
            raise SimulationUnavailableError(
                "model geometry requires flux element identifiers"
            )
        for index, element_id in net[table].flux_element_id.items():
            all_elements[str(element_id)] = (table, int(index))
    selected = (
        sorted(all_elements)
        if element_ids is None
        else [str(value) for value in element_ids]
    )
    elements: list[dict[str, Any]] = []
    for requested_element_id in selected:
        element_id, record = _resolve_geometry_element(
            net, all_elements, requested_element_id
        )
        if record is None:
            elements.append(
                {
                    "element_id": requested_element_id,
                    "resolved": False,
                    "reason": "unknown synthetic model element",
                }
            )
            continue
        table, index = record
        frame = net[table]
        if table in {"line", "impedance"}:
            from_bus, to_bus = (
                int(frame.at[index, "from_bus"]),
                int(frame.at[index, "to_bus"]),
            )
            first, second = _bus_point(net, from_bus), _bus_point(net, to_bus)
            if first is None or second is None:
                elements.append(
                    {
                        "element_id": element_id,
                        "resolved": False,
                        "reason": "current AUX point unavailable",
                    }
                )
                continue
            geometry: dict[str, Any] = {
                "type": "LineString",
                "coordinates": [first, second],
            }
            coordinates: dict[str, Any] = {
                "from": {"lon": first[0], "lat": first[1]},
                "to": {"lon": second[0], "lat": second[1]},
            }
            source_bus_ids = [
                int(net.bus.at[from_bus, "flux_source_bus_id"]),
                int(net.bus.at[to_bus, "flux_source_bus_id"]),
            ]
        else:
            bus = int(frame.at[index, "bus"])
            point = _bus_point(net, bus)
            if point is None:
                elements.append(
                    {
                        "element_id": element_id,
                        "resolved": False,
                        "reason": "current AUX point unavailable",
                    }
                )
                continue
            geometry = {"type": "Point", "coordinates": point}
            coordinates = {"lon": point[0], "lat": point[1]}
            source_bus_ids = [int(net.bus.at[bus, "flux_source_bus_id"])]
        elements.append(
            {
                "element_id": element_id,
                **(
                    {"requested_element_id": requested_element_id}
                    if requested_element_id != element_id
                    else {}
                ),
                "resolved": True,
                "role": {
                    "line": "line",
                    "impedance": "impedance_branch",
                    "gen": "generator",
                    "sgen": "static_generator",
                    "ext_grid": "grid_forming_slack",
                    "load": "load",
                }[table],
                "pandapower_index": index,
                "source_id": element_id,
                "source_bus_ids": source_bus_ids,
                "coordinates": coordinates,
                "geometry": geometry,
                "provenance": {
                    "topology": SYNTHETIC_TOPOLOGY_LABEL,
                    "coordinate_source": "tamu_aux",
                },
            }
        )
    unresolved = [element for element in elements if not element["resolved"]]
    return {
        "status": "partial" if unresolved else "available",
        **(
            {"reason": "one or more requested synthetic elements could not be resolved"}
            if unresolved
            else {}
        ),
        "data": {
            "topology": {
                "label": SYNTHETIC_TOPOLOGY_LABEL,
                "synthetic": True,
                "solver": "pandapower.rundcpp",
            },
            "elements": elements,
            "capabilities": {"selected_component_failure": True},
            "provenance": {
                "coordinate_source": "tamu_aux",
                "mapping": "pandapower/MATPOWER element ids with current AUX bus coordinates",
                "physical_inventory_equivalence": False,
            },
        },
    }


def _resolve_geometry_element(
    net: Any,
    all_elements: dict[str, tuple[str, int]],
    requested_element_id: str,
) -> tuple[str, tuple[str, int] | None]:
    """Resolve the same one-based table aliases accepted by ``run_cascade``."""
    if requested_element_id in all_elements:
        return requested_element_id, all_elements[requested_element_id]
    prefix, separator, raw_index = requested_element_id.partition(":")
    table = {
        "line": "line",
        "impedance": "impedance",
        "gen": "gen",
        "sgen": "sgen",
        "slack": "ext_grid",
        "load": "load",
    }.get(prefix)
    if not separator or table is None:
        return requested_element_id, None
    try:
        index = int(raw_index) - 1
    except ValueError:
        return requested_element_id, None
    if index not in net[table].index:
        return requested_element_id, None
    canonical = str(net[table].at[index, "flux_element_id"])
    return canonical, (table, index)


def _bus_point(net: Any, bus_id: int) -> list[float] | None:
    raw = net.bus.at[bus_id, "geo"]
    if not isinstance(raw, str):
        return None
    try:
        point = json.loads(raw)
        coordinates = point["coordinates"]
        if point.get("type") != "Point" or len(coordinates) != 2:
            return None
        return [float(coordinates[0]), float(coordinates[1])]
    except (TypeError, ValueError, KeyError):
        return None


if __name__ == "__main__":
    net = build_network()
    print(network_summary(net))

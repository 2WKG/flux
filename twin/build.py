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
        raise SimulationUnavailableError(f"could not import MATPOWER case {path}: {exc}") from exc

    net["flux_topology"] = SYNTHETIC_TOPOLOGY_LABEL
    net["flux_case_path"] = str(path)
    _attach_element_ids(net)
    if db_path is not None:
        attach_current_bus_coordinates(net, db_path)
    return net


def _attach_element_ids(net: Any) -> None:
    """Retain original MATPOWER branch and generator positions as stable ids."""
    branch_lookup = net.get("_from_ppc_lookups", {}).get("branch")
    if branch_lookup is not None:
        for source_index, row in branch_lookup.iterrows():
            element_type = str(row["element_type"])
            element = int(row["element"])
            if element_type == "line":
                net.line.loc[element, "flux_element_id"] = f"line:{int(source_index) + 1}"
            elif element_type == "impedance":
                net.impedance.loc[element, "flux_element_id"] = f"impedance:{int(source_index) + 1}"
    if "flux_element_id" not in net.line:
        net.line["flux_element_id"] = [f"line:{index + 1}" for index in net.line.index]
    if "flux_element_id" not in net.impedance:
        net.impedance["flux_element_id"] = [f"impedance:{index + 1}" for index in net.impedance.index]
    net.gen["flux_element_id"] = [f"generator:{index + 1}" for index in net.gen.index]
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
        columns = {row[1] for row in con.execute("PRAGMA table_info('buses')").fetchall()}
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
        raise SimulationUnavailableError("current AUX coordinate records contain duplicate bus_id or name values")
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
        if abs(float(net.bus.at[bus_id, "vn_kv"]) - float(by_name.at[str(net.bus.at[bus_id, "name"]), "base_kv"])) > 1e-4
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
        json.dumps({"type": "Point", "coordinates": [float(by_name.at[str(net.bus.at[bus_id, "name"]), "lon"]), float(by_name.at[str(net.bus.at[bus_id, "name"]), "lat"])]})
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


if __name__ == "__main__":
    net = build_network()
    print(network_summary(net))

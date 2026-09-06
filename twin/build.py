"""Build a labelled pandapower DC network from the Flux DuckDB grid tables."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandapower as pp

from twin.contracts import (
    SYNTHETIC_TOPOLOGY_LABEL,
    SimulationInputError,
    SimulationUnavailableError,
)

_REQUIRED: dict[str, set[str]] = {
    "buses": {"bus_id", "name", "base_kv", "lon", "lat", "county_fips"},
    "lines": {"line_id", "from_bus", "to_bus", "base_kv", "r_pu", "x_pu", "rate_a_mw", "length_km", "is_transformer"},
    "gens": {"gen_id", "bus_id", "fuel", "pmax_mw"},
    "loads": {"load_id", "bus_id", "p_mw_nominal"},
}
_UNRATED_MVA = 100_000.0


def build_network(db_path: str | Path) -> Any:
    """Read the declared grid tables into a new synthetic pandapower network.

    The source database is opened read-only.  Its numerical topology is
    preserved as lines plus impedance branches for ``is_transformer`` rows;
    no public-inventory connectivity is inferred.
    """
    path = Path(db_path)
    if not path.is_file():
        raise SimulationUnavailableError(f"grid database unavailable: {path}")
    con = duckdb.connect(str(path), read_only=True)
    try:
        _validate_schema(con)
        buses = con.execute("SELECT bus_id, name, base_kv, lon, lat, county_fips FROM buses ORDER BY bus_id").fetchall()
        lines = con.execute(
            "SELECT line_id, from_bus, to_bus, base_kv, r_pu, x_pu, rate_a_mw, length_km, is_transformer FROM lines ORDER BY line_id"
        ).fetchall()
        generators = con.execute("SELECT gen_id, bus_id, fuel, pmax_mw FROM gens ORDER BY gen_id").fetchall()
        loads = con.execute("SELECT load_id, bus_id, p_mw_nominal FROM loads ORDER BY load_id").fetchall()
        critical = _critical_loads(con)
    finally:
        con.close()
    if not buses:
        raise SimulationUnavailableError("grid database has no bus records")

    net = pp.create_empty_network(sn_mva=100.0, f_hz=60.0)
    net["flux_topology"] = SYNTHETIC_TOPOLOGY_LABEL
    net["flux_source_db"] = str(path.resolve())
    net["flux_bus_index"] = {}
    net["flux_element_lookup"] = {}
    net["flux_bus_metadata"] = {}
    net["flux_critical_loads"] = critical
    for bus_id, name, base_kv, lon, lat, county in buses:
        index = pp.create_bus(net, vn_kv=float(base_kv), name=str(name), geo=json.dumps({"type": "Point", "coordinates": [float(lon), float(lat)]}))
        source_id = int(bus_id)
        net.flux_bus_index[source_id] = int(index)
        net.flux_bus_metadata[int(index)] = {"bus_id": source_id, "county_fips": None if county is None else str(county)}

    for line_id, from_bus, to_bus, base_kv, r_pu, x_pu, rate, length, is_transformer in lines:
        first, second = _bus(net, from_bus), _bus(net, to_bus)
        element_id = f"impedance:{int(line_id)}" if bool(is_transformer) else f"line:{int(line_id)}"
        rating = _rating(rate)
        if bool(is_transformer):
            index = pp.create_impedance(net, first, second, rft_pu=float(r_pu), xft_pu=float(x_pu), sn_mva=rating, name=element_id)
            table = "impedance"
        else:
            kv = float(base_kv)
            km = max(float(length or 0.0), 1e-6)
            z_base_ohm = kv * kv / float(net.sn_mva)
            max_i_ka = rating / (3**0.5 * kv)
            index = pp.create_line_from_parameters(net, first, second, km, float(r_pu) * z_base_ohm / km, float(x_pu) * z_base_ohm / km, 0.0, max_i_ka, name=element_id)
            table = "line"
        net[table].at[index, "flux_element_id"] = element_id
        net[table].at[index, "flux_source_line_id"] = int(line_id)
        net.flux_element_lookup[element_id] = (table, int(index))

    # The first declared generator is the reference bus.  Remaining generators
    # retain their capacity but start at zero scheduled injection; callers add
    # explicit injections through immutable edits rather than fabricated dispatch.
    for position, (gen_id, bus_id, fuel, pmax) in enumerate(generators):
        bus = _bus(net, bus_id)
        element_id = f"generator:{int(gen_id)}"
        if position == 0:
            index = pp.create_ext_grid(net, bus, name=element_id)
            table = "ext_grid"
        else:
            index = pp.create_gen(net, bus, p_mw=0.0, vm_pu=1.0, max_p_mw=float(pmax), min_p_mw=0.0, name=element_id)
            table = "gen"
        net[table].at[index, "flux_element_id"] = element_id
        net[table].at[index, "fuel"] = str(fuel)
        net[table].at[index, "pmax_mw"] = float(pmax)
        net.flux_element_lookup[element_id] = (table, int(index))
    for load_id, bus_id, demand in loads:
        element_id = f"load:{int(load_id)}"
        index = pp.create_load(net, _bus(net, bus_id), p_mw=float(demand), q_mvar=0.0, name=element_id)
        net.load.at[index, "flux_element_id"] = element_id
        net.flux_element_lookup[element_id] = ("load", int(index))
    net["flux_input_sha256"] = _network_hash(buses, lines, generators, loads)
    return net


def network_summary(net: Any) -> dict[str, Any]:
    """Return counts and honest source labels for a built network."""
    return {"topology": str(net.get("flux_topology", SYNTHETIC_TOPOLOGY_LABEL)), "buses": len(net.bus), "lines": len(net.line), "impedance_branches": len(net.impedance), "generators": len(net.gen) + len(net.ext_grid), "loads": len(net.load), "input_sha256": net.get("flux_input_sha256")}


def _validate_schema(con: duckdb.DuckDBPyConnection) -> None:
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    missing_tables = sorted(set(_REQUIRED) - tables)
    if missing_tables:
        raise SimulationUnavailableError("grid database missing tables: " + ", ".join(missing_tables))
    missing: list[str] = []
    for table, required in _REQUIRED.items():
        columns = {row[1] for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()}
        missing.extend(f"{table}.{column}" for column in sorted(required - columns))
    if missing:
        raise SimulationUnavailableError("grid database missing fields: " + ", ".join(missing))


def _critical_loads(con: duckdb.DuckDBPyConnection) -> dict[int, tuple[dict[str, str], ...]]:
    if "critical_loads" not in {row[0] for row in con.execute("SHOW TABLES").fetchall()}:
        return {}
    columns = {row[1] for row in con.execute("PRAGMA table_info('critical_loads')").fetchall()}
    required = {"cl_id", "kind", "name", "bus_id"}
    if not required.issubset(columns):
        return {}
    result: dict[int, list[dict[str, str]]] = {}
    for cl_id, kind, name, bus_id in con.execute("SELECT cl_id, kind, name, bus_id FROM critical_loads WHERE bus_id IS NOT NULL ORDER BY cl_id").fetchall():
        result.setdefault(int(bus_id), []).append({"cl_id": str(cl_id), "kind": str(kind), "name": str(name)})
    return {key: tuple(value) for key, value in result.items()}


def _bus(net: Any, source_id: int) -> int:
    try:
        return int(net.flux_bus_index[int(source_id)])
    except KeyError as exc:
        raise SimulationInputError(f"grid row references unknown bus_id {source_id}") from exc


def _rating(value: float | None) -> float:
    return _UNRATED_MVA if value is None or float(value) <= 0 else float(value)


def _network_hash(*frames: object) -> str:
    encoded = json.dumps(frames, default=str, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()

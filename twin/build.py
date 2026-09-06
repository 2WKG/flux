"""Build a labelled pandapower DC network from the Flux DuckDB grid tables."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandapower as pp
from pandapower.converter.pypower.from_ppc import from_ppc

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
        generator_dispatch = _generator_dispatch(con)
        loads = con.execute("SELECT load_id, bus_id, p_mw_nominal FROM loads ORDER BY load_id").fetchall()
        critical = _critical_loads(con)
        native = _native_ppc_data(con)
    finally:
        con.close()
    if not buses:
        raise SimulationUnavailableError("grid database has no bus records")
    if native is not None:
        return _build_native_network(path, buses, lines, generators, loads, critical, native)

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
            # DuckDB carries the source case's branch p.u. values on the
            # network base.  pandapower's impedance table instead stores p.u.
            # on each element's ``sn_mva`` base, matching from_ppc.
            impedance_base = rating / float(net.sn_mva)
            index = pp.create_impedance(net, first, second, rft_pu=float(r_pu) * impedance_base, xft_pu=float(x_pu) * impedance_base, sn_mva=rating, name=element_id)
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

    # The first declared generator is the reference bus.  When the ingest has
    # preserved the native MATPOWER dispatch, keep every remaining generator's
    # scheduled injection as well: otherwise the lone reference would have to
    # supply the whole system and fabricate an immediate overload cascade.
    # Minimal/test databases legitimately omit the optional electrical table;
    # their non-reference generators retain the prior zero schedule.
    for position, (gen_id, bus_id, fuel, pmax) in enumerate(generators):
        bus = _bus(net, bus_id)
        element_id = f"generator:{int(gen_id)}"
        scheduled_p, in_service = generator_dispatch.get(int(gen_id), (0.0, True))
        if position == 0:
            index = pp.create_ext_grid(net, bus, name=element_id, in_service=in_service)
            table = "ext_grid"
        else:
            index = pp.create_gen(net, bus, p_mw=scheduled_p, vm_pu=1.0, max_p_mw=float(pmax), min_p_mw=0.0, name=element_id, in_service=in_service)
            table = "gen"
        net[table].at[index, "flux_element_id"] = element_id
        net[table].at[index, "fuel"] = str(fuel)
        net[table].at[index, "pmax_mw"] = float(pmax)
        net.flux_element_lookup[element_id] = (table, int(index))
    for load_id, bus_id, demand in loads:
        element_id = f"load:{int(load_id)}"
        index = pp.create_load(net, _bus(net, bus_id), p_mw=float(demand), q_mvar=0.0, name=element_id)
        net.load.at[index, "flux_element_id"] = element_id
        net.load.at[index, "flux_nominal_p_mw"] = float(demand)
        net.flux_element_lookup[element_id] = ("load", int(index))
    net["flux_input_sha256"] = _network_hash(buses, lines, generators, loads)
    return net


def network_summary(net: Any) -> dict[str, Any]:
    """Return counts and honest source labels for a built network."""
    return {"topology": str(net.get("flux_topology", SYNTHETIC_TOPOLOGY_LABEL)), "buses": len(net.bus), "lines": len(net.line), "impedance_branches": len(net.impedance), "generators": len(net.gen) + len(net.sgen) + len(net.ext_grid), "loads": len(net.load), "input_sha256": net.get("flux_input_sha256")}


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


def _generator_dispatch(con: duckdb.DuckDBPyConnection) -> dict[int, tuple[float, bool]]:
    """Return source dispatch when the optional native electrical table exists."""
    if "synthetic_generator_electrical" not in {row[0] for row in con.execute("SHOW TABLES").fetchall()}:
        return {}
    columns = {row[1] for row in con.execute("PRAGMA table_info('synthetic_generator_electrical')").fetchall()}
    if not {"gen_id", "p_mw", "status"}.issubset(columns):
        return {}
    return {
        int(gen_id): (float(p_mw), bool(status))
        for gen_id, p_mw, status in con.execute("SELECT gen_id, p_mw, status FROM synthetic_generator_electrical").fetchall()
    }


def _native_ppc_data(con: duckdb.DuckDBPyConnection) -> dict[str, dict[int, tuple[Any, ...]]] | None:
    """Read the optional electrical side tables needed to reproduce the source case."""
    required = {
        "synthetic_bus_electrical": {"bus_id", "bus_type", "pd_mw", "qd_mvar", "gs_mw", "bs_mvar", "vm_pu", "va_deg", "vmin_pu", "vmax_pu"},
        "synthetic_branch_electrical": {"line_id", "b_pu", "tap_ratio", "shift_deg", "status"},
        "synthetic_generator_electrical": {"gen_id", "p_mw", "q_mvar", "qmax_mvar", "qmin_mvar", "pmin_mw", "status"},
    }
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    if not set(required).issubset(tables):
        return None
    for table, columns in required.items():
        available = {row[1] for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()}
        if not columns.issubset(available):
            return None
    return {
        "bus": {int(row[0]): row[1:] for row in con.execute("SELECT bus_id, bus_type, pd_mw, qd_mvar, gs_mw, bs_mvar, vm_pu, va_deg, vmin_pu, vmax_pu FROM synthetic_bus_electrical").fetchall()},
        "branch": {int(row[0]): row[1:] for row in con.execute("SELECT line_id, b_pu, tap_ratio, shift_deg, status FROM synthetic_branch_electrical").fetchall()},
        "gen": {int(row[0]): row[1:] for row in con.execute("SELECT gen_id, p_mw, q_mvar, qmax_mvar, qmin_mvar, pmin_mw, status FROM synthetic_generator_electrical").fetchall()},
    }


def _build_native_network(path: Path, buses: list[tuple[Any, ...]], lines: list[tuple[Any, ...]], generators: list[tuple[Any, ...]], loads: list[tuple[Any, ...]], critical: dict[int, tuple[dict[str, str], ...]], native: dict[str, dict[int, tuple[Any, ...]]]) -> Any:
    """Build through pandapower's MATPOWER converter from DuckDB-held source arrays."""
    try:
        bus = np.zeros((len(buses), 13), dtype=float)
        for index, (bus_id, name, base_kv, lon, lat, county) in enumerate(buses):
            kind, pd_mw, qd_mvar, gs_mw, bs_mvar, vm_pu, va_deg, vmin_pu, vmax_pu = native["bus"][int(bus_id)]
            bus[index] = (bus_id, kind, pd_mw, qd_mvar, gs_mw, bs_mvar, 0.0, vm_pu, va_deg, base_kv, 0.0, vmax_pu, vmin_pu)
        branch = np.zeros((len(lines), 13), dtype=float)
        for index, (line_id, from_bus, to_bus, base_kv, r_pu, x_pu, rate, length, is_transformer) in enumerate(lines):
            b_pu, tap_ratio, shift_deg, status = native["branch"][int(line_id)]
            branch[index] = (from_bus, to_bus, r_pu, x_pu, b_pu, rate, 0.0, 0.0, tap_ratio, shift_deg, status, 0.0, 0.0)
        gen = np.zeros((len(generators), 21), dtype=float)
        for index, (gen_id, bus_id, fuel, pmax) in enumerate(generators):
            p_mw, q_mvar, qmax_mvar, qmin_mvar, pmin_mw, status = native["gen"][int(gen_id)]
            gen[index, :10] = (bus_id, p_mw, q_mvar, qmax_mvar, qmin_mvar, 1.0, 100.0, status, pmax, pmin_mw)
    except KeyError as exc:
        raise SimulationUnavailableError(f"native electrical data missing source id {exc.args[0]}") from exc
    net = from_ppc({"version": "2", "baseMVA": 100.0, "bus": bus, "gen": gen, "branch": branch, "bus_name": np.array([name for _, name, *_ in buses])}, f_hz=60)
    net["flux_topology"] = SYNTHETIC_TOPOLOGY_LABEL
    net["flux_source_db"] = str(path.resolve())
    net["flux_bus_index"] = {}
    net["flux_element_lookup"] = {}
    net["flux_bus_metadata"] = {}
    net["flux_critical_loads"] = critical
    for bus_id, name, base_kv, lon, lat, county in buses:
        source_id = int(bus_id)
        net.bus.at[source_id, "geo"] = json.dumps({"type": "Point", "coordinates": [float(lon), float(lat)]})
        net.flux_bus_index[source_id] = source_id
        net.flux_bus_metadata[source_id] = {"bus_id": source_id, "county_fips": None if county is None else str(county)}
    branch_lookup = net._from_ppc_lookups["branch"]
    for offset, (line_id, *_) in enumerate(lines):
        table = str(branch_lookup.at[offset, "element_type"])
        index = int(branch_lookup.at[offset, "element"])
        element_id = f"impedance:{int(line_id)}" if table == "impedance" else f"line:{int(line_id)}"
        net[table].at[index, "flux_element_id"] = element_id
        net[table].at[index, "flux_source_line_id"] = int(line_id)
        net.flux_element_lookup[element_id] = (table, index)
    generator_lookup = net._from_ppc_lookups["gen"]
    for offset, (gen_id, bus_id, fuel, pmax) in enumerate(generators):
        table = str(generator_lookup.at[offset, "element_type"])
        index = int(generator_lookup.at[offset, "element"])
        element_id = f"generator:{int(gen_id)}"
        net[table].at[index, "flux_element_id"] = element_id
        net[table].at[index, "fuel"] = str(fuel)
        net[table].at[index, "pmax_mw"] = float(pmax)
        net.flux_element_lookup[element_id] = (table, index)
    available_loads: dict[int, list[int]] = {}
    for index, row in net.load.iterrows():
        available_loads.setdefault(int(row.bus), []).append(int(index))
    for load_id, bus_id, demand in loads:
        try:
            index = available_loads[int(bus_id)].pop(0)
        except (KeyError, IndexError) as exc:
            raise SimulationUnavailableError(f"native conversion missing load at bus_id {bus_id}") from exc
        element_id = f"load:{int(load_id)}"
        net.load.at[index, "flux_element_id"] = element_id
        net.load.at[index, "flux_nominal_p_mw"] = float(demand)
        net.flux_element_lookup[element_id] = ("load", index)
    net["flux_input_sha256"] = _network_hash(buses, lines, generators, loads)
    return net


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

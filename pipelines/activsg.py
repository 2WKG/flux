"""Load the current ACTIVSg2000 MATPOWER case plus its matching AUX geography."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import LineString

from pipelines.activsg_aux import read_aux_coords
from pipelines.texas_db import log_artifact, replace_frame


def _numeric_matrix(text: str, name: str) -> np.ndarray:
    match = re.search(rf"mpc\.{re.escape(name)}\s*=\s*\[(.*?)\];", text, flags=re.DOTALL)
    if match is None:
        raise ValueError(f"missing MATPOWER matrix mpc.{name}")
    rows = []
    for line in match.group(1).splitlines():
        line = line.strip().rstrip(";")
        if not line or line.startswith("%"):
            continue
        rows.append([float(value) for value in line.split()])
    return np.asarray(rows, dtype=float)


def _string_cell(text: str, name: str) -> list[str]:
    match = re.search(rf"mpc\.{re.escape(name)}\s*=\s*\{{(.*?)\}};", text, flags=re.DOTALL)
    if match is None:
        raise ValueError(f"missing MATPOWER cell mpc.{name}")
    return re.findall(r"'([^']*)'", match.group(1))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    lat1, lon1, lat2, lon2 = np.radians([lat1, lon1, lat2, lon2])
    return float(2 * radius * np.arcsin(np.sqrt(
        np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )))


def load_activsg(con, aux_path: str, case_path: str) -> dict[str, int]:
    """Populate synthetic contract/helper tables from one validated case pair."""
    case = Path(case_path)
    text = case.read_text(encoding="utf-8", errors="replace")
    buses_raw = _numeric_matrix(text, "bus")
    branch_raw = _numeric_matrix(text, "branch")
    generators_raw = _numeric_matrix(text, "gen")
    bus_names = _string_cell(text, "bus_name")
    fuels = _string_cell(text, "genfuel")
    generator_types = _string_cell(text, "gentype")
    coords = read_aux_coords(aux_path)

    if len(buses_raw) != 2000 or len(coords) != 2000:
        raise ValueError(f"expected 2,000 current-case buses, got case={len(buses_raw)} aux={len(coords)}")
    if len(bus_names) != len(buses_raw) or len(fuels) != len(generators_raw):
        raise ValueError("MATPOWER string cells do not align with numeric matrices")

    bus_ids = buses_raw[:, 0].astype(int)
    if set(bus_ids) != set(coords.bus_id):
        raise ValueError("AUX and MATPOWER bus ID sets differ; refusing mixed case versions")
    coords = coords.set_index("bus_id").loc[bus_ids].reset_index()
    if not np.allclose(coords.base_kv_aux, buses_raw[:, 9], atol=1e-4):
        raise ValueError("AUX and MATPOWER nominal voltages differ; refusing mixed case versions")

    bus_frame = pd.DataFrame({
        "bus_id": bus_ids, "name": bus_names, "base_kv": buses_raw[:, 9],
        "lon": coords.lon, "lat": coords.lat, "county_fips": None, "ba_code": None,
        "coord_source": "tamu_aux", "zone": buses_raw[:, 10].astype(int), "area": buses_raw[:, 6].astype(int),
    })
    bus_electrical = pd.DataFrame({
        "bus_id": bus_ids, "bus_type": buses_raw[:, 1].astype(int), "pd_mw": buses_raw[:, 2],
        "qd_mvar": buses_raw[:, 3], "gs_mw": buses_raw[:, 4], "bs_mvar": buses_raw[:, 5],
        "vm_pu": buses_raw[:, 7], "va_deg": buses_raw[:, 8], "vmax_pu": buses_raw[:, 11], "vmin_pu": buses_raw[:, 12],
    })
    substations = coords[["sub_num", "sub_name", "sub_id", "lon", "lat"]].drop_duplicates("sub_num")

    bus_by_id = bus_frame.set_index("bus_id")
    branch_rows, branch_detail = [], []
    for index, row in enumerate(branch_raw, start=1):
        from_bus, to_bus = int(row[0]), int(row[1])
        from_record, to_record = bus_by_id.loc[from_bus], bus_by_id.loc[to_bus]
        tap = row[8]
        transformer = bool(not np.isclose(from_record.base_kv, to_record.base_kv) or not np.isclose(tap, 0.0))
        length_km = 0.0 if transformer else 1.15 * _haversine_km(from_record.lat, from_record.lon, to_record.lat, to_record.lon)
        branch_rows.append({
            "line_id": index, "from_bus": from_bus, "to_bus": to_bus,
            "base_kv": max(from_record.base_kv, to_record.base_kv), "r_pu": row[2], "x_pu": row[3],
            "rate_a_mw": row[5] if row[5] > 0 else None, "length_km": length_km,
            "geom_wkb": LineString([(from_record.lon, from_record.lat), (to_record.lon, to_record.lat)]).wkb,
            "is_transformer": transformer,
        })
        branch_detail.append({"line_id": index, "b_pu": row[4], "tap_ratio": tap, "shift_deg": row[9], "status": int(row[10])})
    lines = pd.DataFrame(branch_rows)

    generator_ids = np.arange(1, len(generators_raw) + 1)
    gens = pd.DataFrame({"gen_id": generator_ids, "bus_id": generators_raw[:, 0].astype(int), "fuel": fuels,
                         "pmax_mw": generators_raw[:, 8], "eia_plant_id": None})
    gen_detail = pd.DataFrame({
        "gen_id": generator_ids, "p_mw": generators_raw[:, 1], "q_mvar": generators_raw[:, 2],
        "qmax_mvar": generators_raw[:, 3], "qmin_mvar": generators_raw[:, 4], "pmin_mw": generators_raw[:, 9],
        "status": generators_raw[:, 7].astype(int), "generator_type": generator_types,
    })
    load_mask = buses_raw[:, 2] > 0
    loads = pd.DataFrame({
        "load_id": np.arange(1, int(load_mask.sum()) + 1),
        "bus_id": bus_ids[load_mask], "p_mw_nominal": buses_raw[load_mask, 2],
    })

    counts = {
        "buses": replace_frame(con, "buses", bus_frame),
        "lines": replace_frame(con, "lines", lines),
        "gens": replace_frame(con, "gens", gens),
        "loads": replace_frame(con, "loads", loads),
        "synthetic_substations": replace_frame(con, "synthetic_substations", substations),
        "synthetic_bus_electrical": replace_frame(con, "synthetic_bus_electrical", bus_electrical),
        "synthetic_branch_electrical": replace_frame(con, "synthetic_branch_electrical", pd.DataFrame(branch_detail)),
        "synthetic_generator_electrical": replace_frame(con, "synthetic_generator_electrical", gen_detail),
    }
    log_artifact(con, source="activsg2000", source_release="current", path=case, rows_loaded=counts["buses"], schema_fingerprint="matpower-v2")
    log_artifact(con, source="activsg2000", source_release="current", path=aux_path, rows_loaded=counts["synthetic_substations"], schema_fingerprint="powerworld-aux")
    return counts

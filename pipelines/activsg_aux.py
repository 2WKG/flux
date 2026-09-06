"""Parse the coordinate-bearing blocks in a PowerWorld AUX file."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


def _block(text: str, object_name: str) -> str:
    match = re.search(
        rf"DATA \({object_name},\s*\[.*?\]\)\s*\{{(.*?)^\}}",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if match is None:
        raise ValueError(f"missing {object_name} DATA block")
    return match.group(1)


def read_aux_coords(aux_path: str | Path) -> pd.DataFrame:
    """Return one coordinate record per current-version ACTIVSg2000 bus.

    Coordinates are resolved through `SubNum` rather than copied from an older
    incompatible case. The parser intentionally reads only the stable fields
    needed by the curated model.
    """
    text = Path(aux_path).read_text(encoding="utf-8", errors="replace")
    substations: dict[int, dict[str, object]] = {}
    for line in _block(text, "Substation").splitlines():
        match = re.match(
            r'\s*(\d+)\s+"([^"]*)"\s+"([^"]*)"\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)', line
        )
        if match:
            number, name, source_id, lat, lon = match.groups()
            substations[int(number)] = {
                "sub_num": int(number),
                "sub_name": name,
                "sub_id": source_id,
                "lat": float(lat),
                "lon": float(lon),
            }

    rows: list[dict[str, object]] = []
    for line in _block(text, "Bus").splitlines():
        # BusNum, quoted name, nominal kV, then enough tokens to reach SubNum.
        match = re.match(
            r'\s*(\d+)\s+"([^"]*)"\s+([-+0-9.eE]+)\s+.*?\s+(\d+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+"',
            line,
        )
        if match is None:
            continue
        bus_id, bus_name, nominal_kv, sub_num, lat, lon = match.groups()
        record = substations.get(int(sub_num))
        if record is None:
            raise ValueError(f"bus {bus_id} references absent substation {sub_num}")
        rows.append(
            {
                "bus_id": int(bus_id),
                "bus_name": bus_name,
                "base_kv_aux": float(nominal_kv),
                "sub_num": int(sub_num),
                "sub_name": record["sub_name"],
                "sub_id": record["sub_id"],
                "lat": float(lat),
                "lon": float(lon),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty or frame.bus_id.duplicated().any():
        raise ValueError("AUX bus parse yielded no rows or duplicate bus IDs")
    return frame

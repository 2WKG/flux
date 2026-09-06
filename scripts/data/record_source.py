#!/usr/bin/env python3
"""D01 (2WKG-38) — record provider URL, licence and hashes for the case input.

Writes data/sources/activsg2000.json. Uses only the standard library so it runs
before `uv sync` exists on a machine.

Also does a cheap structural check of ACTIVSg2000.aux so the acceptance evidence
is real rather than "the file downloaded": counts the Substation and Bus records
and reports the coordinate extent.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path

RAW = Path("data/raw/activsg2000_current")
OUT = Path("data/sources/activsg2000.json")

PROVIDER = {
    "name": "Texas A&M University — Electric Grid Test Case Repository",
    "case": "ACTIVSg2000 (Synthetic Texas, 2000 bus)",
    "version": "current (post-2016; PowerWorld v21 build 2018-08-30)",
    "page": "https://electricgrids.engr.tamu.edu/electric-grid-test-cases/activsg2000/",
    "download_url": (
        "https://drive.usercontent.google.com/download"
        "?id=1tC-ofbw1EE46hoZeSfiBAWnSAhG0SmVu&export=download&confirm=t"
    ),
    "licence": "Free for commercial or non-commercial use; contains no CEII.",
    "citation": (
        "A.B. Birchfield, T. Xu, K.M. Gegner, K.S. Shetye, T.J. Overbye, "
        "'Grid Structural Characteristics as Validation Criteria for Synthetic "
        "Networks', IEEE Transactions on Power Systems, 2017. "
        "doi:10.1109/TPWRS.2016.2616385"
    ),
    "not_used": (
        "The 'Texas2000_June2016' bundle is a different case version (2,007 buses, "
        "49,776 MW) sharing only 98 of 2,000 bus numbers with this one. Not used."
    ),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _aux_block(text: str, obj: str) -> tuple[list[str], list[list[str]]]:
    """Return (field names, rows) for one AUX `DATA (obj, [f1,f2,...]) { ... }` block.

    Values are whitespace-separated but names are double-quoted and contain
    spaces ("BIG SPRING 5"), so rows must be tokenised with shlex, not split().
    """
    m = re.search(
        rf"DATA\s*\(\s*{obj}\s*,\s*\[(.*?)\]", text, re.IGNORECASE | re.DOTALL
    )
    if not m:
        raise ValueError(f"no DATA ({obj}, …) block found")
    fields = [f.strip() for f in m.group(1).split(",")]
    open_i = text.index("{", m.end())
    close_i = text.index("}", open_i)
    rows = []
    for line in text[open_i + 1 : close_i].splitlines():
        if not line.strip():
            continue
        try:
            rows.append(shlex.split(line))
        except ValueError:
            continue
    return fields, rows


def _mpc_bus_ids(path: Path) -> dict[int, float]:
    """bus_id -> base_kv from the MATPOWER `mpc.bus = [ ... ];` block."""
    text = path.read_text(errors="replace")
    m = re.search(r"mpc\.bus\s*=\s*\[(.*?)\];", text, re.DOTALL)
    if not m:
        raise ValueError("no mpc.bus block in the .m file")
    out: dict[int, float] = {}
    for line in m.group(1).splitlines():
        line = line.split("%")[0].strip().rstrip(";")
        parts = line.split()
        if len(parts) < 10:
            continue
        try:
            out[int(float(parts[0]))] = float(parts[9])  # BUS_I, BASE_KV
        except ValueError:
            continue
    return out


def inspect_aux(aux: Path, mfile: Path) -> dict:
    """Structural check: do the AUX coordinates actually cover the case's buses?"""
    text = aux.read_text(errors="replace")
    out: dict = {}

    sub_fields, sub_rows = _aux_block(text, "Substation")
    si = {f: i for i, f in enumerate(sub_fields)}
    subs: dict[str, tuple[float, float]] = {}
    for r in sub_rows:
        if len(r) <= max(si["Latitude"], si["Longitude"], si["SubNum"]):
            continue
        try:
            subs[r[si["SubNum"]]] = (
                float(r[si["Latitude"]]),
                float(r[si["Longitude"]]),
            )
        except ValueError:
            continue
    out["substation_fields"] = sub_fields
    out["substation_records"] = len(sub_rows)
    out["substations_with_coords"] = len(subs)

    bus_fields, bus_rows = _aux_block(text, "Bus")
    bi = {f: i for i, f in enumerate(bus_fields)}
    out["bus_fields"] = bus_fields
    out["bus_records"] = len(bus_rows)

    located, aux_kv = {}, {}
    for r in bus_rows:
        if len(r) <= max(bi["BusNum"], bi.get("SubNum", 0), bi["BusNomVolt"]):
            continue
        try:
            bus = int(r[bi["BusNum"]])
            aux_kv[bus] = float(r[bi["BusNomVolt"]])
        except (ValueError, KeyError):
            continue
        sub = r[bi["SubNum"]] if "SubNum" in bi else None
        if sub in subs:
            located[bus] = subs[sub]
    out["buses_with_coords"] = len(located)

    if located:
        lats = [c[0] for c in located.values()]
        lons = [c[1] for c in located.values()]
        out["extent"] = {
            "lon_min": round(min(lons), 4),
            "lon_max": round(max(lons), 4),
            "lat_min": round(min(lats), 4),
            "lat_max": round(max(lats), 4),
        }

    # The check that matters for D02/D05/D06: does the AUX describe the same
    # buses as the case file we will actually import?
    mpc = _mpc_bus_ids(mfile)
    out["mpc_bus_records"] = len(mpc)
    out["bus_ids_match"] = set(mpc) == set(aux_kv)
    out["ids_only_in_mpc"] = len(set(mpc) - set(aux_kv))
    out["ids_only_in_aux"] = len(set(aux_kv) - set(mpc))
    out["kv_mismatches"] = sum(
        1 for b in set(mpc) & set(aux_kv) if abs(mpc[b] - aux_kv[b]) > 1e-6
    )
    out["mpc_buses_without_coords"] = len(set(mpc) - set(located))
    return out


def main() -> int:
    files = {}
    for name in ("ACTIVSg2000_current.zip", "ACTIVSg2000.aux", "case_ACTIVSg2000.m"):
        p = RAW / name
        if not p.exists():
            print(f"MISSING: {p}", file=sys.stderr)
            return 1
        files[name] = {"bytes": p.stat().st_size, "sha256": sha256(p)}

    record = {
        "issue": "2WKG-38 [D01] Download one synthetic Texas case",
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": PROVIDER,
        "files": files,
        "aux_check": inspect_aux(RAW / "ACTIVSg2000.aux", RAW / "case_ACTIVSg2000.m"),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

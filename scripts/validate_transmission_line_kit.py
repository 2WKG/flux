"""Validate the source handoff for the transmission tower/line archetype."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT_DIR = ROOT / "assets" / "3d" / "transmission_line_segment"
META_PATH = KIT_DIR / "transmission_line_segment.meta.json"
SOURCE_PATH = KIT_DIR / "transmission_line_segment.blender.py"


def validate_kit() -> list[str]:
    metadata = json.loads(META_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    if metadata.get("archetype_id") != "transmission_line_segment":
        errors.append("archetype_id must be transmission_line_segment")
    if metadata.get("contract_id") != "flux:3d-asset-archetypes:v1":
        errors.append("metadata must bind the shared v1 contract")
    if metadata.get("transform") != {
        "length_unit": "meter",
        "unit_scale": 1.0,
        "up_axis": "Y",
        "forward_axis": "-Z",
        "pivot": "ground_center",
    }:
        errors.append("metadata transform must match the import contract")
    if metadata.get("footprint_m") != {"length": 12, "width": 12}:
        errors.append("metadata footprint must match the shared archetype")
    connectors = metadata.get("connectors", [])
    expected_connectors = {"CONN_HV_IN_0", "CONN_HV_OUT_0"}
    if {connector.get("name") for connector in connectors} != expected_connectors:
        errors.append("metadata must expose the two named HV connectors")
    if {connector.get("role") for connector in connectors} != {"HV_IN", "HV_OUT"}:
        errors.append("connectors must be one HV_IN and one HV_OUT")
    lods = [metadata.get(f"triangles_lod{index}") for index in range(3)]
    if lods != [18000, 7000, 2000]:
        errors.append("LOD triangle budgets must match the shared archetype")
    if metadata.get("material_slots") != [
        {
            "name": "MAT_STATUS",
            "default": "neutral",
            "binding": "placement.status_label",
        }
    ]:
        errors.append("a neutral MAT_STATUS slot is required")
    if not metadata.get("license") or not metadata.get("source_of_shape"):
        errors.append("redistribution license and source_of_shape are required")
    source = SOURCE_PATH.read_text(encoding="utf-8")
    for required in (
        "MAT_STATUS",
        "CONN_HV_IN_0",
        "CONN_HV_OUT_0",
        'export_format="GLB"',
    ):
        if required not in source:
            errors.append(f"Blender source must create {required}")
    return errors


def main() -> int:
    errors = validate_kit()
    if errors:
        print("\n".join(errors))
        return 1
    print("transmission_line_segment asset kit conforms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate the source handoff for the commercial-buildings archetype."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT_DIR = ROOT / "assets" / "3d" / "commercial_buildings"
META_PATH = KIT_DIR / "commercial_buildings.meta.json"
SOURCE_PATH = KIT_DIR / "commercial_buildings.blender.py"


def validate_kit() -> list[str]:
    metadata = json.loads(META_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    if metadata.get("archetype_id") != "commercial_buildings":
        errors.append("archetype_id must be commercial_buildings")
    if metadata.get("contract_id") != "flux:3d-asset-archetypes:v1":
        errors.append("metadata must bind the shared v1 contract")
    if metadata.get("transform") != {"length_unit": "meter", "unit_scale": 1.0, "up_axis": "Y", "forward_axis": "-Z", "pivot": "ground_center"}:
        errors.append("metadata transform must match the import contract")
    if metadata.get("footprint_m") != {"length": 120, "width": 100}:
        errors.append("metadata footprint must match the commercial archetype")
    connectors = metadata.get("connectors", [])
    if [(item.get("name"), item.get("role")) for item in connectors] != [("CONN_MV_FEED_0", "MV_FEED")]:
        errors.append("metadata must expose one named MV feeder connector")
    if [metadata.get(f"triangles_lod{index}") for index in range(3)] != [24000, 9000, 2600]:
        errors.append("LOD triangle budgets must match the commercial archetype")
    if metadata.get("material_slots") != [{"name": "MAT_STATUS", "default": "neutral", "binding": "placement.status_label"}]:
        errors.append("a neutral MAT_STATUS slot is required")
    if not metadata.get("license") or not metadata.get("source_of_shape"):
        errors.append("redistribution license and source_of_shape are required")
    source = SOURCE_PATH.read_text(encoding="utf-8")
    for required in ("MAT_STATUS", "CONN_MV_FEED_0", 'export_format="GLB"', "resolution_x = 512"):
        if required not in source:
            errors.append(f"Blender source must create {required}")
    return errors


def main() -> int:
    errors = validate_kit()
    if errors:
        print("\n".join(errors))
        return 1
    print("commercial_buildings asset kit conforms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate the source handoff for the hospital archetype."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT_DIR = ROOT / "assets" / "3d" / "hospital"
META_PATH = KIT_DIR / "hospital.meta.json"
SOURCE_PATH = KIT_DIR / "hospital.blender.py"


def validate_kit() -> list[str]:
    metadata = json.loads(META_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []
    if metadata.get("archetype_id") != "hospital":
        errors.append("archetype_id must be hospital")
    if metadata.get("contract_id") != "flux:3d-asset-archetypes:v1":
        errors.append("metadata must bind the shared v1 contract")
    expected_transform = {
        "length_unit": "meter",
        "unit_scale": 1.0,
        "up_axis": "Y",
        "forward_axis": "-Z",
        "pivot": "ground_center",
    }
    if metadata.get("transform") != expected_transform:
        errors.append("metadata transform must match the import contract")
    if metadata.get("footprint_m") != {"length": 90, "width": 60}:
        errors.append("metadata footprint must match the shared archetype")
    if [connector.get("name") for connector in metadata.get("connectors", [])] != [
        "CONN_MV_FEED_0"
    ]:
        errors.append("metadata must expose CONN_MV_FEED_0")
    if [connector.get("role") for connector in metadata.get("connectors", [])] != [
        "MV_FEED"
    ]:
        errors.append("connector must be MV_FEED")
    if [metadata.get(f"triangles_lod{index}") for index in range(3)] != [
        26000,
        9500,
        2800,
    ]:
        errors.append("LOD triangle budgets must match the shared archetype")
    if metadata.get("material_slots") != [
        {
            "name": "MAT_STATUS",
            "default": "neutral",
            "binding": "placement.status_label",
        }
    ]:
        errors.append("a neutral MAT_STATUS slot is required")
    source = SOURCE_PATH.read_text(encoding="utf-8")
    for required in ("MAT_STATUS", "CONN_MV_FEED_0", 'export_format="GLB"'):
        if required not in source:
            errors.append(f"Blender source must create {required}")
    return errors


def main() -> int:
    errors = validate_kit()
    if errors:
        print("\n".join(errors))
        return 1
    print("hospital asset kit conforms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

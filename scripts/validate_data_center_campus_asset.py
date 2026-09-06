"""Validate data-center campus export metadata against the shared 3D catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data/3d/asset-archetypes-v1.json"
META_PATH = ROOT / "data/3d/assets/data_center_campus.meta.json"
TRANSFORM = {
    "length_unit": "meter",
    "unit_scale": 1.0,
    "up_axis": "Y",
    "forward_axis": "-Z",
    "handedness": "right",
    "pivot": "ground_center",
}
MATERIAL = [
    {
        "name": "MAT_STATUS",
        "default": "neutral",
        "binding": "server_asserted_status_label",
    }
]


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(meta: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    entry = next(
        (item for item in catalog["archetypes"] if item["id"] == "data_center_campus"),
        None,
    )
    if not entry:
        return ["data-center archetype is missing from the shared catalog"]
    errors: list[str] = []
    for field in (
        "semantic_name",
        "category",
        "footprint_m",
        "connectors",
        "lod_triangles",
    ):
        if meta.get(field) != entry[field]:
            errors.append(f"{field} does not match the shared archetype")
    if meta.get("archetype_id") != entry["id"] or meta.get(
        "contract_id"
    ) != catalog.get("contractId"):
        errors.append("asset identity does not match the shared contract")
    if meta.get("transform") != TRANSFORM:
        errors.append("transform must use metre/Y/-Z/right/ground_center")
    if meta.get("container") != "glb" or not str(
        meta.get("model_filename", "")
    ).endswith(".glb"):
        errors.append("export must declare a .glb model")
    if meta.get("preview_size_px") != 512 or not str(
        meta.get("preview_filename", "")
    ).endswith(".png"):
        errors.append("export must declare a 512 px PNG preview")
    if meta.get("material_slots") != MATERIAL:
        errors.append("asset must expose neutral MAT_STATUS only")
    if (
        not str(meta.get("license", "")).strip()
        or not str(meta.get("source_of_shape", "")).strip()
    ):
        errors.append("license and source_of_shape are required")
    context = meta.get("minnesota_context", {})
    if (
        context.get("render_mode") != "catalog_preview"
        or context.get("truth_label") != "unavailable"
    ):
        errors.append(
            "current Minnesota context must remain an unavailable catalogue preview"
        )
    return errors


def main() -> int:
    errors = validate(_read(META_PATH), _read(CATALOG_PATH))
    if errors:
        print("\n".join(errors))
        return 1
    print("data_center_campus metadata matches flux:3d-asset-archetypes:v1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

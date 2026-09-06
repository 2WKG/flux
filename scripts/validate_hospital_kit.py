"""Validate the source handoff for the hospital archetype.

Every budget this checks is read from the shared catalog
(``data/3d/asset-archetypes-v1.json``), never hand-copied, so catalog drift
turns the kit red instead of passing silently. Every geometric claim is checked
against the manifest the builder derives from its own scene description, so the
meta cannot describe a different asset than the source builds - and neither
check needs Blender installed.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ASSET_ID = "hospital"
KIT_DIR = ROOT / "data" / "3d" / "assets" / ASSET_ID
META_PATH = KIT_DIR / f"{ASSET_ID}.meta.json"
SOURCE_PATH = KIT_DIR / f"{ASSET_ID}.blender.py"
CATALOG_PATH = ROOT / "data" / "3d" / "asset-archetypes-v1.json"

EXPECTED_TRANSFORM = {
    "length_unit": "meter",
    "unit_scale": 1.0,
    "up_axis": "Y",
    "forward_axis": "-Z",
    "pivot": "ground_center",
}
# data/3d/asset-archetypes-v1.json -> footprint.tolerance
FOOTPRINT_TOLERANCE = 0.05


def load_builder(source_path: Path = SOURCE_PATH) -> Any:
    """Import the ``.blender.py`` source as a module (it must not need bpy)."""
    spec = importlib.util.spec_from_file_location(f"{ASSET_ID}_source", source_path)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable
        raise ImportError(f"cannot load {source_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_reads(source_text: str) -> set[str] | None:
    """Names read inside ``build()``; ``None`` if there is no ``build()``."""
    tree = ast.parse(source_text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "build":
            return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
    return None


def validate_kit(
    meta_path: Path = META_PATH,
    source_path: Path = SOURCE_PATH,
    catalog_path: Path = CATALOG_PATH,
) -> list[str]:
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    if metadata.get("archetype_id") != ASSET_ID:
        errors.append(f"archetype_id must be {ASSET_ID}")
    if metadata.get("contract_id") != catalog.get("contractId"):
        errors.append("metadata must bind the shared v1 contract")
    if metadata.get("transform") != EXPECTED_TRANSFORM:
        errors.append("metadata transform must match the import contract")

    archetype = next(
        (item for item in catalog.get("archetypes", []) if item.get("id") == ASSET_ID),
        None,
    )
    if archetype is None:
        errors.append(f"{ASSET_ID} is not in the shared archetype catalog")
        return errors

    if metadata.get("footprint_m") != archetype.get("footprint_m"):
        errors.append("metadata footprint must match the shared archetype")
    lods = [metadata.get(f"triangles_lod{index}") for index in range(3)]
    catalog_lods = [archetype.get("lod_triangles", {}).get(f"lod{i}") for i in range(3)]
    if lods != catalog_lods:
        errors.append("LOD triangle budgets must match the shared archetype")

    connectors = metadata.get("connectors", [])
    if {connector.get("name") for connector in connectors} != {"CONN_MV_FEED_0"}:
        errors.append("metadata must expose the named MV feeder connector")
    if {connector.get("role") for connector in connectors} != set(
        archetype.get("connectors", [])
    ):
        errors.append("connector roles must match the shared archetype")

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

    source_text = source_path.read_text(encoding="utf-8")
    build_reads = _build_reads(source_text)
    if build_reads is None or not {"SCENE_NODES", "CONNECTORS"} <= build_reads:
        errors.append("build() must create every SCENE_NODES node and CONNECTORS empty")

    manifest = load_builder(source_path).scene_manifest()

    meta_connectors = {
        connector.get("name"): connector.get("position_m") for connector in connectors
    }
    source_connectors = {
        connector["name"]: connector["position_m"]
        for connector in manifest["connectors"]
    }
    if meta_connectors != source_connectors:
        errors.append(
            "metadata connector positions must equal the positions the source builds"
        )

    bounds = manifest["bounds_m"]
    if metadata.get("bounds_m") != bounds:
        errors.append("metadata bounds_m must equal the bounds the source builds")

    if bounds["min"][1] != 0.0:
        errors.append("pivot is ground_center: built geometry must start at y = 0")

    footprint = archetype.get("footprint_m", {})
    width = bounds["max"][0] - bounds["min"][0]
    length = bounds["max"][2] - bounds["min"][2]
    if width > footprint.get("width", 0) * (1 + FOOTPRINT_TOLERANCE):
        errors.append("built X extent must fit the declared footprint width")
    if length > footprint.get("length", 0) * (1 + FOOTPRINT_TOLERANCE):
        errors.append("built Z extent must fit the declared footprint length")

    return errors


def main() -> int:
    errors = validate_kit()
    if errors:
        print("\n".join(errors))
        return 1
    print(f"{ASSET_ID} asset kit conforms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

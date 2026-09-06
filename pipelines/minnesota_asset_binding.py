"""Bind reusable 3D models to Minnesota scene evidence without inventing places.

Archetypes describe geometry only. This is the import boundary between an
archetype's metadata and a Minnesota placement artifact. A model without an
accepted, placement-capable Minnesota identity remains a catalogue preview.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONTRACT_ID = "flux:3d-asset-archetypes:v1"
MATERIAL_SLOT = "MAT_STATUS"


class AssetBindingError(ValueError):
    """Raised when an asset cannot be safely imported under the shared contract."""


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_catalog(path: Path) -> dict[str, Any]:
    catalog = _read_json(path)
    if catalog.get("contractId") != CONTRACT_ID:
        raise AssetBindingError("asset catalog has an unsupported contract id")
    return catalog


def load_inventory(path: Path) -> dict[str, Any]:
    return _read_json(path)


def _catalog_entry(catalog: dict[str, Any], archetype_id: str) -> dict[str, Any]:
    for entry in catalog.get("archetypes", []):
        if entry.get("id") == archetype_id:
            return entry
    raise AssetBindingError(f"unknown archetype: {archetype_id}")


def _placement_artifact(inventory: dict[str, Any], artifact_id: str) -> dict[str, Any] | None:
    for artifact in inventory.get("accepted_product_artifacts", []):
        if artifact.get("artifact_id") == artifact_id:
            return artifact
    return None


def _preview(entry: dict[str, Any], reason: str) -> dict[str, Any]:
    """Return a conspicuous, non-geographic preview rather than a fake placement."""
    return {
        "render_mode": "catalog_preview",
        "semantic_type": entry["category"],
        "archetype_id": entry["id"],
        "footprint_m": entry["footprint_m"],
        "connectors": entry["connectors"],
        "lod_triangles": entry["lod_triangles"],
        "material": {"slot": MATERIAL_SLOT, "status_label": "unavailable"},
        "disclosure": f"Illustrative catalogue preview — not Minnesota infrastructure: {reason}",
    }


def bind_asset(
    catalog: dict[str, Any],
    inventory: dict[str, Any],
    model: dict[str, Any],
    placement: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate model metadata and bind it only to accepted Minnesota evidence.

    Missing or ineligible evidence is a normal demo state: callers receive a
    labelled catalogue preview with no coordinates or scene identity.
    """
    archetype_id = model.get("archetype_id")
    if not isinstance(archetype_id, str):
        raise AssetBindingError("model.archetype_id is required")
    entry = _catalog_entry(catalog, archetype_id)

    if model.get("contract_id") != CONTRACT_ID:
        raise AssetBindingError("model contract_id does not match the shared contract")
    if not isinstance(model.get("glb_uri"), str) or not model["glb_uri"].endswith(".glb"):
        raise AssetBindingError("model.glb_uri must identify a .glb import")
    for field in ("footprint_m", "connectors", "lod_triangles"):
        if model.get(field) != entry[field]:
            raise AssetBindingError(f"model {field} does not match archetype metadata")

    if not placement:
        return _preview(entry, "no accepted Minnesota placement artifact was supplied")

    artifact_id = placement.get("source_artifact_id")
    artifact = _placement_artifact(inventory, artifact_id) if isinstance(artifact_id, str) else None
    allowed_uses = artifact.get("allowed_uses", []) if artifact else []
    coordinates = placement.get("coordinates")
    coordinates_are_valid = (
        isinstance(coordinates, dict)
        and isinstance(coordinates.get("longitude"), (int, float))
        and isinstance(coordinates.get("latitude"), (int, float))
    )
    if (
        placement.get("truth_label") != "source_supported"
        or not artifact
        or "3d placement" not in allowed_uses
        or not coordinates_are_valid
        or not isinstance(placement.get("scene_id"), str)
    ):
        return _preview(entry, "placement lacks accepted Minnesota identity, coverage, or coordinates")

    return {
        "render_mode": "placed",
        "scene_id": placement["scene_id"],
        "source_artifact_id": artifact_id,
        "semantic_type": entry["category"],
        "archetype_id": entry["id"],
        "coordinates": coordinates,
        "footprint_m": entry["footprint_m"],
        "connectors": entry["connectors"],
        "lod_triangles": entry["lod_triangles"],
        "material": {"slot": MATERIAL_SLOT, "status_label": "source_supported"},
    }


def bind_from_files(catalog_path: Path, inventory_path: Path, request_path: Path) -> dict[str, Any]:
    """Load one import request and return its render-safe binding payload."""
    request = _read_json(request_path)
    return bind_asset(
        load_catalog(catalog_path),
        load_inventory(inventory_path),
        request.get("model", {}),
        request.get("placement"),
    )

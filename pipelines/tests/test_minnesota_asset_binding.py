from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipelines.minnesota_asset_binding import AssetBindingError, bind_asset


ROOT = Path(__file__).resolve().parents[2]


def _catalog() -> dict:
    return json.loads((ROOT / "data/3d/asset-archetypes-v1.json").read_text())


def _inventory() -> dict:
    return json.loads((ROOT / "data/sources/minnesota-accepted-artifact-inventory.json").read_text())


def _model() -> dict:
    entry = _catalog()["archetypes"][0]
    return {
        "archetype_id": entry["id"],
        "contract_id": "flux:3d-asset-archetypes:v1",
        "glb_uri": "assets/transmission_tower.glb",
        "footprint_m": entry["footprint_m"],
        "connectors": entry["connectors"],
        "lod_triangles": entry["lod_triangles"],
    }


def test_current_inventory_returns_a_visible_non_geographic_preview():
    binding = bind_asset(
        _catalog(),
        _inventory(),
        _model(),
        {
            "scene_id": "mn:fictional:substation",
            "source_artifact_id": "mn:facility_capacity:county:2024",
            "coordinates": {"longitude": -93.2, "latitude": 44.9},
            "truth_label": "source_supported",
        },
    )

    assert binding["render_mode"] == "catalog_preview"
    assert "coordinates" not in binding
    assert binding["material"] == {"slot": "MAT_STATUS", "status_label": "unavailable"}
    assert "not Minnesota infrastructure" in binding["disclosure"]


def test_accepted_placement_binds_identity_and_shared_material_slot():
    inventory = _inventory()
    inventory["accepted_product_artifacts"] = [{
        "artifact_id": "mn:scene:coverage:v1",
        "allowed_uses": ["3d placement"],
    }]
    binding = bind_asset(
        _catalog(),
        inventory,
        _model(),
        {
            "scene_id": "mn:scene:coverage:v1:facility-1",
            "source_artifact_id": "mn:scene:coverage:v1",
            "coordinates": {"longitude": -93.265, "latitude": 44.977},
            "truth_label": "source_supported",
        },
    )

    assert binding["render_mode"] == "placed"
    assert binding["semantic_type"] == "network"
    assert binding["material"] == {"slot": "MAT_STATUS", "status_label": "source_supported"}


def test_import_rejects_metadata_that_does_not_match_its_archetype():
    model = _model()
    model["connectors"] = ["NONE"]
    with pytest.raises(AssetBindingError, match="connectors"):
        bind_asset(_catalog(), _inventory(), model, None)

"""HTTP contract tests for the registered 3D model pack."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings


def _pack(root: Path) -> tuple[Path, bytes]:
    model = b"glTF-model-bytes"
    digest = hashlib.sha256(model).hexdigest()
    (root / "line").mkdir(parents=True)
    (root / "symbols").mkdir()
    (root / "line" / "line.glb").write_bytes(model)
    (root / "symbols" / "atlas.png").write_bytes(b"png")
    (root / "symbols" / "mapping.json").write_text("{}", encoding="utf-8")
    resource = {
        "path": "line/line.glb",
        "sha256": digest,
        "bytes": len(model),
        "triangles": 1,
    }
    manifest = {
        "schema_version": 1,
        "contract_id": "flux:3d-asset-archetypes:v1",
        "assets": [
            {
                "archetype_id": "transmission_line_segment",
                "lods": {"lod0": resource, "lod1": resource, "lod2": resource},
            }
        ],
        "symbols": {
            "atlas": {"path": "symbols/atlas.png", "sha256": "a" * 64, "bytes": 3},
            "mapping": {"path": "symbols/mapping.json", "sha256": "b" * 64, "bytes": 2},
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root, model


def _client(pack: Path) -> TestClient:
    return TestClient(create_app(Settings(asset_pack_root=pack, _env_file=None)))


def test_registered_manifest_and_glb_are_served_as_real_http_bytes(
    tmp_path: Path,
) -> None:
    pack, model = _pack(tmp_path / "pack")
    client = _client(pack)

    manifest = client.get("/assets/flux-grid/manifest.json")
    response = client.get("/assets/flux-grid/line/line.glb")

    assert manifest.status_code == 200
    assert manifest.headers["cache-control"] == "no-cache"
    assert manifest.json()["assets"][0]["lods"]["lod2"]["path"] == "line/line.glb"
    assert response.status_code == 200
    assert response.content == model
    assert response.headers["content-type"] == "model/gltf-binary"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["etag"] == f'"{hashlib.sha256(model).hexdigest()}"'


def test_only_manifest_registered_safe_paths_are_served(tmp_path: Path) -> None:
    pack, _model = _pack(tmp_path / "pack")
    (pack / "secret.glb").write_bytes(b"do not serve")
    client = _client(pack)

    unknown = client.get("/assets/flux-grid/secret.glb")
    traversal = client.get("/assets/flux-grid/%2e%2e/secret.glb")

    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "not_found"
    assert traversal.status_code == 404
    assert traversal.json()["error"]["code"] == "not_found"


def test_missing_or_unpublished_pack_is_a_named_unavailable_state(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path / "missing")
    for response in (
        client.get("/assets/flux-grid/manifest.json"),
        client.get("/assets/flux-grid/line/line.glb"),
    ):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "unavailable"
        assert response.json()["error"]["details"]["reason"] == "manifest_missing"


def test_placement_projection_uses_source_geometry_and_declared_visual_kind() -> None:
    root = Path(__file__).resolve().parents[1] / "data/artifacts/physical_inventory"
    client = TestClient(
        create_app(Settings(physical_inventory_root=root, _env_file=None))
    )

    response = client.get(
        "/api/v1/grid/asset-placements?state=tx&version=1.1.0&limit=2"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["placement_contract"] == "flux:3d-asset-placement:v1"
    assert body["items"]
    assert {item["archetype_id"] for item in body["items"]} <= {
        "transmission_line_segment",
        "battery_storage",
    }
    assert all(
        item["coordinate_provenance"] == "physical_inventory_display_geometry"
        for item in body["items"]
    )
    assert all(
        item["status"] in {"source_supported", "source_screened"}
        for item in body["items"]
    )


def test_asset_placement_validation_and_missing_release_are_explicit() -> None:
    root = Path(__file__).resolve().parents[1] / "data/artifacts/physical_inventory"
    client = TestClient(
        create_app(Settings(physical_inventory_root=root, _env_file=None))
    )

    invalid = client.get(
        "/api/v1/grid/asset-placements?state=tx&version=1.1.0&bbox=not,a,bbox"
    )
    missing = client.get("/api/v1/grid/asset-placements?state=tx&version=9.9.9")

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_input"
    assert missing.status_code == 503
    assert missing.json()["error"]["details"]["reason"] == "release_not_found"

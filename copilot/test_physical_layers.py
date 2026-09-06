"""HTTP checks against the published physical-inventory release artifacts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings

ROOT = Path(__file__).resolve().parents[1] / "data/artifacts/physical_inventory"


def _client() -> TestClient:
    return TestClient(create_app(Settings(physical_inventory_root=ROOT)))


def test_tx_lines_are_real_http_pages_with_release_bound_cursor() -> None:
    client = _client()
    first = client.get("/api/v1/grid/layers/line?state=tx&version=1.1.0&limit=2")

    assert first.status_code == 200
    body = first.json()
    assert body["artifact_id"] == "tx:physical-inventory:1.1.0"
    assert (
        body["release_sha256"]
        == "036feeb75c805a03a7489f8e916b15d408ef64c76117548700290db01ced0496"
    )
    assert body["inventory_mode"] == "physical_observed"
    assert body["page"]["total"] == 7042
    assert [item["asset_id"] for item in body["items"]] == sorted(
        item["asset_id"] for item in body["items"]
    )
    assert all(item["display_crs"] == "EPSG:4326" for item in body["items"])
    assert all(item["native_crs"] == "EPSG:4326" for item in body["items"])
    assert all(item["provenance"]["source_version"] for item in body["items"])

    second = client.get(
        "/api/v1/grid/layers/line?state=tx&version=1.1.0&limit=2&cursor="
        + body["page"]["next_cursor"]
    )
    assert second.status_code == 200
    assert {item["asset_id"] for item in first.json()["items"]}.isdisjoint(
        item["asset_id"] for item in second.json()["items"]
    )
    changed_request = client.get(
        "/api/v1/grid/layers/line?state=tx&version=1.1.0&bbox=-106,25,-93,37&cursor="
        + body["page"]["next_cursor"]
    )
    assert changed_request.status_code == 422
    assert changed_request.json()["error"]["code"] == "invalid_input"


def test_minnesota_viewport_transforms_native_esri_geometry_to_wgs84() -> None:
    response = _client().get(
        "/api/v1/grid/layers/line?state=mn&version=1.1.0&bbox=-94,45,-93,47&limit=100"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["page"]["total"] == 31
    item = body["items"][0]
    assert item["native_crs"] == "ESRI:103705"
    assert item["display_crs"] == "EPSG:4326"
    assert item["transform_provenance"] == {
        "method": "pyproj always_xy",
        "source_crs": "ESRI:103705",
        "display_crs": "EPSG:4326",
    }
    assert item["native_geometry"] != item["display_geometry"]
    assert body["coverage"][0]["status"] == "partial"
    assert body["coverage"][0]["denominator_count"] == 31


def test_unavailable_geometry_is_honest_and_never_viewport_co_located() -> None:
    client = _client()
    all_generation = client.get(
        "/api/v1/grid/layers/generation?state=tx&version=1.1.0&limit=100"
    )
    assert all_generation.status_code == 200
    unavailable = next(
        item
        for item in all_generation.json()["items"]
        if item["availability"] == "unavailable"
    )
    assert unavailable["display_geometry"] is None
    assert unavailable["native_geometry"] is None
    assert unavailable["native_crs"] is None
    assert unavailable["transform_provenance"] is None
    assert unavailable["geometry_status"] == "unavailable"

    viewport = client.get(
        "/api/v1/grid/layers/generation?state=tx&version=1.1.0&bbox=-106,25,-93,37&limit=100"
    )
    assert viewport.status_code == 200
    assert all(item["availability"] == "available" for item in viewport.json()["items"])
    coverage = viewport.json()["coverage"][0]
    assert coverage["unavailable_count"] == 2934
    assert coverage["status"] == "partial"


def test_missing_release_is_explicitly_unavailable() -> None:
    response = _client().get("/api/v1/grid/layers/line?state=tx&version=9.9.9")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "physical_inventory",
        "reason": "release_not_found",
        "state": "tx",
        "version": "9.9.9",
    }


def test_invalid_viewport_and_unknown_physical_layer_use_shared_errors() -> None:
    client = _client()
    invalid = client.get(
        "/api/v1/grid/layers/line?state=tx&version=1.1.0&bbox=not,a,bbox"
    )
    unknown = client.get("/api/v1/grid/layers/transformer?state=tx&version=1.1.0")

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_input"
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "not_found"


def test_manifest_digest_mismatch_is_unavailable_not_stale_provenance(
    tmp_path: Path,
) -> None:
    root = tmp_path / "physical_inventory"
    shutil.copytree(ROOT, root)
    manifest_path = root / "manifest-1.1.0.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    next(entry for entry in manifest["artifacts"] if entry["state"] == "tx")[
        "canonical_content_sha256"
    ] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    response = TestClient(create_app(Settings(physical_inventory_root=root))).get(
        "/api/v1/grid/layers/line?state=tx&version=1.1.0"
    )

    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "release_hash_mismatch"

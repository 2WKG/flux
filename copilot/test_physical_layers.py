"""HTTP checks against the published physical-inventory release artifacts."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.routes import physical_layers
from pipelines.physical_inventory import artifact_sha256

ROOT = Path(__file__).resolve().parents[1] / "data/artifacts/physical_inventory"


def _client() -> TestClient:
    return TestClient(
        create_app(Settings(physical_inventory_root=ROOT, _env_file=None))
    )


def _client_for(root: Path) -> TestClient:
    return TestClient(
        create_app(Settings(physical_inventory_root=root, _env_file=None))
    )


def _copy(tmp_path: Path) -> Path:
    root = tmp_path / "physical_inventory"
    shutil.copytree(ROOT, root)
    return root


def _release_path(root: Path, state: str) -> Path:
    return root / state / "physical-inventory-1.1.0.json.gz"


def _read_release(root: Path, state: str) -> dict[str, Any]:
    with gzip.open(_release_path(root, state), "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _write_release(root: Path, state: str, release: dict[str, Any]) -> None:
    with gzip.open(_release_path(root, state), "wt", encoding="utf-8") as stream:
        json.dump(release, stream)


def _entry(root: Path, state: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    manifest_path = root / "manifest-1.1.0.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["artifacts"] if item["state"] == state)
    return manifest_path, manifest, entry


def _rewrite_manifest(root: Path, state: str, **fields: Any) -> None:
    manifest_path, manifest, entry = _entry(root, state)
    entry.update(fields)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _republish(root: Path, state: str, release: dict[str, Any]) -> None:
    """Publish a mutated release the way the pipeline would: digests restated."""
    release = dict(release)
    release["content_sha256"] = artifact_sha256(release)
    _write_release(root, state, release)
    _rewrite_manifest(
        root,
        state,
        canonical_content_sha256=release["content_sha256"],
        compressed_sha256=hashlib.sha256(
            _release_path(root, state).read_bytes()
        ).hexdigest(),
    )


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


def test_recompressed_release_bytes_fail_the_published_compressed_digest(
    tmp_path: Path,
) -> None:
    """Only ``compressed_sha256`` can catch bytes that decompress unchanged.

    Re-gzipping the identical JSON leaves the canonical digest, the release's
    own self-consistency and the published path all agreeing; the wire bytes
    the manifest published are the only thing that moved.
    """
    root = _copy(tmp_path)
    release = _read_release(root, "mn")
    _write_release(root, "mn", release)
    _, _, entry = _entry(root, "mn")
    assert (
        hashlib.sha256(_release_path(root, "mn").read_bytes()).hexdigest()
        != entry["compressed_sha256"]
    )
    assert entry["canonical_content_sha256"] == release["content_sha256"]
    assert artifact_sha256(release) == release["content_sha256"]

    response = _client_for(root).get("/api/v1/grid/layers/line?state=mn&version=1.1.0")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "physical_inventory",
        "reason": "release_hash_mismatch",
        "state": "mn",
        "version": "1.1.0",
    }


def test_manifest_entry_pointing_at_another_state_is_refused(tmp_path: Path) -> None:
    """The manifest row must name the file the route actually opened."""
    root = _copy(tmp_path)
    _rewrite_manifest(
        root,
        "mn",
        published_path="data/artifacts/physical_inventory/tx/"
        "physical-inventory-1.1.0.json.gz",
    )
    _, _, entry = _entry(root, "mn")
    release = _read_release(root, "mn")
    assert entry["canonical_content_sha256"] == release["content_sha256"]
    assert (
        entry["compressed_sha256"]
        == hashlib.sha256(_release_path(root, "mn").read_bytes()).hexdigest()
    )

    response = _client_for(root).get("/api/v1/grid/layers/line?state=mn&version=1.1.0")

    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "release_hash_mismatch"


def test_release_that_misstates_its_own_digest_is_refused(tmp_path: Path) -> None:
    """A manifest that agrees with a lying release is still not evidence.

    Both published digests are restated to match the tampered file, so the only
    check left standing is the release's own ``artifact_sha256`` consistency.
    """
    root = _copy(tmp_path)
    release = _read_release(root, "mn")
    release["content_sha256"] = "0" * 64
    _write_release(root, "mn", release)
    _rewrite_manifest(
        root,
        "mn",
        canonical_content_sha256="0" * 64,
        compressed_sha256=hashlib.sha256(
            _release_path(root, "mn").read_bytes()
        ).hexdigest(),
    )
    _, _, entry = _entry(root, "mn")
    assert entry["canonical_content_sha256"] == release["content_sha256"]
    assert artifact_sha256(release) != release["content_sha256"]

    response = _client_for(root).get("/api/v1/grid/layers/line?state=mn&version=1.1.0")

    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "release_hash_mismatch"


def test_release_for_another_geography_is_never_served_as_this_state(
    tmp_path: Path,
) -> None:
    """A fully self-consistent release still has to be the state that was asked for."""
    root = _copy(tmp_path)
    release = _read_release(root, "mn")
    release["geography_id"] = "tx"
    _republish(root, "mn", release)

    response = _client_for(root).get("/api/v1/grid/layers/line?state=mn&version=1.1.0")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {
        "artifact": "physical_inventory",
        "reason": "release_identity_mismatch",
        "state": "mn",
        "version": "1.1.0",
    }


def test_release_published_under_another_version_is_never_served(
    tmp_path: Path,
) -> None:
    root = _copy(tmp_path)
    release = _read_release(root, "mn")
    release["artifact_version"] = "9.9.9"
    _republish(root, "mn", release)

    response = _client_for(root).get("/api/v1/grid/layers/line?state=mn&version=1.1.0")

    assert response.status_code == 503
    assert response.json()["error"]["details"]["reason"] == "release_identity_mismatch"


def test_published_digests_are_verified_once_per_release_not_per_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dominant per-request cost is a property of immutable bytes.

    Canonicalising 11,949 TX assets costs ~0.5 s, so re-running it on every
    page made a map load O(pages).  The release is immutable, so verification
    is cached on both files' ``(st_mtime_ns, st_size)`` — and a file that is
    replaced under the cache re-verifies rather than serving a stale parse.
    """
    root = _copy(tmp_path)
    calls: list[str] = []
    real = physical_layers.artifact_sha256

    def counting(release: dict[str, Any]) -> str:
        calls.append(release.get("artifact_id", ""))
        return real(release)

    monkeypatch.setattr(physical_layers, "artifact_sha256", counting)
    client = _client_for(root)

    first = client.get("/api/v1/grid/layers/line?state=mn&version=1.1.0&limit=2")
    second = client.get(
        "/api/v1/grid/layers/line?state=mn&version=1.1.0&limit=2&cursor="
        + first.json()["page"]["next_cursor"]
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == ["mn:physical-inventory:1.1.0"]

    tampered = _read_release(root, "mn")
    tampered["assets"] = tampered["assets"][:-1]
    _write_release(root, "mn", tampered)

    after = client.get("/api/v1/grid/layers/line?state=mn&version=1.1.0&limit=2")

    assert after.status_code == 503
    # A cache keyed on the path alone would have served the stale 200 here.
    assert after.json()["error"]["details"]["reason"] == "release_hash_mismatch"

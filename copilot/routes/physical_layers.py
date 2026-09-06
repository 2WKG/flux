"""Read-only transport for published physical-inventory releases.

The release is authoritative for native geometry and truth labels.  This route
only creates a WGS84 display copy for a renderer; it never derives topology,
coordinates for unavailable assets, or coverage totals.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform as transform_geometry

from copilot.api import InvalidInputError, NotFoundError, UnavailableError
from pipelines.physical_inventory import artifact_sha256

router = APIRouter(prefix="/api/v1/grid/layers", tags=["physical-layers"])
MAX_LIMIT = 100


def _unavailable(reason: str, **details: str) -> UnavailableError:
    return UnavailableError(
        "The requested physical-inventory release is unavailable.",
        details={"artifact": "physical_inventory", "reason": reason, **details},
    )


def _artifact_path(root: Path, state: str, version: str) -> Path:
    return root / state / f"physical-inventory-{version}.json.gz"


def _read_release(path: Path) -> dict[str, Any]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            release = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise _unavailable("unreadable_release") from exc
    if not isinstance(release, dict) or not isinstance(release.get("assets"), list):
        raise _unavailable("invalid_release")
    return release


def _fingerprint(path: Path) -> tuple[int, int]:
    """Identify the exact bytes on disk without reading them."""
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=8)
def _verify_and_read(
    path_text: str,
    manifest_text: str,
    state: str,
    version: str,
    release_fingerprint: tuple[int, int],
    manifest_fingerprint: tuple[int, int],
) -> dict[str, Any]:
    """Read a release only when both published digests agree with its manifest.

    A published release is immutable, so the four digest conjuncts below are a
    property of the bytes on disk rather than of a request.  The cache key
    carries both files' ``(st_mtime_ns, st_size)``, so replacing either file
    re-verifies from scratch instead of pairing a stale parse with a fresh
    digest.  ``lru_cache`` never stores a raised exception, so a refusal is
    recomputed — and stays a refusal — on every subsequent request.
    """
    path = Path(path_text)
    try:
        manifest = json.loads(Path(manifest_text).read_text(encoding="utf-8"))
        entry = next(item for item in manifest["artifacts"] if item["state"] == state)
        compressed_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, KeyError, StopIteration, TypeError, json.JSONDecodeError) as exc:
        raise _unavailable("invalid_manifest", state=state, version=version) from exc
    release = _read_release(path)
    if (
        not str(entry.get("published_path", "")).endswith(
            f"/{state}/physical-inventory-{version}.json.gz"
        )
        or entry.get("compressed_sha256") != compressed_sha256
        or entry.get("canonical_content_sha256") != release.get("content_sha256")
        or artifact_sha256(release) != release.get("content_sha256")
    ):
        raise _unavailable("release_hash_mismatch", state=state, version=version)
    return release


def _verified_release(root: Path, state: str, version: str) -> dict[str, Any]:
    """Return the verified release, verifying each published file version once."""
    path = _artifact_path(root, state, version)
    manifest_path = root / f"manifest-{version}.json"
    if not path.is_file() or not manifest_path.is_file():
        raise _unavailable("release_not_found", state=state, version=version)
    return _verify_and_read(
        str(path),
        str(manifest_path),
        state,
        version,
        _fingerprint(path),
        _fingerprint(manifest_path),
    )


def _parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    try:
        west, south, east, north = (float(part) for part in value.split(","))
    except ValueError as exc:
        raise InvalidInputError(
            "bbox must be west,south,east,north", details={"field": "bbox"}
        ) from exc
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise InvalidInputError(
            "bbox must be a valid WGS84 extent", details={"field": "bbox"}
        )
    return west, south, east, north


def _cursor(value: str | None, binding: dict[str, str]) -> int:
    if value is None:
        return 0
    try:
        decoded = base64.urlsafe_b64decode(value.encode() + b"===")
        payload = json.loads(decoded)
        offset = payload.pop("offset")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidInputError(
            "cursor is invalid", details={"field": "cursor"}
        ) from exc
    if payload != binding or not isinstance(offset, int) or not 0 <= offset <= 100_000:
        raise InvalidInputError(
            "cursor does not match this request", details={"field": "cursor"}
        )
    return offset


def _encode_cursor(offset: int, binding: dict[str, str]) -> str:
    payload = json.dumps(
        {**binding, "offset": offset}, separators=(",", ":"), sort_keys=True
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


@lru_cache(maxsize=32)
def _transformer(source_crs: str) -> Transformer:
    return Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)


def _display_geometry(
    asset: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    native = asset.get("geometry")
    crs = asset.get("geometry_crs")
    if asset.get("geometry_status") == "unavailable":
        return None, None
    if not isinstance(native, dict) or not isinstance(crs, str):
        raise _unavailable("invalid_geometry")
    try:
        if crs == "EPSG:4326":
            return native, {
                "method": "identity",
                "source_crs": crs,
                "display_crs": "EPSG:4326",
            }
        converted = transform_geometry(_transformer(crs).transform, shape(native))
        return converted.__geo_interface__, {
            "method": "pyproj always_xy",
            "source_crs": crs,
            "display_crs": "EPSG:4326",
        }
    except Exception as exc:  # malformed geometry or unresolvable source CRS
        raise _unavailable("display_transform_failed") from exc


def _item(
    asset: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    display_pair: tuple[dict[str, Any] | None, dict[str, str] | None] | None = None,
) -> dict[str, Any]:
    display, transform = (
        _display_geometry(asset) if display_pair is None else display_pair
    )
    source_id = asset.get("source_id")
    source = sources.get(source_id)
    if not isinstance(source_id, str) or source is None:
        raise _unavailable("provenance_missing")
    return {
        "asset_id": asset["asset_id"],
        "asset_class": asset["asset_class"],
        "asset_kind": asset["asset_kind"],
        "availability": "available" if display is not None else "unavailable",
        "display_geometry": display,
        "display_crs": "EPSG:4326" if display is not None else None,
        "native_geometry": asset["geometry"],
        "native_crs": asset["geometry_crs"],
        "geometry_status": asset["geometry_status"],
        "geometry_accuracy_basis": asset["geometry_accuracy_basis"],
        "geometry_precision_m": asset["geometry_precision_m"],
        "transform_provenance": transform,
        "provenance": {
            "source_id": source_id,
            "source_record_id": asset["source_record_id"],
            "authority": source["authority"],
            "source_ref": source["source_ref"],
            "source_version": source["source_version"],
            "retrieved_at": source["retrieved_at"],
        },
    }


@router.get("/{layer}")
def get_physical_layer(
    layer: str,
    request: Request,
    state: str = Query(pattern=r"^(tx|mn)$"),
    version: str = Query(pattern=r"^\d+\.\d+\.\d+$"),
    bbox: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
) -> JSONResponse:
    """Return a deterministic page of source-backed physical assets."""
    viewport = _parse_bbox(bbox)
    settings = request.app.state.settings
    release = _verified_release(settings.physical_inventory_root, state, version)
    if (
        release.get("geography_id") != state
        or release.get("artifact_version") != version
    ):
        raise _unavailable("release_identity_mismatch", state=state, version=version)
    classes = {asset.get("asset_class") for asset in release["assets"]}
    if layer not in classes and layer != "all":
        raise NotFoundError("Unknown physical asset layer.", details={"layer": layer})
    bbox_key = bbox or ""
    binding = {
        "state": state,
        "version": version,
        "layer": layer,
        "bbox": bbox_key,
        "release": release["content_sha256"],
    }
    offset = _cursor(cursor, binding)
    sources = {source["source_id"]: source for source in release.get("sources", [])}
    # Select, filter and order the raw assets first; only the page that is
    # actually served is projected into a wire item, so `limit` bounds the
    # transform work instead of costing O(release) per page.
    selected = sorted(
        (
            asset
            for asset in release["assets"]
            if layer == "all" or asset["asset_class"] == layer
        ),
        key=lambda asset: asset["asset_id"],
    )
    # Provenance is a whole-release claim, so it is still checked across every
    # selected asset rather than only the page.
    for asset in selected:
        if not isinstance(asset.get("source_id"), str) or asset["source_id"] not in (
            sources
        ):
            raise _unavailable("provenance_missing")
    displays: list[tuple[dict[str, Any] | None, dict[str, str] | None]] | None = None
    if viewport is not None:
        viewport_shape = box(*viewport)
        kept: list[dict[str, Any]] = []
        displays = []
        for asset in selected:
            display_pair = _display_geometry(asset)
            geometry = display_pair[0]
            if geometry is not None and shape(geometry).intersects(viewport_shape):
                kept.append(asset)
                displays.append(display_pair)
        selected = kept
    total = len(selected)
    page_assets = selected[offset : offset + limit]
    page_displays = (
        displays[offset : offset + limit]
        if displays is not None
        else [None] * len(page_assets)
    )
    page_items = [
        _item(asset, sources, display_pair)
        for asset, display_pair in zip(page_assets, page_displays, strict=True)
    ]
    next_cursor = (
        _encode_cursor(offset + limit, binding) if offset + limit < total else None
    )
    return JSONResponse(
        {
            "api_version": "v1",
            "state": state,
            "artifact_version": version,
            "artifact_id": release["artifact_id"],
            "release_sha256": release["content_sha256"],
            "layer": layer,
            "inventory_mode": release["inventory_mode"],
            "electrical_model_mode": release["electrical_model_mode"],
            "items": page_items,
            "page": {
                "limit": limit,
                "cursor": cursor,
                "next_cursor": next_cursor,
                "total": total,
            },
            "coverage": [
                row
                for row in release["coverage"]
                if layer == "all" or row["asset_class"] == layer
            ],
        }
    )

"""Read-only delivery of the registered Flux Grid model pack."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Final

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from shapely.geometry import box, shape

from copilot.api import NotFoundError, UnavailableError
from copilot.routes.physical_layers import (
    MAX_LIMIT,
    _cursor,
    _display_geometry,
    _encode_cursor,
    _parse_bbox,
    _verified_release,
)

router = APIRouter(prefix="/assets/flux-grid", tags=["3d-assets"])
placements_router = APIRouter(prefix="/api/v1/grid", tags=["3d-assets"])

_SAFE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
_MEDIA_TYPES: Final = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ktx2": "image/ktx2",
}
_PLACEMENT_ARCHETYPES: Final = {
    ("line", "AC; OVERHEAD"): "transmission_line_segment",
    ("line", "AC; UNDERGROUND"): "transmission_line_segment",
    ("line", "OVERHEAD"): "transmission_line_segment",
    ("line", "transmission_or_subtransmission_line"): "transmission_line_segment",
    ("storage", "storage_unit"): "battery_storage",
}


def _unavailable(reason: str) -> UnavailableError:
    return UnavailableError(
        "The Flux Grid 3D asset pack is unavailable.",
        details={"artifact": "flux_grid_assets", "reason": reason},
    )


def _safe_relative(value: object) -> str | None:
    if not isinstance(value, str) or not _SAFE_PATH.fullmatch(value):
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or len(path.parts) == 0:
        return None
    return path.as_posix()


def _registered_files(manifest: dict[str, Any]) -> dict[str, str | None]:
    """Return only manifest-declared, safe files and their optional ETags."""
    files: dict[str, str | None] = {}

    def add(resource: object) -> None:
        if not isinstance(resource, dict):
            return
        path = _safe_relative(resource.get("path"))
        if path is not None:
            digest = resource.get("sha256")
            files[path] = (
                digest if isinstance(digest, str) and len(digest) == 64 else None
            )

    for asset in manifest.get("assets", []):
        if not isinstance(asset, dict):
            continue
        lods = asset.get("lods")
        if isinstance(lods, dict):
            for lod in lods.values():
                add(lod)
        for key in ("preview", "metadata"):
            path = _safe_relative(asset.get(key))
            if path is not None:
                files[path] = None
    symbols = manifest.get("symbols")
    if isinstance(symbols, dict):
        add(symbols.get("atlas"))
        add(symbols.get("mapping"))
    return files


def _manifest(root: Path) -> tuple[Path, dict[str, Any]]:
    path = root / "manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise _unavailable("manifest_missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise _unavailable("manifest_invalid") from exc
    if not isinstance(payload, dict) or not _registered_files(payload):
        raise _unavailable("manifest_invalid")
    return path, payload


@router.get("/manifest.json")
def get_manifest(request: Request) -> JSONResponse:
    """Serve the catalog itself with revalidation so a new pack is seen promptly."""
    _path, manifest = _manifest(request.app.state.settings.asset_pack_root)
    return JSONResponse(manifest, headers={"Cache-Control": "no-cache"})


@router.get("/{asset_path:path}")
def get_asset(asset_path: str, request: Request) -> FileResponse:
    """Serve only a file declared by the pack manifest; never a filesystem path."""
    normalized = _safe_relative(asset_path)
    if normalized is None:
        raise NotFoundError("Unknown Flux Grid asset.")
    root = request.app.state.settings.asset_pack_root
    _path, manifest = _manifest(root)
    registered = _registered_files(manifest)
    digest = registered.get(normalized)
    if normalized not in registered:
        raise NotFoundError("Unknown Flux Grid asset.")
    candidate = root.joinpath(*PurePosixPath(normalized).parts)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise NotFoundError("Unknown Flux Grid asset.") from exc
    if not candidate.is_file():
        raise _unavailable("registered_file_missing")
    media_type = _MEDIA_TYPES.get(candidate.suffix.lower())
    if media_type is None:
        raise NotFoundError("Unknown Flux Grid asset.")
    headers = {"Cache-Control": "no-cache"}
    if digest is not None:
        headers["ETag"] = f'"{digest}"'
    return FileResponse(candidate, media_type=media_type, headers=headers)


def _placement(asset: dict[str, Any]) -> dict[str, Any] | None:
    """Project an observed physical record to a visual anchor without inventing it."""
    archetype_id = _PLACEMENT_ARCHETYPES.get(
        (str(asset.get("asset_class")), str(asset.get("asset_kind")))
    )
    if archetype_id is None or asset.get("geometry_status") == "unavailable":
        return None
    geometry, _transform = _display_geometry(asset)
    if geometry is None:
        return None
    try:
        anchor = shape(geometry).representative_point()
        lon, lat = float(anchor.x), float(anchor.y)
    except Exception as exc:
        raise _unavailable("placement_geometry_invalid") from exc
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise _unavailable("placement_geometry_invalid")
    source_record_id = asset.get("source_record_id")
    if not isinstance(source_record_id, str) or not source_record_id:
        raise _unavailable("placement_provenance_missing")
    geometry_status = asset.get("geometry_status")
    return {
        "id": asset["asset_id"],
        "archetype_id": archetype_id,
        "position": [lon, lat, 0],
        "label": asset["asset_id"],
        "artifact_id": source_record_id,
        "status": "source_supported"
        if geometry_status == "source"
        else "source_screened",
        "visual_mapping": "source_kind",
        "coordinate_provenance": "physical_inventory_display_geometry",
    }


@placements_router.get("/asset-placements")
def get_asset_placements(
    request: Request,
    state: str = Query(pattern=r"^(tx|mn)$"),
    version: str = Query(pattern=r"^\d+\.\d+\.\d+$"),
    bbox: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
) -> JSONResponse:
    """Page source-backed records that have a declared reusable visual archetype.

    The `archetype_id` is a rendering choice keyed by source class/kind.  It is
    deliberately separate from the physical record identity and does not claim
    that a reusable model is an observed facility mesh.
    """
    viewport = _parse_bbox(bbox)
    release = _verified_release(
        request.app.state.settings.physical_inventory_root, state, version
    )
    if (
        release.get("geography_id") != state
        or release.get("artifact_version") != version
    ):
        raise _unavailable("placement_release_identity_mismatch")
    binding = {
        "state": state,
        "version": version,
        "bbox": bbox or "",
        "release": str(release.get("content_sha256", "")),
    }
    offset = _cursor(cursor, binding)
    candidates: list[dict[str, Any]] = []
    for asset in sorted(release.get("assets", []), key=lambda item: item["asset_id"]):
        placement = _placement(asset)
        if placement is None:
            continue
        if viewport is not None:
            try:
                if not box(*viewport).contains(
                    shape({"type": "Point", "coordinates": placement["position"][:2]})
                ):
                    continue
            except Exception as exc:
                raise _unavailable("placement_geometry_invalid") from exc
        candidates.append(placement)
    page = candidates[offset : offset + limit]
    next_cursor = (
        _encode_cursor(offset + limit, binding)
        if offset + limit < len(candidates)
        else None
    )
    return JSONResponse(
        {
            "api_version": "v1",
            "state": state,
            "artifact_version": version,
            "artifact_id": release["artifact_id"],
            "release_sha256": release["content_sha256"],
            "placement_contract": "flux:3d-asset-placement:v1",
            "items": page,
            "page": {
                "limit": limit,
                "cursor": cursor,
                "next_cursor": next_cursor,
                "total": len(candidates),
            },
        },
        headers={"Cache-Control": "no-cache"},
    )

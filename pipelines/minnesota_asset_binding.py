"""Bind reusable 3D models to Minnesota scene evidence without inventing places.

Archetypes describe geometry only. This is the import boundary between an
archetype's metadata and a Minnesota placement artifact. A model without an
accepted, placement-capable Minnesota identity remains a catalogue preview.

Acceptance is *read from storage*, never taken from the caller's request. The
request may claim anything; the only facts that promote a model to a placed
Minnesota asset are the artifact's own rows in the shared DuckDB namespace
(`pipelines/minnesota_schema.py`):

* `mn_artifact_manifests.availability == 'available'` -- the Unavailable label
  in `docs/design/minnesota-demo-narrative-ia.md` is derived from exactly this
  field, so an absent or `unavailable` manifest hides the dependent layer.
* `mn_score_results.regulatory_label` -- when the artifact carries a score, the
  narrative-IA status-label table admits `source_supported` and
  `source_screened`; `hypothetical` is explicitly "never rendered as permitted,
  approved, or ready to build" and therefore never positions geometry.

This module places points only. Lines, buses, and any topology edge stay out:
the accepted-artifact inventory marks every topology class `unavailable` and
prohibits "topology, line, bus, flow, loading, trip, or outage claims".
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import duckdb

CONTRACT_ID = "flux:3d-asset-archetypes:v1"
MATERIAL_SLOT = "MAT_STATUS"

# Gate 6 is deliberately a closed pack rather than a loose collection of
# models.  This makes a missing or substituted city-essential archetype a
# validation error at the binding boundary, before a scene can consume it.
CITY_ESSENTIALS_FORMAT = "flux:minnesota-city-essentials-binding:v1"
CITY_ESSENTIAL_ARCHETYPE_IDS = (
    "data_center_campus",
    "residential_neighborhood",
    "commercial_buildings",
    "factory_industrial_facility",
    "natural_gas_plant",
    "wind_turbine",
    "solar_array",
)

# 2WKG-402 receives a published geometry archive, but that archive is not a
# Minnesota placement artifact.  Keep the four later-infrastructure models in
# one explicit request shape so a mount owner can consume the checked release
# identity without substituting a made-up location or facility identity.
LATER_INFRASTRUCTURE_FORMAT = "flux:minnesota-later-infrastructure-binding:v1"
LATER_INFRASTRUCTURE_ARCHETYPE_IDS = (
    "battery_storage",
    "warehouse_logistics_center",
    "school_emergency_services",
    "ev_charging_station",
)
RUNTIME_RELEASE = {
    "tag": "flux-grid-runtime-v1-20260906",
    "archive_filename": "flux-grid-runtime-v1-20260906T103700Z.zip",
    "archive_sha256": "44ed49bd7e2a8392765825fdfc164e01061e7701befd8b89eaf38ac9ecc45d78",
    "runtime_manifest_sha256": "068ca96a44b9730f3d59ab55c454cf5a8959b285db62625bbd2bcad57afd067b",
}

#: The coordinate reference every placement declares. `docs/specs/00-overview.md`
#: and `docs/specs/10-duckdb-contract.md`: all geometry is EPSG:4326 lon/lat.
PLACEMENT_CRS = "EPSG:4326"

#: `mn_score_results.regulatory_label` values that may position geometry, from
#: the status-label table in `docs/design/minnesota-demo-narrative-ia.md`.
ACCEPTED_REGULATORY_LABELS = frozenset({"source_supported", "source_screened"})

#: The published GLB pack the committed Minnesota requests draw their
#: `glb_uri` values from. Its `publication_status` / `download_url` decide
#: whether those URIs resolve to a binary anyone can fetch, so the binder reads
#: them from the pack itself and carries them into every binding instead of
#: letting a consumer assume the geometry is present.
PACK_ARCHIVE_PATH = (
    Path(__file__).resolve().parents[1] / "data/3d/packs/flux-grid-v1/archive.json"
)

#: EPSG:4326 axis ranges, matching `_coordinate_contract_error` in
#: `pipelines/consumer_contracts.py`.
LONGITUDE_RANGE = (-180.0, 180.0)
LATITUDE_RANGE = (-90.0, 90.0)

#: Documented fallback extent for Minnesota (WGS 84 decimal degrees), rounded
#: outward from the published state extent of the TIGER 2024 `STATEFP=27`
#: boundary (about -97.24..-89.49 longitude, 43.50..49.38 latitude). It is only
#: used when no accepted Minnesota geometry artifact is stored; when
#: `mn_geography_artifacts` holds an available boundary, that real geometry --
#: the county union written by `pipelines/minnesota_source_evidence.py` -- is
#: the authority and this box is not consulted.
MINNESOTA_BBOX = (-97.3, 43.4, -89.4, 49.5)

_MN_GEOMETRY_SQL = """
    SELECT g.geometry_wkb
    FROM mn_geography_artifacts g
    JOIN mn_artifact_manifests m USING (artifact_id)
    WHERE m.availability = 'available'
      AND g.coordinate_status <> 'unavailable'
      AND g.geometry_wkb IS NOT NULL
"""


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


def _inventory_entry(
    inventory: dict[str, Any], artifact_id: str
) -> dict[str, Any] | None:
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


def _acceptance(
    con: duckdb.DuckDBPyConnection, artifact_id: str
) -> tuple[str | None, str]:
    """Read acceptance for one artifact from storage.

    Returns ``(status_label, reason)``. ``status_label`` is ``None`` when the
    artifact may not position geometry, and ``reason`` then names why. This is
    the only place acceptance is decided; nothing in the caller's request can
    substitute for these rows.
    """

    manifest = con.execute(
        "SELECT availability FROM mn_artifact_manifests WHERE artifact_id = ?",
        [artifact_id],
    ).fetchone()
    if manifest is None:
        return None, (
            f"no mn_artifact_manifests row for artifact {artifact_id!r}; "
            "Minnesota identity is unavailable"
        )
    if manifest[0] != "available":
        return None, (
            f"artifact {artifact_id!r} has mn_artifact_manifests.availability "
            f"{manifest[0]!r}, not 'available'"
        )

    score = con.execute(
        "SELECT regulatory_label FROM mn_score_results WHERE artifact_id = ?",
        [artifact_id],
    ).fetchone()
    if score is None:
        # No score row: the manifest alone carries the artifact, and the shared
        # material slot reports the availability fact rather than inventing a
        # regulatory claim the storage layer never made.
        return "available", ""
    if score[0] not in ACCEPTED_REGULATORY_LABELS:
        return None, (
            f"artifact {artifact_id!r} has mn_score_results.regulatory_label "
            f"{score[0]!r}, which is not in the accepted set "
            f"{sorted(ACCEPTED_REGULATORY_LABELS)!r}"
        )
    return score[0], ""


def _inventory_prohibition(entry: dict[str, Any] | None) -> str | None:
    """Name an inventory prohibition that forbids positioning this artifact.

    The accepted-artifact inventory is the policy boundary: it states, in prose,
    which uses each artifact permits. Two of its current entries prohibit
    "facility placement" and "map or 3D point placement", so any prohibition
    mentioning placement fails closed here rather than being overridden by a
    manifest row.
    """

    if entry is None:
        return None
    for prohibited in entry.get("prohibited_uses", []):
        if isinstance(prohibited, str) and "placement" in prohibited.lower():
            return (
                f"the accepted-artifact inventory prohibits {prohibited!r} for "
                f"artifact {entry.get('artifact_id')!r}"
            )
    return None


def _number(value: Any, field: str) -> float:
    """Accept only a real, finite number. ``bool`` is not a coordinate."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AssetBindingError(
            f"placement.coordinates.{field} must be a numeric {PLACEMENT_CRS} "
            f"coordinate, got {type(value).__name__}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise AssetBindingError(
            f"placement.coordinates.{field} must be finite, got {value!r}"
        )
    return number


def _minnesota_geometries(con: duckdb.DuckDBPyConnection) -> list[bytes]:
    try:
        rows = con.execute(_MN_GEOMETRY_SQL).fetchall()
    except duckdb.Error:
        # No Minnesota namespace in this database at all.
        return []
    return [row[0] for row in rows if row[0] is not None]


def _reject_outside_minnesota(
    con: duckdb.DuckDBPyConnection, longitude: float, latitude: float
) -> None:
    """Require the point to fall inside accepted Minnesota geography."""
    geometries = _minnesota_geometries(con)
    if geometries:
        from shapely.geometry import Point
        from shapely.wkb import loads as wkb_loads

        point = Point(longitude, latitude)
        if any(wkb_loads(bytes(wkb)).covers(point) for wkb in geometries):
            return
        raise AssetBindingError(
            f"placement coordinates ({longitude}, {latitude}) fall outside the "
            "accepted Minnesota geography artifact"
        )

    west, south, east, north = MINNESOTA_BBOX
    if not (west <= longitude <= east and south <= latitude <= north):
        raise AssetBindingError(
            f"placement coordinates ({longitude}, {latitude}) fall outside the "
            f"Minnesota bounding box {MINNESOTA_BBOX}"
        )


def _validated_coordinates(
    con: duckdb.DuckDBPyConnection, placement: dict[str, Any]
) -> dict[str, Any]:
    coordinates = placement.get("coordinates")
    if not isinstance(coordinates, dict):
        raise AssetBindingError("placement.coordinates must be an object")

    declared_crs = coordinates.get("crs", placement.get("crs", PLACEMENT_CRS))
    if declared_crs != PLACEMENT_CRS:
        raise AssetBindingError(
            f"placement coordinates must be declared {PLACEMENT_CRS}, got "
            f"{declared_crs!r}"
        )

    longitude = _number(coordinates.get("longitude"), "longitude")
    latitude = _number(coordinates.get("latitude"), "latitude")
    for value, (lower, upper), axis in (
        (longitude, LONGITUDE_RANGE, "longitude"),
        (latitude, LATITUDE_RANGE, "latitude"),
    ):
        if not lower <= value <= upper:
            raise AssetBindingError(
                f"placement.coordinates.{axis} {value} is not a valid "
                f"{PLACEMENT_CRS} {axis} in [{lower}, {upper}]"
            )
    _reject_outside_minnesota(con, longitude, latitude)
    return {"longitude": longitude, "latitude": latitude, "crs": PLACEMENT_CRS}


def _validated_scene_id(placement: dict[str, Any], artifact_id: str) -> str:
    scene_id = placement.get("scene_id")
    if not isinstance(scene_id, str) or not scene_id:
        raise AssetBindingError("placement.scene_id must be a non-empty string")
    if not scene_id.startswith(artifact_id):
        # Scene identity is derived from accepted evidence, never invented by the
        # requester: it must live under the artifact that supplied it.
        raise AssetBindingError(
            f"placement.scene_id {scene_id!r} is not namespaced under its source "
            f"artifact {artifact_id!r}"
        )
    return scene_id


def _validated_truth_label(
    placement: dict[str, Any], inventory: dict[str, Any]
) -> None:
    """Reject a truth_label outside the inventory's declared vocabulary.

    The label is *not* an acceptance input -- storage decides that -- but a
    request carrying a token the inventory never defined is a contract breach,
    not a missing artifact.
    """

    truth_label = placement.get("truth_label")
    if truth_label is None:
        return
    known = inventory.get("truth_labels", [])
    if truth_label not in known:
        raise AssetBindingError(
            f"placement.truth_label {truth_label!r} is not one of the accepted "
            f"artifact inventory's truth_labels {list(known)!r}"
        )


def load_pack_binaries(archive_path: Path) -> dict[str, Any]:
    """Read whether a pack's GLB binaries are actually published.

    `data/3d/packs/flux-grid-v1/archive.json` is the only place that records
    it. A pack whose `download_url` is null is *not* fetchable no matter how
    well-formed the `glb_uri` values in a request are, and a consumer must be
    able to see that from the binding rather than discovering it as a 404.
    """
    archive = _read_json(archive_path)
    publication_status = archive.get("publication_status")
    if not isinstance(publication_status, str) or not publication_status:
        raise AssetBindingError("pack archive publication_status is required")
    download_url = archive.get("download_url")
    if download_url is not None and not isinstance(download_url, str):
        raise AssetBindingError("pack archive download_url must be a string or null")
    return {
        "publication_status": publication_status,
        "download_url": download_url,
        "fetchable": bool(download_url),
    }


def bind_asset(
    con: duckdb.DuckDBPyConnection,
    catalog: dict[str, Any],
    inventory: dict[str, Any],
    model: dict[str, Any],
    placement: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate model metadata and bind it only to accepted Minnesota evidence.

    Missing or ineligible evidence is a normal demo state: callers receive a
    labelled catalogue preview naming the reason, with no coordinates and no
    scene identity. Malformed input -- a coordinate that cannot be EPSG:4326, a
    point outside Minnesota, an undeclared archetype -- is a contract breach and
    raises :class:`AssetBindingError`.
    """
    archetype_id = model.get("archetype_id")
    if not isinstance(archetype_id, str):
        raise AssetBindingError("model.archetype_id is required")
    entry = _catalog_entry(catalog, archetype_id)

    if model.get("contract_id") != CONTRACT_ID:
        raise AssetBindingError("model contract_id does not match the shared contract")
    if not isinstance(model.get("glb_uri"), str) or not model["glb_uri"].endswith(
        ".glb"
    ):
        raise AssetBindingError("model.glb_uri must identify a .glb import")
    for field in ("footprint_m", "connectors", "lod_triangles"):
        if model.get(field) != entry[field]:
            raise AssetBindingError(f"model {field} does not match archetype metadata")

    if not placement:
        return _preview(entry, "no accepted Minnesota placement artifact was supplied")

    _validated_truth_label(placement, inventory)

    artifact_id = placement.get("source_artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id:
        return _preview(
            entry, "placement.source_artifact_id does not name a Minnesota artifact"
        )

    status_label, reason = _acceptance(con, artifact_id)
    if status_label is None:
        return _preview(entry, reason)
    if prohibition := _inventory_prohibition(_inventory_entry(inventory, artifact_id)):
        return _preview(entry, prohibition)

    scene_id = _validated_scene_id(placement, artifact_id)
    coordinates = _validated_coordinates(con, placement)

    return {
        "render_mode": "placed",
        "scene_id": scene_id,
        "source_artifact_id": artifact_id,
        "semantic_type": entry["category"],
        "archetype_id": entry["id"],
        "crs": PLACEMENT_CRS,
        "coordinates": coordinates,
        "footprint_m": entry["footprint_m"],
        "connectors": entry["connectors"],
        "lod_triangles": entry["lod_triangles"],
        "material": {"slot": MATERIAL_SLOT, "status_label": status_label},
    }


def bind_city_essentials(
    con: duckdb.DuckDBPyConnection,
    catalog: dict[str, Any],
    inventory: dict[str, Any],
    request: dict[str, Any],
    *,
    binaries: dict[str, Any],
) -> dict[str, Any]:
    """Bind the complete Gate 6 city-essential pack.

    The pack is intentionally all-or-nothing: the seven archetypes are the
    Gate 6 contract, so a caller cannot silently render a partial city scene.
    Each member still goes through :func:`bind_asset`, which means an absent or
    ineligible Minnesota artifact remains a non-geographic catalogue preview.

    ``binaries`` is the pack publication record from :func:`load_pack_binaries`.
    It is required, not defaulted: every binding carries its asset's `glb_uri`
    next to the status of the pack that URI lives in, so a consumer of an
    unpublished pack sees `fetchable: false` instead of inferring that seven
    resolvable binaries exist.
    """
    if request.get("format") != CITY_ESSENTIALS_FORMAT:
        raise AssetBindingError("city-essentials request has an unsupported format")
    if request.get("contract_id") != CONTRACT_ID:
        raise AssetBindingError(
            "city-essentials request contract_id does not match the shared contract"
        )
    assets = request.get("assets")
    if not isinstance(assets, list):
        raise AssetBindingError("city-essentials request.assets must be an array")

    by_archetype: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("model"), dict):
            raise AssetBindingError(
                "each city-essentials asset must contain a model object"
            )
        archetype_id = asset["model"].get("archetype_id")
        if not isinstance(archetype_id, str):
            raise AssetBindingError(
                "each city-essentials model.archetype_id must be a string"
            )
        if archetype_id in by_archetype:
            raise AssetBindingError(
                f"city-essentials request duplicates archetype {archetype_id!r}"
            )
        by_archetype[archetype_id] = asset

    actual_ids = set(by_archetype)
    expected_ids = set(CITY_ESSENTIAL_ARCHETYPE_IDS)
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        unexpected = sorted(actual_ids - expected_ids)
        raise AssetBindingError(
            "city-essentials request must contain exactly the seven Gate 6 "
            f"archetypes; missing={missing!r}, unexpected={unexpected!r}"
        )

    bindings = []
    for archetype_id in CITY_ESSENTIAL_ARCHETYPE_IDS:
        model = by_archetype[archetype_id]["model"]
        binding = bind_asset(
            con,
            catalog,
            inventory,
            model,
            by_archetype[archetype_id].get("placement"),
        )
        # The binary the request names is a separate fact from the placement:
        # the geometry can be absent while the evidence is accepted, and both
        # states have to survive to the consumer under their own names.
        binding["glb_binary"] = {"uri": model["glb_uri"], **binaries}
        bindings.append(binding)
    return {
        "format": CITY_ESSENTIALS_FORMAT,
        "contract_id": CONTRACT_ID,
        "binaries": binaries,
        "assets": bindings,
        "summary": {
            "total": len(bindings),
            "placed": sum(binding["render_mode"] == "placed" for binding in bindings),
            "catalog_previews": sum(
                binding["render_mode"] == "catalog_preview" for binding in bindings
            ),
        },
    }


def _validated_runtime_release(request: dict[str, Any]) -> dict[str, str]:
    """Require the exact release read back for the later-asset handoff."""
    release = request.get("runtime_release")
    if not isinstance(release, dict):
        raise AssetBindingError(
            "later-infrastructure request.runtime_release is required"
        )
    actual = {key: release.get(key) for key in RUNTIME_RELEASE}
    if actual != RUNTIME_RELEASE:
        raise AssetBindingError(
            "later-infrastructure request must pin the verified Flux Grid runtime release"
        )
    return dict(RUNTIME_RELEASE)


def bind_later_infrastructure(
    con: duckdb.DuckDBPyConnection,
    catalog: dict[str, Any],
    inventory: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    """Bind the four later-infrastructure archetypes without inventing a site."""
    if request.get("format") != LATER_INFRASTRUCTURE_FORMAT:
        raise AssetBindingError("later-infrastructure request has an unsupported format")
    if request.get("contract_id") != CONTRACT_ID:
        raise AssetBindingError(
            "later-infrastructure request contract_id does not match the shared contract"
        )
    runtime_release = _validated_runtime_release(request)
    assets = request.get("assets")
    if not isinstance(assets, list):
        raise AssetBindingError("later-infrastructure request.assets must be an array")

    by_archetype: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("model"), dict):
            raise AssetBindingError(
                "each later-infrastructure asset must contain a model object"
            )
        archetype_id = asset["model"].get("archetype_id")
        if not isinstance(archetype_id, str):
            raise AssetBindingError(
                "each later-infrastructure model.archetype_id must be a string"
            )
        if archetype_id in by_archetype:
            raise AssetBindingError(
                f"later-infrastructure request duplicates archetype {archetype_id!r}"
            )
        by_archetype[archetype_id] = asset

    expected_ids = set(LATER_INFRASTRUCTURE_ARCHETYPE_IDS)
    actual_ids = set(by_archetype)
    if actual_ids != expected_ids:
        raise AssetBindingError(
            "later-infrastructure request must contain exactly the four 2WKG-402 "
            f"archetypes; missing={sorted(expected_ids - actual_ids)!r}, "
            f"unexpected={sorted(actual_ids - expected_ids)!r}"
        )

    bindings = [
        bind_asset(
            con,
            catalog,
            inventory,
            by_archetype[archetype_id]["model"],
            by_archetype[archetype_id].get("placement"),
        )
        for archetype_id in LATER_INFRASTRUCTURE_ARCHETYPE_IDS
    ]
    return {
        "format": LATER_INFRASTRUCTURE_FORMAT,
        "contract_id": CONTRACT_ID,
        "runtime_release": runtime_release,
        "assets": bindings,
        "summary": {
            "total": len(bindings),
            "placed": sum(binding["render_mode"] == "placed" for binding in bindings),
            "catalog_previews": sum(
                binding["render_mode"] == "catalog_preview" for binding in bindings
            ),
        },
    }


def bind_from_files(
    catalog_path: Path,
    inventory_path: Path,
    request_path: Path,
    db_path: Path,
    pack_archive_path: Path | None = None,
) -> dict[str, Any]:
    """Load one import request and return its render-safe binding payload.

    This is the file entry point for *every* committed request shape, so a
    request declaring :data:`CITY_ESSENTIALS_FORMAT` is dispatched to
    :func:`bind_city_essentials` here rather than needing its own caller.

    ``db_path`` is the Minnesota DuckDB database that supplies acceptance; it is
    opened read-only because binding never writes evidence.
    """
    request = _read_json(request_path)
    catalog = load_catalog(catalog_path)
    inventory = load_inventory(inventory_path)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        if request.get("format") == CITY_ESSENTIALS_FORMAT:
            return bind_city_essentials(
                con,
                catalog,
                inventory,
                request,
                binaries=load_pack_binaries(pack_archive_path or PACK_ARCHIVE_PATH),
            )
        if request.get("format") == LATER_INFRASTRUCTURE_FORMAT:
            return bind_later_infrastructure(con, catalog, inventory, request)
        return bind_asset(
            con,
            catalog,
            inventory,
            request.get("model", {}),
            request.get("placement"),
        )
    finally:
        con.close()


def bind_city_essentials_from_files(
    catalog_path: Path,
    inventory_path: Path,
    request_path: Path,
    db_path: Path,
    pack_archive_path: Path | None = None,
) -> dict[str, Any]:
    """Load and bind the versioned Gate 6 city-essential request pack."""
    request = _read_json(request_path)
    catalog = load_catalog(catalog_path)
    inventory = load_inventory(inventory_path)
    binaries = load_pack_binaries(pack_archive_path or PACK_ARCHIVE_PATH)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return bind_city_essentials(con, catalog, inventory, request, binaries=binaries)
    finally:
        con.close()


def bind_later_infrastructure_from_files(
    catalog_path: Path,
    inventory_path: Path,
    request_path: Path,
    db_path: Path,
) -> dict[str, Any]:
    """Load the versioned 2WKG-402 request and return its safe bindings."""
    request = _read_json(request_path)
    catalog = load_catalog(catalog_path)
    inventory = load_inventory(inventory_path)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return bind_later_infrastructure(con, catalog, inventory, request)
    finally:
        con.close()

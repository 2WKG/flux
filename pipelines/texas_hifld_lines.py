"""Acquire a source-preserving Texas selection from HIFLD's archived line service.

This module deliberately selects against a supplied Texas boundary polygon.  It
does not use a bounding box, clip source routes, create substations from route
ends, or turn endpoint labels into electrical connectivity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from shapely.geometry import shape
from shapely.geometry.polygon import orient

from pipelines.physical_inventory import artifact_sha256, validate_artifact

SERVICE_URL = (
    "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
    "US_Electric_Power_Transmission_Lines/FeatureServer/0/query"
)
OUT_FIELDS = "ID,TYPE,STATUS,SOURCE,SOURCEDATE,VAL_METHOD,VAL_DATE,OWNER,VOLTAGE,VOLT_CLASS,INFERRED,SUB_1,SUB_2"


def _geometry(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("type") == "Feature":
        value = value.get("geometry", {})
    elif value.get("type") == "FeatureCollection":
        features = value.get("features", [])
        if len(features) != 1:
            raise ValueError(
                "Texas boundary FeatureCollection must contain exactly one feature"
            )
        value = features[0].get("geometry", {})
    if value.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Texas boundary must be a GeoJSON Polygon or MultiPolygon")
    return value


def _esri_polygon(geometry: dict[str, Any]) -> dict[str, Any]:
    """Translate GeoJSON polygon rings to ArcGIS REST polygon syntax.

    The two encodings disagree about ring winding.  GeoJSON (RFC 7946) uses a
    counter-clockwise exterior ring and clockwise holes; Esri JSON reads a
    clockwise ring as an outer ring and a counter-clockwise ring as a hole.
    Handing GeoJSON rings over verbatim therefore asks the service for the
    complement of Texas, or for nothing.  Every exterior ring is emitted
    clockwise and every hole counter-clockwise here, which is also what carries
    multipart grouping across: Esri's flat ``rings`` list distinguishes parts by
    winding, not by nesting, so a MultiPolygon flattens without losing which
    ring belongs to which part.
    """
    polygons = shape(geometry)
    parts = list(getattr(polygons, "geoms", [polygons]))
    rings: list[list[list[float]]] = []
    for part in parts:
        # sign=-1.0 gives a clockwise exterior and counter-clockwise interiors.
        oriented = orient(part, sign=-1.0)
        rings.append([list(point) for point in oriented.exterior.coords])
        rings.extend(
            [list(point) for point in interior.coords]
            for interior in oriented.interiors
        )
    return {"rings": rings, "spatialReference": {"wkid": 4326}}


def fetch_texas_lines(
    boundary: dict[str, Any],
    session: requests.Session | Any = requests,
    capture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return all source-native routes whose geometry intersects Texas.

    ArcGIS receives the actual state polygon in EPSG:4326.  The returned route
    geometry is deliberately unmodified native source geometry; a cross-border
    route is retained whole with its selection semantics recorded in metadata.
    """
    polygon = _geometry(boundary)
    base = {
        "geometry": json.dumps(_esri_polygon(polygon), separators=(",", ":")),
        "geometryType": "esriGeometryPolygon",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": "true",
        "outSR": "4326",
        "outFields": OUT_FIELDS,
        "f": "geojson",
    }
    # A true Texas boundary is too large for a GET query string; POST preserves
    # the polygon instead of degrading the selection to a bounding box.
    ids_response = session.post(
        SERVICE_URL, data={**base, "f": "json", "returnIdsOnly": "true"}, timeout=60
    )
    ids_response.raise_for_status()
    object_ids = ids_response.json().get("objectIds")
    if not isinstance(object_ids, list):
        raise TypeError("HIFLD service did not return objectIds")

    features: list[dict[str, Any]] = []
    response_bytes = len(getattr(ids_response, "content", b""))
    pages = 0
    for offset in range(0, len(object_ids), 1000):
        response = session.post(
            SERVICE_URL,
            data={
                "where": "1=1",
                "returnGeometry": "true",
                "outSR": "4326",
                "outFields": OUT_FIELDS,
                "f": "geojson",
                "objectIds": ",".join(
                    str(item) for item in object_ids[offset : offset + 1000]
                ),
            },
            timeout=60,
        )
        response.raise_for_status()
        response_bytes += len(getattr(response, "content", b""))
        pages += 1
        payload = response.json()
        if payload.get("type") != "FeatureCollection":
            raise RuntimeError("HIFLD service returned a non-GeoJSON feature response")
        if payload.get("exceededTransferLimit") or payload.get("properties", {}).get(
            "exceededTransferLimit"
        ):
            raise RuntimeError(
                "HIFLD service truncated a page (exceededTransferLimit); "
                "the selection would be silently partial"
            )
        features.extend(payload.get("features", []))
    if len(features) != len(object_ids):
        raise RuntimeError(
            f"HIFLD service returned {len(features)} features for "
            f"{len(object_ids)} selected object ids; a partial acquisition must "
            "not be recorded as an observed inventory"
        )

    retrieved_at = datetime.now(UTC).isoformat(timespec="seconds")
    source_hash = hashlib.sha256(
        json.dumps(features, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assets = []
    for feature in features:
        properties = feature.get("properties", {})
        raw_record_id = properties.get("ID")
        if raw_record_id is None or raw_record_id == "":
            raw_record_id = properties.get("OBJECTID_1")
        if raw_record_id is None or raw_record_id == "":
            raise RuntimeError("HIFLD feature lacks an ID")
        if feature.get("geometry") is None:
            raise RuntimeError("HIFLD feature lacks native geometry")
        source_record_id = str(raw_record_id)
        assets.append(
            {
                "asset_id": f"hifld-line:{source_record_id}",
                "asset_class": "line",
                "asset_kind": str(properties.get("TYPE") or "unspecified"),
                "source_id": "hifld-lines-2024-09-30",
                "source_record_id": source_record_id,
                "geometry": feature["geometry"],
                "geometry_crs": "EPSG:4326",
                "geometry_precision_m": None,
                "geometry_accuracy_basis": "Native archived HIFLD geometry; numeric coordinate precision is unpublished. Per-feature SOURCE/SOURCEDATE/VAL_METHOD/VAL_DATE/INFERRED remain in source sidecar.",
                "geometry_derivation_method": None,
                "geometry_status": "source",
            }
        )
    artifact = {
        "artifact_id": "us-tx:physical-inventory:1.0.0",
        "contract_version": "1.0.0",
        "geography_id": "us-tx",
        "artifact_version": "1.0.0",
        "inventory_mode": "physical_observed",
        "electrical_model_mode": "none",
        "created_at": retrieved_at,
        "content_sha256": "0" * 64,
        "sources": [
            {
                "source_id": "hifld-lines-2024-09-30",
                "authority": "Federal User Community / HIFLD archive",
                "source_ref": SERVICE_URL.rsplit("/query", 1)[0],
                "source_version": "Archived service; last data update 2024-09-30",
                "retrieved_at": retrieved_at,
                "license_or_terms": "Esri Master License Agreement in service item metadata",
                "content_sha256": source_hash,
            }
        ],
        "assets": assets,
        "terminals": [],
        "connectivity_edges": [],
        "coverage": [
            {
                "asset_class": "line",
                "scope_id": "us-tx",
                "status": "partial",
                "observed_count": len(assets),
                "denominator_count": None,
                "unknown_count": None,
                "unavailable_count": None,
                "denominator_basis": "unknown",
                "source_scope": "Archived national HIFLD service selected by supplied Texas polygon; no owner-level Texas completeness declaration",
                "reason": "Native observed routes are partial/stale public overlay; endpoint labels are not terminals or edges.",
            }
        ],
    }
    artifact["content_sha256"] = artifact_sha256(artifact)
    validate_artifact(artifact)
    if capture is not None:
        capture.update(
            {
                "retrieved_at": retrieved_at,
                "selected_object_ids": len(object_ids),
                "returned_features": len(features),
                "pages": pages,
                "response_bytes": response_bytes,
                "source_feature_digest": source_hash,
            }
        )
    return artifact


def build_receipt(
    capture: dict[str, Any],
    artifact: dict[str, Any],
    boundary_source: str,
    output: Path,
    output_bytes: int,
    output_sha256: str,
) -> dict[str, Any]:
    """Return the checked-in source-receipt shape used by the rest of data/sources.

    Every number here comes from the acquisition that produced ``artifact``; a
    receipt is never written for a run that did not happen.
    """
    return {
        "retrieved_at": capture["retrieved_at"],
        "provider": "Federal User Community / HIFLD archive",
        "source_url": SERVICE_URL.rsplit("/query", 1)[0],
        "vintage": "Archived service; last data update 2024-09-30",
        "license_access": "Esri Master License Agreement in the service item metadata",
        "capture_method": (
            f"ArcGIS REST POST query against {SERVICE_URL}: one returnIdsOnly=true "
            f"selection with geometryType=esriGeometryPolygon, "
            f"spatialRel=esriSpatialRelIntersects, inSR=4326, then "
            f"{capture['pages']} objectIds page(s) of at most 1000 ids with "
            f"outSR=4326 and f=geojson"
        ),
        "boundary_source": boundary_source,
        "files": {
            output.name: {
                "path": str(output),
                "bytes": output_bytes,
                "sha256": output_sha256,
                "tracked": False,
                "note": (
                    "data/physical-inventory/ is gitignored bulk output; "
                    "regenerate with the command in capture_method"
                ),
            }
        },
        "verification": {
            "selected_object_ids": capture["selected_object_ids"],
            "returned_features": capture["returned_features"],
            "features_reconciled_to_selected_ids": (
                capture["returned_features"] == capture["selected_object_ids"]
            ),
            "response_bytes": capture["response_bytes"],
            "source_feature_digest": capture["source_feature_digest"],
            "artifact_content_sha256": artifact["content_sha256"],
            "artifact_validated_by": "pipelines.physical_inventory.validate_artifact",
            "observed_routes": len(artifact["assets"]),
            "terminals_created": len(artifact["terminals"]),
            "connectivity_edges_created": len(artifact["connectivity_edges"]),
            "result": "passed",
        },
        "coverage": artifact["coverage"][0],
        "uncertainty": (
            "The archived national HIFLD overlay publishes no owner-level Texas "
            "completeness denominator, so coverage stays partial. Routes are "
            "retained whole and unclipped; SUB_1/SUB_2 remain source attributes "
            "and are not terminals or electrical connectivity."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--texas-boundary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument(
        "--boundary-source",
        default="unspecified",
        help="Prose identifying the boundary artifact, recorded in the receipt.",
    )
    args = parser.parse_args()
    boundary = json.loads(args.texas_boundary.read_text(encoding="utf-8"))
    capture: dict[str, Any] = {}
    artifact = fetch_texas_lines(boundary, capture=capture)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(artifact, indent=2) + "\n"
    args.output.write_text(payload, encoding="utf-8")
    if args.receipt is not None:
        receipt = build_receipt(
            capture,
            artifact,
            args.boundary_source,
            args.output,
            len(payload.encode()),
            hashlib.sha256(payload.encode()).hexdigest(),
        )
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

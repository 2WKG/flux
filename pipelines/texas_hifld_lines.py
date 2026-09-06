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
            raise ValueError("Texas boundary FeatureCollection must contain exactly one feature")
        value = features[0].get("geometry", {})
    if value.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Texas boundary must be a GeoJSON Polygon or MultiPolygon")
    return value


def _esri_polygon(geometry: dict[str, Any]) -> dict[str, Any]:
    """Translate GeoJSON polygon rings to ArcGIS REST polygon syntax."""
    if geometry["type"] == "Polygon":
        rings = geometry["coordinates"]
    else:
        rings = [ring for polygon in geometry["coordinates"] for ring in polygon]
    return {"rings": rings, "spatialReference": {"wkid": 4326}}


def fetch_texas_lines(boundary: dict[str, Any], session: requests.Session | Any = requests) -> dict[str, Any]:
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
    for offset in range(0, len(object_ids), 1000):
        response = session.post(
            SERVICE_URL,
            data={
                "where": "1=1", "returnGeometry": "true", "outSR": "4326",
                "outFields": OUT_FIELDS, "f": "geojson",
                "objectIds": ",".join(str(item) for item in object_ids[offset : offset + 1000]),
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("type") != "FeatureCollection":
            raise RuntimeError("HIFLD service returned a non-GeoJSON feature response")
        features.extend(payload.get("features", []))

    retrieved_at = datetime.now(UTC).isoformat(timespec="seconds")
    source_hash = hashlib.sha256(
        json.dumps(features, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assets = []
    for feature in features:
        properties = feature.get("properties", {})
        source_record_id = str(properties.get("ID") or properties.get("OBJECTID_1"))
        if not source_record_id or feature.get("geometry") is None:
            raise RuntimeError("HIFLD feature lacks an ID or native geometry")
        assets.append({
            "asset_id": f"hifld-line:{source_record_id}", "asset_class": "line",
            "asset_kind": str(properties.get("TYPE") or "unspecified"),
            "source_id": "hifld-lines-2024-09-30", "source_record_id": source_record_id,
            "geometry": feature["geometry"], "geometry_crs": "EPSG:4326",
            "geometry_precision_m": None, "geometry_accuracy_basis": "Native archived HIFLD geometry; numeric coordinate precision is unpublished. Per-feature SOURCE/SOURCEDATE/VAL_METHOD/VAL_DATE/INFERRED remain in source sidecar.",
            "geometry_derivation_method": None,
            "geometry_status": "source",
        })
    artifact = {
        "artifact_id": "us-tx:physical-inventory:1.0.0", "contract_version": "1.0.0",
        "geography_id": "us-tx", "artifact_version": "1.0.0", "inventory_mode": "physical_observed",
        "electrical_model_mode": "none", "created_at": retrieved_at, "content_sha256": "0" * 64,
        "sources": [{"source_id": "hifld-lines-2024-09-30", "authority": "Federal User Community / HIFLD archive", "source_ref": SERVICE_URL.rsplit("/query", 1)[0], "source_version": "Archived service; last data update 2024-09-30", "retrieved_at": retrieved_at, "license_or_terms": "Esri Master License Agreement in service item metadata", "content_sha256": source_hash}],
        "assets": assets, "terminals": [], "connectivity_edges": [],
        "coverage": [{"asset_class": "line", "scope_id": "us-tx", "status": "partial", "observed_count": len(assets), "denominator_count": None, "unknown_count": None, "unavailable_count": None, "denominator_basis": "unknown", "source_scope": "Archived national HIFLD service selected by supplied Texas polygon; no owner-level Texas completeness declaration", "reason": "Native observed routes are partial/stale public overlay; endpoint labels are not terminals or edges."}],
    }
    artifact["content_sha256"] = artifact_sha256(artifact)
    return validate_artifact(artifact)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--texas-boundary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    boundary = json.loads(args.texas_boundary.read_text(encoding="utf-8"))
    artifact = fetch_texas_lines(boundary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

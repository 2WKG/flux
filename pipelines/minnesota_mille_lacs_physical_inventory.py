"""Build a source-native, county-scoped physical inventory from Mille Lacs GIS.

The source supplies geometry and attributes, but no terminals or electrical
edges.  This module deliberately leaves those arrays empty and labels the
county layer as partial source coverage rather than a Minnesota inventory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pipelines.physical_inventory import (
    CONTRACT_VERSION,
    PhysicalInventoryError,
    artifact_sha256,
    validate_artifact,
)

SERVICE_ROOT = (
    "https://gis.co.mille-lacs.mn.us/arcgis/rest/services/Utilities/MapServer"
)
LAYER_QUERY = "query?where=1%3D1&outFields=*&returnGeometry=true&f=json"
LINES_LAYER = 2
SUBSTATIONS_LAYER = 0
LINES_SOURCE_ID = (
    "mille_lacs_county_utilities_mapserver_2026:transmission-lines-layer-2"
)
SUBSTATIONS_SOURCE_ID = "mille_lacs_county_utilities_mapserver_2026:substations-layer-0"
NATIVE_CRS = "ESRI:103705"
SOURCE_COPYRIGHT = "Mille Lacs County MN"


def layer_query_url(layer: int) -> str:
    """Return the exact query URL whose response bytes are captured for a layer."""
    return f"{SERVICE_ROOT}/{layer}/{LAYER_QUERY}"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_row(
    *, source_id: str, layer: int, description: str, path: Path, retrieved_at: str
) -> dict[str, Any]:
    """Describe one captured layer, digesting exactly one named input file."""
    return {
        "source_id": source_id,
        "authority": (
            f"Mille Lacs County GIS public Utilities MapServer layer {layer} "
            f"({description}); county-scoped source only. Service copyrightText: "
            f"{SOURCE_COPYRIGHT}."
        ),
        "source_ref": layer_query_url(layer),
        "source_version": f"live MapServer layer {layer} query captured {retrieved_at}",
        "retrieved_at": retrieved_at,
        "license_or_terms": (
            "No reusable license was published by the service; copyrightText is "
            f"{SOURCE_COPYRIGHT!r}. Retain attribution and verify terms before "
            "redistribution."
        ),
        "content_sha256": _sha(path),
    }


def _geometry(feature: dict[str, Any], geometry_type: str) -> dict[str, Any]:
    geometry = feature["geometry"]
    if geometry_type == "esriGeometryPoint":
        return {"type": "Point", "coordinates": [geometry["x"], geometry["y"]]}
    paths = geometry["paths"]
    if len(paths) == 1:
        return {"type": "LineString", "coordinates": paths[0]}
    return {"type": "MultiLineString", "coordinates": paths}


def _features(payload: dict[str, Any], expected_type: str) -> list[dict[str, Any]]:
    if payload.get("geometryType") != expected_type:
        raise PhysicalInventoryError(
            f"expected {expected_type}, got {payload.get('geometryType')!r}"
        )
    if (
        payload.get("spatialReference", {}).get(
            "latestWkid", payload.get("spatialReference", {}).get("wkid")
        )
        != 103705
    ):
        raise PhysicalInventoryError("Mille Lacs source CRS must be WKID 103705")
    features = payload.get("features")
    if not isinstance(features, list):
        raise PhysicalInventoryError("source response has no feature array")
    return sorted(features, key=lambda row: row["attributes"]["OBJECTID"])


def build_artifact(
    *, lines_path: Path, substations_path: Path, retrieved_at: str
) -> dict[str, Any]:
    lines_payload = json.loads(lines_path.read_text(encoding="utf-8"))
    substations_payload = json.loads(substations_path.read_text(encoding="utf-8"))
    lines = _features(lines_payload, "esriGeometryPolyline")
    substations = _features(substations_payload, "esriGeometryPoint")
    # One source row per captured layer so each content_sha256 digests exactly one
    # named, independently fetchable file rather than a blend of two.
    lines_source = _source_row(
        source_id=LINES_SOURCE_ID,
        layer=LINES_LAYER,
        description="Transmission Lines",
        path=lines_path,
        retrieved_at=retrieved_at,
    )
    substations_source = _source_row(
        source_id=SUBSTATIONS_SOURCE_ID,
        layer=SUBSTATIONS_LAYER,
        description="Substations",
        path=substations_path,
        retrieved_at=retrieved_at,
    )
    basis = "Native geometry supplied by Mille Lacs County GIS; numeric positional precision is unpublished in queried metadata."
    assets: list[dict[str, Any]] = []
    for feature in lines:
        attrs, oid = feature["attributes"], str(feature["attributes"]["OBJECTID"])
        assets.append(
            {
                "asset_id": f"{LINES_SOURCE_ID}:line:{oid}",
                "asset_class": "line",
                "asset_kind": "transmission_or_subtransmission_line",
                "source_id": LINES_SOURCE_ID,
                "source_record_id": oid,
                "geometry": _geometry(feature, "esriGeometryPolyline"),
                "geometry_crs": NATIVE_CRS,
                "geometry_precision_m": None,
                "geometry_accuracy_basis": basis,
                "geometry_derivation_method": None,
                "geometry_status": "source",
                "source_attributes": {
                    key: attrs.get(key)
                    for key in (
                        "COMPANY",
                        "COMP_AB",
                        "COMP_ID",
                        "ACDC",
                        "VOLTAGE",
                        "MILES_GIS",
                        "INTERSTATE",
                        "SOURCE",
                        "DOCKET",
                    )
                },
            }
        )
    for feature in substations:
        attrs, oid = feature["attributes"], str(feature["attributes"]["OBJECTID"])
        assets.append(
            {
                "asset_id": f"{SUBSTATIONS_SOURCE_ID}:substation:{oid}",
                "asset_class": "substation",
                "asset_kind": "substation",
                "source_id": SUBSTATIONS_SOURCE_ID,
                "source_record_id": oid,
                "geometry": _geometry(feature, "esriGeometryPoint"),
                "geometry_crs": NATIVE_CRS,
                "geometry_precision_m": None,
                "geometry_accuracy_basis": basis,
                "geometry_derivation_method": None,
                "geometry_status": "source",
                "source_attributes": {
                    key: attrs.get(key)
                    for key in (
                        "COMPANY",
                        "COMP_AB",
                        "COMP_ID",
                        "SUB_TYPE",
                        "SOURCE",
                        "DOCKET",
                    )
                },
            }
        )
    # The raw source responses remain the attribute-preserving evidence files.
    # The shared physical-asset contract deliberately stores only identity and
    # geometry/provenance fields, so it cannot accidentally treat attributes as
    # terminals or edges.
    contract_assets = [
        {key: value for key, value in row.items() if key != "source_attributes"}
        for row in assets
    ]
    artifact = {
        "artifact_id": "mn:mille-lacs-county:physical-inventory:1.0.0",
        "contract_version": CONTRACT_VERSION,
        "geography_id": "mn:mille-lacs-county",
        "artifact_version": "1.0.0",
        "inventory_mode": "physical_observed",
        "electrical_model_mode": "none",
        "created_at": retrieved_at,
        "content_sha256": "0" * 64,
        "sources": [lines_source, substations_source],
        "assets": contract_assets,
        "terminals": [],
        "connectivity_edges": [],
        "coverage": [
            {
                "asset_class": "line",
                "scope_id": "mn:mille-lacs-county:utilities-mapserver:layer-2",
                "status": "partial",
                "observed_count": len(lines),
                "denominator_count": None,
                "unknown_count": None,
                "unavailable_count": None,
                "denominator_basis": "unknown: the service publishes no authoritative count of in-scope transmission lines, so the returned feature count is an observation and not a denominator",
                "source_scope": "Mille Lacs County Utilities MapServer layer 2 only; not countywide or statewide completeness",
                "reason": "No source-backed statewide line denominator or connectivity is available.",
            },
            {
                "asset_class": "substation",
                "scope_id": "mn:mille-lacs-county:utilities-mapserver:layer-0",
                "status": "partial",
                "observed_count": len(substations),
                "denominator_count": None,
                "unknown_count": None,
                "unavailable_count": None,
                "denominator_basis": "unknown: the service publishes no authoritative count of in-scope substations, so the returned feature count is an observation and not a denominator",
                "source_scope": "Mille Lacs County Utilities MapServer layer 0 only; not countywide or statewide completeness",
                "reason": "No source-backed statewide substation denominator or terminals are available.",
            },
        ],
    }
    artifact["content_sha256"] = artifact_sha256(artifact)
    validate_artifact(artifact)
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lines", type=Path, required=True)
    parser.add_argument("--substations", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    artifact = build_artifact(
        lines_path=args.lines,
        substations_path=args.substations,
        retrieved_at=args.retrieved_at,
    )
    args.output.write_text(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

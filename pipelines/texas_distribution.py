"""Acquire Texas DISTRIBUTION coverage evidence and write the contract artifact.

Texas distribution-level geometry is largely not public.  The honest result of
this lane is therefore an explicit, structured *unavailable* coverage record for
every distribution asset class, naming the owner and the request route, next to
the small set of owner-published artifacts that genuinely are public.

Three Texas owners publish their own electric service-area polygons in a native
projected CRS.  A service area is an owner footprint.  It is **not** a feeder,
a cable, a device or a service connection, so this module deliberately retrieves
those layers, digests them, and creates **no** physical asset from them.  The
2WKG-441 asset taxonomy has no service-area class, and inventing one from a
boundary polygon would be exactly the proxy fabrication this lane forbids.

What this module never does:

* render aggregate load, streets, parcels, imagery, address points or any other
  proxy as feeder or service topology;
* turn a layer merely *named* "Electric Distribution" into feeder geometry;
* treat traffic-signal or streetlight poles as distribution supports;
* acquire meter, premise, account or customer-level records;
* record an unknown distribution count as zero.

Source availability, owner records and request routes live in
``data/sources/texas-distribution-source-authority-ledger-v1.json`` and are
validated by ``scripts/validate_source_authority_ledger.py``.  Provenance, CRS,
readiness and unavailable-state mechanisms are reused from
``pipelines.physical_inventory``; nothing parallel is defined here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from pipelines.physical_inventory import (
    PhysicalInventoryError,
    artifact_sha256,
    validate_artifact,
)

GEOGRAPHY_ID = "us-tx-distribution"
ARTIFACT_VERSION = "1.0.0"
COVERAGE_SCOPE_ID = "us-tx:distribution"
LEDGER_PATH = "data/sources/texas-distribution-source-authority-ledger-v1.json"

# Attribute names that would carry meter, premise, account or customer-level
# detail.  This lane establishes physical coverage, so a source that carries any
# of them fails the acquisition rather than being quietly published.
PROHIBITED_ATTRIBUTE_PATTERN = re.compile(
    r"CUSTOMER|METER|PREMISE|PREMISES|ACCOUNT|SUBSCRIBER|BILLING|RATEPAYER",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ServiceAreaLayer:
    """One owner-published electric service-area layer that is genuinely public."""

    source_id: str
    authority: str
    layer_url: str
    native_crs: str
    native_wkid: int
    source_version: str
    license_or_terms: str


# Retrieved and verified on 2026-09-06; see the ledger for each layer's receipt.
SERVICE_AREA_LAYERS: tuple[ServiceAreaLayer, ...] = (
    ServiceAreaLayer(
        source_id="austin-energy-electric-service-area",
        authority="City of Austin (Austin Energy)",
        layer_url=(
            "https://services.arcgis.com/0L95CJ0VTaxqcmED/arcgis/rest/services/"
            "UTILITIESCOMMUNICATION_austin_energy_service_area/FeatureServer/0"
        ),
        native_crs="EPSG:2277",
        native_wkid=2277,
        source_version=(
            "Hosted feature service, serviceDescription 'Austin Energy Electric "
            "Utility Service Area'; the publisher declares no version string"
        ),
        license_or_terms="City of Austin open data terms published with the hosted feature service",
    ),
    ServiceAreaLayer(
        source_id="new-braunfels-utilities-electric-service-boundary",
        authority="New Braunfels Utilities",
        layer_url=(
            "https://services.arcgis.com/yHSU3Q4NlapEfzn5/arcgis/rest/services/"
            "New_Braunfels_Utilities_Service_Boundaries/FeatureServer/0"
        ),
        native_crs="EPSG:2278",
        native_wkid=2278,
        source_version=(
            "Hosted feature service, serviceDescription 'NBU Service Boundary', "
            "layer 0 'ElectricBoundary'; the publisher declares no version string"
        ),
        license_or_terms="Publisher's hosted feature service terms",
    ),
    ServiceAreaLayer(
        source_id="granbury-electric-distribution-provider-areas",
        authority="City of Granbury, Texas",
        layer_url=(
            "https://services6.arcgis.com/wHtOhDQeUxQY5fQy/arcgis/rest/services/"
            "Electric_Distribution/FeatureServer/90"
        ),
        native_crs="EPSG:2276",
        native_wkid=2276,
        source_version=(
            "Hosted feature service 'Electric_Distribution', layer 90 'ElectricDist'; "
            "the publisher declares no version string"
        ),
        license_or_terms="Publisher's hosted feature service terms",
    ),
)

_OWNER_ROUTE = (
    "Owner-held critical energy infrastructure; no public machine-readable Texas "
    "source was found. Owners and their written request routes are recorded in "
    f"{LEDGER_PATH}. The count is unknown, not zero."
)

# Every distribution class this lane is responsible for, expressed in the
# 2WKG-441 asset taxonomy.  Each stays unavailable with a null denominator.
DISTRIBUTION_COVERAGE_CLASSES: tuple[tuple[str, str], ...] = (
    ("distribution_feeder", "Primary distribution feeders"),
    ("cable", "Underground and overhead distribution cable"),
    ("substation", "Distribution substations"),
    ("transformer", "Distribution transformers"),
    (
        "distribution_equipment",
        "Distribution switching, protection and regulation devices",
    ),
    ("support", "Distribution supports"),
    ("pole", "Distribution poles"),
)


class TexasDistributionError(RuntimeError):
    """A distribution acquisition that must not be recorded as an observation."""


def _get(session: Any, url: str, params: dict[str, str]) -> requests.Response:
    response = session.get(url, params=params, timeout=90)
    response.raise_for_status()
    return response


def fetch_service_area_layer(
    layer: ServiceAreaLayer, session: requests.Session | Any = requests
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Retrieve one owner service-area layer in its own native CRS.

    The count query and the feature query must agree, the service must not
    report a truncated page, and the payload must carry the CRS the ledger
    declares.  Any disagreement fails the acquisition: a partial or reprojected
    capture must never be published as an observation.
    """
    count_response = _get(
        session,
        f"{layer.layer_url}/query",
        {"where": "1=1", "returnCountOnly": "true", "f": "json"},
    )
    count_payload = count_response.json()
    declared_count = count_payload.get("count")
    if not isinstance(declared_count, int):
        raise TexasDistributionError(
            f"{layer.source_id}: the service returned no feature count"
        )

    # outSR is deliberately omitted so the service answers in its own CRS.
    feature_response = _get(
        session,
        f"{layer.layer_url}/query",
        {"where": "1=1", "outFields": "*", "returnGeometry": "true", "f": "json"},
    )
    payload = feature_response.json()
    if payload.get("exceededTransferLimit") is True:
        raise TexasDistributionError(
            f"{layer.source_id}: the service truncated the response "
            "(exceededTransferLimit); a partial capture is not an observation"
        )
    features = payload.get("features")
    if not isinstance(features, list) or len(features) != declared_count:
        returned = len(features) if isinstance(features, list) else None
        raise TexasDistributionError(
            f"{layer.source_id}: the service returned {returned!r} features for a "
            f"declared count of {declared_count}"
        )
    spatial_reference = payload.get("spatialReference") or {}
    observed_wkid = spatial_reference.get("latestWkid") or spatial_reference.get("wkid")
    if observed_wkid != layer.native_wkid:
        raise TexasDistributionError(
            f"{layer.source_id}: the service answered in CRS {observed_wkid!r}, "
            f"but the ledger declares {layer.native_crs}"
        )
    for feature in features:
        offending = sorted(
            name
            for name in (feature.get("attributes") or {})
            if PROHIBITED_ATTRIBUTE_PATTERN.search(name)
        )
        if offending:
            raise TexasDistributionError(
                f"{layer.source_id}: refusing to ingest customer-level attributes {offending}"
            )

    raw = feature_response.content
    retrieved_at = datetime.now(UTC).isoformat(timespec="seconds")
    source = {
        "source_id": layer.source_id,
        "authority": layer.authority,
        "source_ref": layer.layer_url,
        "source_version": layer.source_version,
        "retrieved_at": retrieved_at,
        "license_or_terms": layer.license_or_terms,
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }
    capture = {
        "source_id": layer.source_id,
        "layer_url": layer.layer_url,
        "declared_count": declared_count,
        "returned_features": len(features),
        "native_crs": layer.native_crs,
        "observed_wkid": observed_wkid,
        "response_bytes": len(raw),
        "count_response_bytes": len(count_response.content),
        "content_sha256": source["content_sha256"],
        "retrieved_at": retrieved_at,
        "raw": raw,
        "assets_created": 0,
    }
    return source, capture


VALIDATOR_NAME = "pipelines.physical_inventory.validate_artifact"


def validate_against_contract(
    artifact: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Run the shared contract validator and return what it actually did.

    Both outcomes are reachable and both are recorded.  The receipt's
    ``verification.result`` is read off this record rather than written as a
    literal, so a receipt can say ``failed`` and a run that never reached the
    validator cannot say ``passed``.
    """
    try:
        validated = validate_artifact(artifact)
    except PhysicalInventoryError as error:
        return None, {
            "artifact_validated_by": VALIDATOR_NAME,
            "result": "failed",
            "detail": str(error),
        }
    return validated, {"artifact_validated_by": VALIDATOR_NAME, "result": "passed"}


def build_artifact(
    sources: list[dict[str, Any]], created_at: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the validated artifact and the validation record it earned.

    ``assets`` is empty on purpose.  The retrieved sources carry owner
    service-area boundaries, and a boundary is not a physical distribution
    asset, so every distribution class is recorded as unavailable with a null
    denominator rather than as an observed count.
    """
    artifact = {
        "artifact_id": f"{GEOGRAPHY_ID}:physical-inventory:{ARTIFACT_VERSION}",
        "contract_version": "1.0.0",
        "geography_id": GEOGRAPHY_ID,
        "artifact_version": ARTIFACT_VERSION,
        "inventory_mode": "physical_observed",
        "electrical_model_mode": "none",
        "created_at": created_at,
        "content_sha256": "0" * 64,
        "sources": sources,
        "assets": [],
        "terminals": [],
        "connectivity_edges": [],
        "coverage": [
            {
                "asset_class": asset_class,
                "scope_id": COVERAGE_SCOPE_ID,
                "status": "unavailable",
                "observed_count": 0,
                "denominator_count": None,
                "unknown_count": None,
                "unavailable_count": None,
                "denominator_basis": "unknown",
                "source_scope": (
                    "Owner-published Texas electric service-area boundaries retrieved "
                    "for owner attribution only; they contain no distribution asset "
                    "geometry, so this class has no observed asset and no denominator."
                ),
                "reason": f"{label} in Texas. {_OWNER_ROUTE}",
            }
            for asset_class, label in DISTRIBUTION_COVERAGE_CLASSES
        ],
    }
    artifact["content_sha256"] = artifact_sha256(artifact)
    validated, verification = validate_against_contract(artifact)
    if validated is None:
        raise TexasDistributionError(
            "the Texas distribution artifact failed the shared physical-inventory "
            f"contract and was not published: {verification['detail']}"
        )
    return validated, verification


def build_receipt(
    captures: list[dict[str, Any]],
    artifact: dict[str, Any],
    output: Path,
    output_bytes: int,
    output_sha256: str,
    verification: dict[str, Any],
) -> dict[str, Any]:
    """Return the checked-in source receipt for one real acquisition run."""
    return {
        "retrieved_at": artifact["created_at"],
        "provider": "Three Texas electric utility owners publishing their own service-area layers",
        "source_url": [capture["layer_url"] for capture in captures],
        "vintage": "Live hosted feature services; no publisher declares a version string",
        "license_access": "Publisher terms as recorded per source in " + LEDGER_PATH,
        "capture_method": (
            "ArcGIS REST GET /query per layer: one where=1=1&returnCountOnly=true&f=json "
            "count, then one where=1=1&outFields=*&returnGeometry=true&f=json feature "
            "request with outSR omitted so the service answers in its own CRS"
        ),
        "files": {
            output.name: {
                "path": output.as_posix(),
                "bytes": output_bytes,
                "sha256": output_sha256,
                "tracked": False,
                "note": (
                    "data/physical-inventory/ is gitignored bulk output; "
                    "regenerate with the command in capture_method"
                ),
            }
        },
        "sources": [
            {
                "source_id": capture["source_id"],
                "layer_url": capture["layer_url"],
                "retrieved_at": capture["retrieved_at"],
                "declared_count": capture["declared_count"],
                "returned_features": capture["returned_features"],
                "features_reconciled_to_declared_count": (
                    capture["returned_features"] == capture["declared_count"]
                ),
                "native_crs": capture["native_crs"],
                "response_bytes": capture["response_bytes"],
                "content_sha256": capture["content_sha256"],
                "assets_created": capture["assets_created"],
            }
            for capture in captures
        ],
        "verification": {
            "artifact_content_sha256": artifact["content_sha256"],
            **verification,
            "observed_assets": len(artifact["assets"]),
            "terminals_created": len(artifact["terminals"]),
            "connectivity_edges_created": len(artifact["connectivity_edges"]),
            "coverage_rows": len(artifact["coverage"]),
            "unavailable_coverage_rows": sum(
                1 for row in artifact["coverage"] if row["status"] == "unavailable"
            ),
        },
        "coverage": artifact["coverage"],
        "uncertainty": (
            "Texas distribution geometry is owner-held and largely not public. Every "
            "distribution class here is unavailable with a null denominator, which is "
            "an unknown count and never zero. The retrieved service-area boundaries are "
            "owner footprints and were deliberately not converted into feeders, cables, "
            "devices, supports or service connections. Owner request routes are recorded "
            f"in {LEDGER_PATH}."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        help="Directory for the native-CRS source captures (gitignored bulk output).",
    )
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()

    sources: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []
    for layer in SERVICE_AREA_LAYERS:
        source, capture = fetch_service_area_layer(layer)
        sources.append(source)
        captures.append(capture)
        if args.raw_dir is not None:
            args.raw_dir.mkdir(parents=True, exist_ok=True)
            (args.raw_dir / f"{layer.source_id}.native.json").write_bytes(
                capture["raw"]
            )

    artifact, verification = build_artifact(
        sources, datetime.now(UTC).isoformat(timespec="seconds")
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(artifact, indent=2) + "\n"
    args.output.write_text(payload, encoding="utf-8", newline="\n")

    if args.receipt is not None:
        receipt = build_receipt(
            captures,
            artifact,
            args.output,
            len(payload.encode()),
            hashlib.sha256(payload.encode()).hexdigest(),
            verification,
        )
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

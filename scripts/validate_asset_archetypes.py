"""Validate the shared 3D asset archetype catalog against its contract.

The contract is only real if a machine can check it. This refuses a catalog that
would let the eighteen models import inconsistently: a drifting unit or axis, a
pivot that is not on the ground, an LOD chain that does not actually reduce, a
budget nobody can meet, a connector role the runtime does not know, or a status
material bound to a label no server asserts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data/3d/asset-archetypes-v1.json"

CONTRACT_ID = "flux:3d-asset-archetypes:v1"
EXPECTED_ARCHETYPES = 18
# Labels the server actually asserts. "illustrative" is deliberately absent: the
# narrative-IA contract removed it because nothing on master produces it.
ALLOWED_LABELS = {
    "source_supported",
    "source_screened",
    "hypothetical",
    "synthetic",
    "unavailable",
    "request_failed",
}
CONNECTOR_ROLES = {"HV_IN", "HV_OUT", "MV_FEED", "NONE"}
CATEGORIES = {"network", "generation", "storage", "load", "critical_load"}
ARCHETYPE_FIELDS = {
    "id",
    "semantic_name",
    "category",
    "texas_issue",
    "minnesota_issue",
    "footprint_m",
    "connectors",
    "lod_triangles",
    "limit",
}
LOD1_MAX_SHARE = 0.40
LOD2_MAX_SHARE = 0.12


def _issue_key(value: object) -> bool:
    return isinstance(value, str) and value.startswith("2WKG-") and value[5:].isdigit()


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    """Return every contract violation; an empty list means the catalog conforms."""
    errors: list[str] = []

    if catalog.get("schemaVersion") != 1 or catalog.get("contractId") != CONTRACT_ID:
        errors.append(f"catalog identity must be schemaVersion 1 and {CONTRACT_ID}")

    transform = catalog.get("transform", {})
    if transform.get("lengthUnit") != "meter" or transform.get("unitScale") != 1.0:
        errors.append("transform must declare metres at unit scale 1.0")
    if transform.get("upAxis") != "Y" or transform.get("forwardAxis") != "-Z":
        errors.append("transform must declare Y up and -Z forward")
    if transform.get("pivot") != "ground_center":
        errors.append("pivot must be ground_center so models sit on terrain")

    materials = catalog.get("statusMaterials", {})
    labels = set(materials.get("allowedLabels", []))
    if labels != ALLOWED_LABELS:
        errors.append(
            "status materials must bind exactly the server-asserted labels "
            f"{sorted(ALLOWED_LABELS)}"
        )
    if not materials.get("slotName"):
        errors.append("status materials must name the shared material slot")

    budgets = catalog.get("budgets", {})
    for key in (
        "perArchetypeTrianglesLod0",
        "perArchetypeFileBytes",
        "textureMaxPixels",
    ):
        if not isinstance(budgets.get(key), int) or budgets[key] <= 0:
            errors.append(f"budgets.{key} must be a positive integer")

    archetypes = catalog.get("archetypes")
    if not isinstance(archetypes, list) or len(archetypes) != EXPECTED_ARCHETYPES:
        errors.append(f"catalog must define exactly {EXPECTED_ARCHETYPES} archetypes")
        return errors

    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    seen_issues: set[str] = set()
    lod0_cap = budgets.get("perArchetypeTrianglesLod0", 0)

    for entry in archetypes:
        label = entry.get("id", "<missing id>")
        if set(entry) != ARCHETYPE_FIELDS:
            errors.append(f"{label}: fields must be exactly {sorted(ARCHETYPE_FIELDS)}")
            continue
        if entry["id"] in seen_ids:
            errors.append(f"{label}: duplicate archetype id")
        seen_ids.add(entry["id"])
        if entry["semantic_name"] in seen_names:
            errors.append(f"{label}: duplicate semantic name")
        seen_names.add(entry["semantic_name"])
        if entry["category"] not in CATEGORIES:
            errors.append(f"{label}: category must be one of {sorted(CATEGORIES)}")

        # Each archetype is claimed by exactly one Texas and one Minnesota work
        # item, and no work item may be claimed twice.
        for key in ("texas_issue", "minnesota_issue"):
            if not _issue_key(entry[key]):
                errors.append(f"{label}: {key} must be a 2WKG-NNN key")
            elif entry[key] in seen_issues:
                errors.append(f"{label}: {key} {entry[key]} is claimed twice")
            else:
                seen_issues.add(entry[key])

        footprint = entry["footprint_m"]
        if set(footprint) != {"length", "width"} or not all(
            isinstance(value, (int, float)) and value > 0
            for value in footprint.values()
        ):
            errors.append(f"{label}: footprint_m needs positive length and width")

        connectors = entry["connectors"]
        if not isinstance(connectors, list) or not connectors:
            errors.append(f"{label}: connectors must be a non-empty list")
        elif unknown := sorted(set(connectors) - CONNECTOR_ROLES):
            errors.append(f"{label}: unknown connector role(s) {unknown}")
        elif len(set(connectors)) != len(connectors):
            errors.append(f"{label}: duplicate connector role")
        elif "NONE" in connectors and len(connectors) > 1:
            errors.append(f"{label}: NONE cannot be combined with a real connector")

        lod = entry["lod_triangles"]
        if set(lod) != {"lod0", "lod1", "lod2"} or not all(
            isinstance(value, int) and value > 0 for value in lod.values()
        ):
            errors.append(f"{label}: lod_triangles needs positive lod0, lod1, lod2")
        else:
            if lod["lod0"] > lod0_cap:
                errors.append(f"{label}: lod0 {lod['lod0']} exceeds budget {lod0_cap}")
            if lod["lod1"] > lod["lod0"] * LOD1_MAX_SHARE:
                errors.append(f"{label}: lod1 must be <= {LOD1_MAX_SHARE:.0%} of lod0")
            if lod["lod2"] > lod["lod0"] * LOD2_MAX_SHARE:
                errors.append(f"{label}: lod2 must be <= {LOD2_MAX_SHARE:.0%} of lod0")

        if not entry["limit"].strip():
            errors.append(f"{label}: limit must state what the model does not assert")

    return errors


def build_report(catalog: dict[str, Any]) -> dict[str, Any]:
    errors = validate_catalog(catalog)
    archetypes = catalog.get("archetypes", [])
    categories: dict[str, int] = {}
    for entry in archetypes:
        if isinstance(entry, dict) and isinstance(entry.get("category"), str):
            categories[entry["category"]] = categories.get(entry["category"], 0) + 1
    return {
        "contractId": catalog.get("contractId"),
        "schemaVersion": catalog.get("schemaVersion"),
        "archetypeCount": len(archetypes),
        "categories": dict(sorted(categories.items())),
        "validation": {"passed": not errors, "errors": errors},
        "modelFilesPresent": False,
        "modelFilesNote": "This validates the contract and catalog only. No .glb is committed; the asset pipeline (2WKG-374 Minnesota, 2WKG-320 Texas) produces and checks the binaries.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    report = build_report(catalog)
    print(json.dumps(report, indent=2))
    return 0 if report["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

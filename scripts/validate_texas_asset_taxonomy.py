"""Validate the Texas placement-policy crosswalk without fetching source data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAXONOMY = ROOT / "data/sources/texas-asset-taxonomy-v1.json"
DEFAULT_CATALOG = ROOT / "data/3d/asset-archetypes-v1.json"
DEFAULT_INVENTORY = ROOT / "data/sources/texas-p0-inventory.json"
CANONICAL_LABELS = {
    "source_supported", "source_screened", "hypothetical", "synthetic", "unavailable", "request_failed"
}


def validate_taxonomy(taxonomy: dict[str, Any], catalog: dict[str, Any], inventory: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if taxonomy.get("schema_version") != 1 or taxonomy.get("taxonomy_id") != "texas-asset-taxonomy-v1":
        errors.append("taxonomy identity must be schema_version 1 and texas-asset-taxonomy-v1")
    if set(taxonomy.get("canonical_truth_labels", [])) != CANONICAL_LABELS:
        errors.append("canonical_truth_labels must match the shared 3D contract labels")
    policy = taxonomy.get("illustrative_wording_policy")
    if not isinstance(policy, str) or "not a truth label" not in policy:
        errors.append("illustrative_wording_policy must say illustrative is not a truth label")
    expected = {entry.get("id") for entry in catalog.get("archetypes", [])}
    source_ids = {record.get("id") for record in inventory.get("records", [])}
    entries = taxonomy.get("entries")
    if not isinstance(entries, list):
        return errors + ["entries must be a list"]
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        prefix = f"entries[{index}]"
        if not isinstance(entry, dict) or set(entry) != {"archetype_id", "source_record_ids", "truth_label_policy"}:
            errors.append(f"{prefix} must contain exactly archetype_id, source_record_ids, and truth_label_policy")
            continue
        archetype_id = entry["archetype_id"]
        if not isinstance(archetype_id, str) or archetype_id not in expected:
            errors.append(f"{prefix}.archetype_id is not in the shared catalog")
        elif archetype_id in seen:
            errors.append(f"duplicate archetype_id: {archetype_id}")
        else:
            seen.add(archetype_id)
        references = entry["source_record_ids"]
        if not isinstance(references, list) or not all(isinstance(item, str) and item in source_ids for item in references):
            errors.append(f"{prefix}.source_record_ids must only reference inventory records")
        text = entry["truth_label_policy"]
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{prefix}.truth_label_policy must be non-empty")
    if seen != expected:
        errors.append("entries must map every shared archetype exactly once")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    args = parser.parse_args()
    errors = validate_taxonomy(
        json.loads(args.taxonomy.read_text(encoding="utf-8")),
        json.loads(args.catalog.read_text(encoding="utf-8")),
        json.loads(args.inventory.read_text(encoding="utf-8")),
    )
    print(json.dumps({"passed": not errors, "errors": errors}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

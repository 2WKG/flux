"""Guard the checked-in Minnesota artifact inventory against misleading labels."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "data/sources/minnesota-accepted-artifact-inventory.json"
TRUTH_LABELS = {"source_backed", "synthetic", "illustrative", "unavailable"}


def _canonical_text_sha256(path: Path) -> str:
    """Hash the repository's LF form, independent of Windows checkout conversion."""
    payload = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


def _inventory() -> dict:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def test_accepted_artifacts_have_verified_local_identity_and_truth_policy():
    inventory = _inventory()
    assert set(inventory["truth_labels"]) == TRUTH_LABELS
    accepted = inventory["accepted_product_artifacts"]
    assert [item["artifact_id"] for item in accepted] == [
        "mn:aggregate:manifest:v1",
        "mn:facility_capacity:county:2024",
        "mn:facility_context:unassigned:2024",
        "mn:ba_context:miso:2024-h1",
    ]
    for artifact in accepted:
        assert artifact["truth_label_policy"]["default"] in TRUTH_LABELS
        assert artifact["license_or_terms"]["status"] in {
            "recorded",
            "partially_recorded",
            "unavailable",
        }
        expected = artifact["content_sha256"].removeprefix("sha256:")
        assert _canonical_text_sha256(ROOT / artifact["source_path"]) == expected


def test_inventory_rejects_misleading_minnesota_coverage_combinations():
    inventory = _inventory()
    excluded = {
        item["evidence_id"]: item
        for item in inventory["not_accepted_as_current_product_coverage"]
    }
    assert (
        excluded["synthetic_power_balance_preview"]["truth_label_policy"]["default"]
        == "synthetic"
    )
    assert (
        "not Minnesota"
        in excluded["synthetic_power_balance_preview"]["truth_label_policy"]["rule"]
    )
    assert (
        excluded["gridsfm_minnesota_feasibility"]["truth_label_policy"]["default"]
        == "unavailable"
    )
    assert (
        excluded["raw_minnesota_geometry"]["truth_label_policy"]["default"]
        == "unavailable"
    )

    taxonomy = {item["class"]: item for item in inventory["asset_taxonomy"]}
    assert taxonomy["topology_node"]["current_availability"] == "unavailable"
    assert taxonomy["topology_edge"]["current_availability"] == "unavailable"
    assert taxonomy["operating_overlay"]["current_availability"] == "unavailable"
    assert (
        taxonomy["regional_time_context"]["current_availability"]
        == "available_without_geometry"
    )
    assert (
        taxonomy["synthetic_preview_network"]["current_availability"]
        == "available_outside_minnesota_product_coverage"
    )
    for entry in taxonomy.values():
        assert entry["truth_label_policy"]

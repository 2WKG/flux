"""Guard the checked-in Minnesota artifact inventory against misleading labels."""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs/data/minnesota-accepted-artifact-inventory.md"
TRUTH_LABELS = {"source_backed", "synthetic", "illustrative", "unavailable"}


def _canonical_text_sha256(path: Path) -> str:
    """Hash the repository's LF form, independent of Windows checkout conversion."""
    payload = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


def _inventory() -> str:
    return INVENTORY.read_text(encoding="utf-8")


def test_accepted_artifacts_have_verified_local_identity_and_truth_policy():
    inventory = _inventory()
    assert all(f"`{label}`" in inventory for label in TRUTH_LABELS)
    expected = {
        "mn:aggregate:manifest:v1": (
            "pipelines/fixtures/inputs/minnesota_aggregate_manifest_v1.json",
            "f287a1dfbafddff8bd9f0ec989d488ad6743609280b19338eca048c3d5858e05",
        ),
        "mn:facility_capacity:county:2024": (
            "pipelines/fixtures/inputs/mn_county_plant_capacity_2024.csv",
            "7757c6ece5c36a0ae15573acfe4dd2e02cb42e13a0aa9f8ac142663977e7d573",
        ),
        "mn:facility_context:unassigned:2024": (
            "pipelines/fixtures/inputs/mn_unassigned_plant_capacity_2024.csv",
            "926f6fb65715df19af1eb833df1560c6e592827d7ea47ed54091cf3cf08a4ed6",
        ),
        "mn:ba_context:miso:2024-h1": (
            "pipelines/fixtures/inputs/miso_ba_context_2024_h1.csv",
            "395dad9aea19226744f8be5f91ca30c783ab776d1720e6486ff64880b8366e6f",
        ),
    }
    for artifact_id, (path, digest) in expected.items():
        assert artifact_id in inventory
        assert path in inventory
        assert digest in inventory
        assert _canonical_text_sha256(ROOT / path) == digest


def test_inventory_rejects_misleading_minnesota_coverage_combinations():
    inventory = _inventory()
    assert "`synthetic_power_balance_preview`" in inventory
    assert "not Minnesota, Texas, ERCOT, MISO, or an actual interconnection" in inventory
    assert "`gridsfm_minnesota_feasibility`" in inventory
    assert "`unavailable` for product coverage" in inventory
    assert "declared CRS without checked-in source/derived geometry" in inventory

    taxonomy = {
        "county_capacity_context",
        "facility_point",
        "service_area_surface",
        "topology_node",
        "topology_edge",
        "operating_overlay",
        "regional_time_context",
        "synthetic_preview_network",
    }
    for asset_class in taxonomy:
        assert f"`{asset_class}`" in inventory
    assert "Flows, loading, trips, and outages are `unavailable`" in inventory

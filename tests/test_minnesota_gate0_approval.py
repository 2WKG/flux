"""Enforce the Gate 0 boundary recorded in docs/design/minnesota-gate-0-approval.md.

A gate written only as prose widens silently. These checks fail when one of the
three Gate 0 inputs drifts away from what the gate froze: the label vocabularies,
the accepted-coverage list, or the standing of the five-bus preview.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPROVAL = ROOT / "docs/design/minnesota-gate-0-approval.md"
NARRATIVE_IA = ROOT / "docs/design/minnesota-demo-narrative-ia.md"
INVENTORY = ROOT / "data/sources/minnesota-accepted-artifact-inventory.json"
ASSET_CONTRACT = ROOT / "docs/design/3d-asset-contract.md"
ARCHETYPES = ROOT / "data/3d/asset-archetypes-v1.json"

# Frozen by Gate 0 section 3.
ARTIFACT_LABELS = {"source_backed", "synthetic", "unavailable"}
UI_STATUS_LABELS = {
    "source_supported",
    "source_screened",
    "hypothetical",
    "synthetic",
    "unavailable",
    "request_failed",
}
ACCEPTED_ARTIFACT_IDS = {
    "mn:aggregate:manifest:v1",
    "mn:facility_capacity:county:2024",
    "mn:facility_context:unassigned:2024",
    "mn:ba_context:miso:2024-h1",
}


def _inventory() -> dict:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def _assigned_labels(inventory: dict) -> set[str]:
    """Every truth label actually assigned to an entry, both accepted and not."""
    labels: set[str] = set()
    for key in (
        "accepted_product_artifacts",
        "not_accepted_as_current_product_coverage",
    ):
        for entry in inventory[key]:
            policy = entry.get("truth_label_policy")
            if isinstance(policy, dict) and isinstance(policy.get("default"), str):
                labels.add(policy["default"])
    return labels


def test_every_gate_input_exists():
    for path in (APPROVAL, NARRATIVE_IA, INVENTORY, ASSET_CONTRACT, ARCHETYPES):
        assert path.is_file(), f"Gate 0 input missing: {path.relative_to(ROOT)}"


def test_artifact_labels_stay_inside_the_frozen_set():
    assigned = _assigned_labels(_inventory())

    assert assigned == ARTIFACT_LABELS, (
        "an inventory entry assigns a truth label Gate 0 did not freeze; "
        "widening the vocabulary needs its own decision"
    )


def test_illustrative_is_never_assigned_to_an_artifact():
    inventory = _inventory()

    # It may remain in the declared vocabulary and inside prohibition prose, but
    # no entry may resolve to it: no server field asserts it.
    assert "illustrative" not in _assigned_labels(inventory)
    assert "illustrative" not in UI_STATUS_LABELS
    materials = json.loads(ARCHETYPES.read_text(encoding="utf-8"))["statusMaterials"]
    assert "illustrative" not in materials["allowedLabels"]


def test_status_materials_bind_exactly_the_ui_status_labels():
    materials = json.loads(ARCHETYPES.read_text(encoding="utf-8"))["statusMaterials"]

    assert set(materials["allowedLabels"]) == UI_STATUS_LABELS
    # Each frozen UI label is a real row in the narrative-IA status table.
    narrative = NARRATIVE_IA.read_text(encoding="utf-8")
    for label in UI_STATUS_LABELS - {"request_failed"}:
        assert label in narrative, f"{label} is bound but absent from the IA table"


def test_five_bus_preview_is_recorded_as_not_minnesota():
    inventory = _inventory()
    preview = next(
        entry
        for entry in inventory["not_accepted_as_current_product_coverage"]
        if entry["evidence_id"] == "synthetic_power_balance_preview"
    )

    assert preview["source_path"] == "data/demo/bundle.json"
    assert preview["truth_label_policy"]["default"] == "synthetic"
    assert "not Minnesota" in preview["truth_label_policy"]["rule"]
    accepted = {
        entry["artifact_id"] for entry in inventory["accepted_product_artifacts"]
    }
    assert "synthetic_power_balance_preview" not in accepted


def test_accepted_coverage_is_aggregate_only_and_grants_no_topology():
    inventory = _inventory()
    accepted = inventory["accepted_product_artifacts"]

    assert {entry["artifact_id"] for entry in accepted} == ACCEPTED_ARTIFACT_IDS
    # Gate 0's guarantee is not that the word "geometry" is absent — an allowed use
    # may legitimately name it in order to deny it ("after an accepted county
    # geometry exists"). It is that every accepted artifact explicitly refuses
    # topology-class inference.
    for entry in accepted:
        prohibited = " ".join(entry.get("prohibited_uses", [])).lower()
        assert prohibited, f"{entry['artifact_id']} declares no prohibited uses"
        assert "topology" in prohibited, (
            f"{entry['artifact_id']} no longer refuses topology inference; "
            "Gate 0 froze aggregate-mode coverage only"
        )
    # And the BA context must keep refusing allocation to Minnesota geography.
    miso = next(e for e in accepted if e["artifact_id"] == "mn:ba_context:miso:2024-h1")
    assert any("allocation" in use.lower() for use in miso["prohibited_uses"])


def test_the_approval_record_states_the_boundary_it_freezes():
    approval = APPROVAL.read_text(encoding="utf-8")

    for claim in (
        "not Minnesota",
        "illustrative` is not approved",
        "Topology scenes stay disabled",
        "never allocated",
    ):
        assert claim in approval, f"Gate 0 record no longer states: {claim}"

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.validate_asset_archetypes import (
    ALLOWED_LABELS,
    DEFAULT_CATALOG,
    EXPECTED_ARCHETYPES,
    build_report,
    validate_catalog,
)


def _catalog() -> dict:
    return json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))


def test_committed_catalog_conforms_and_covers_every_asset_work_item():
    catalog = _catalog()

    report = build_report(catalog)

    assert report["validation"] == {"passed": True, "errors": []}
    assert report["archetypeCount"] == EXPECTED_ARCHETYPES
    # One Texas and one Minnesota work item per archetype, none claimed twice.
    texas = [entry["texas_issue"] for entry in catalog["archetypes"]]
    minnesota = [entry["minnesota_issue"] for entry in catalog["archetypes"]]
    assert len(set(texas)) == len(set(minnesota)) == EXPECTED_ARCHETYPES
    assert set(texas).isdisjoint(minnesota)
    # No binary is committed; the contract governs shape, not hosting.
    assert report["modelFilesPresent"] is False
    assert not list(Path(DEFAULT_CATALOG).parent.glob("*.glb"))


def test_import_invariants_are_pinned_not_merely_described():
    catalog = _catalog()
    transform = catalog["transform"]

    assert transform["lengthUnit"] == "meter" and transform["unitScale"] == 1.0
    assert transform["upAxis"] == "Y" and transform["forwardAxis"] == "-Z"
    assert transform["pivot"] == "ground_center"
    for field, value in (
        ("lengthUnit", "centimeter"),
        ("upAxis", "Z"),
        ("pivot", "bounding_box_center"),
    ):
        drifted = copy.deepcopy(catalog)
        drifted["transform"][field] = value
        assert validate_catalog(drifted), f"{field}={value} must be rejected"


def test_status_materials_bind_only_labels_the_server_asserts():
    catalog = _catalog()

    assert set(catalog["statusMaterials"]["allowedLabels"]) == ALLOWED_LABELS
    # "illustrative" was deliberately removed from the narrative-IA contract: no
    # server field asserts it, so a model may not carry it either.
    invented = copy.deepcopy(catalog)
    invented["statusMaterials"]["allowedLabels"].append("illustrative")

    assert any("server-asserted" in error for error in validate_catalog(invented))


def test_lod_chain_must_actually_reduce_and_respect_the_budget():
    catalog = _catalog()

    flat = copy.deepcopy(catalog)
    flat["archetypes"][0]["lod_triangles"]["lod1"] = flat["archetypes"][0][
        "lod_triangles"
    ]["lod0"]
    assert any("lod1" in error for error in validate_catalog(flat))

    over = copy.deepcopy(catalog)
    over["archetypes"][0]["lod_triangles"]["lod0"] = (
        catalog["budgets"]["perArchetypeTrianglesLod0"] + 1
    )
    assert any("exceeds budget" in error for error in validate_catalog(over))


def test_connector_roles_and_limits_are_constrained():
    catalog = _catalog()

    unknown = copy.deepcopy(catalog)
    unknown["archetypes"][0]["connectors"] = ["HV_MAGIC"]
    assert any("unknown connector" in error for error in validate_catalog(unknown))

    mixed = copy.deepcopy(catalog)
    mixed["archetypes"][0]["connectors"] = ["NONE", "HV_IN"]
    assert any("NONE cannot be combined" in error for error in validate_catalog(mixed))

    # Every archetype must say what it does not assert.
    assert all(entry["limit"].strip() for entry in catalog["archetypes"])
    silent = copy.deepcopy(catalog)
    silent["archetypes"][0]["limit"] = "   "
    assert any("limit must state" in error for error in validate_catalog(silent))


def test_duplicate_identity_is_rejected():
    catalog = _catalog()
    duplicated = copy.deepcopy(catalog)
    duplicated["archetypes"][1]["id"] = duplicated["archetypes"][0]["id"]
    duplicated["archetypes"][1]["texas_issue"] = duplicated["archetypes"][0][
        "texas_issue"
    ]

    errors = validate_catalog(duplicated)

    assert any("duplicate archetype id" in error for error in errors)
    assert any("claimed twice" in error for error in errors)


@pytest.mark.parametrize("count", [EXPECTED_ARCHETYPES - 1, EXPECTED_ARCHETYPES + 1])
def test_catalog_must_hold_exactly_the_eighteen_assets(count: int):
    catalog = _catalog()
    resized = copy.deepcopy(catalog)
    entries = resized["archetypes"]
    resized["archetypes"] = (
        entries[:count] if count < len(entries) else entries + [entries[0]]
    )

    assert any("exactly 18 archetypes" in error for error in validate_catalog(resized))

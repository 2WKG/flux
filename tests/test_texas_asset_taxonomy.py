from __future__ import annotations

import copy
import json
import sys

from scripts.validate_texas_asset_taxonomy import (
    DEFAULT_CATALOG,
    DEFAULT_INVENTORY,
    DEFAULT_TAXONOMY,
    main,
    validate_taxonomy,
)


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_committed_taxonomy_maps_every_shared_archetype_with_a_policy():
    taxonomy = _json(DEFAULT_TAXONOMY)
    catalog = _json(DEFAULT_CATALOG)
    inventory = _json(DEFAULT_INVENTORY)

    assert validate_taxonomy(taxonomy, catalog, inventory) == []
    assert len(taxonomy["entries"]) == len(catalog["archetypes"]) == 18
    assert "not a truth label" in taxonomy["illustrative_wording_policy"]


def test_taxonomy_rejects_an_unknown_source_or_missing_policy():
    taxonomy = _json(DEFAULT_TAXONOMY)
    catalog = _json(DEFAULT_CATALOG)
    inventory = _json(DEFAULT_INVENTORY)

    unknown = copy.deepcopy(taxonomy)
    unknown["entries"][0]["source_record_ids"] = ["not-a-source"]
    assert any(
        "only reference inventory" in error
        for error in validate_taxonomy(unknown, catalog, inventory)
    )

    silent = copy.deepcopy(taxonomy)
    silent["entries"][0]["truth_label_policy"] = ""
    assert any(
        "must be non-empty" in error
        for error in validate_taxonomy(silent, catalog, inventory)
    )


def test_taxonomy_rejects_a_catalog_gap_and_illustrative_label_drift():
    taxonomy = _json(DEFAULT_TAXONOMY)
    catalog = _json(DEFAULT_CATALOG)
    inventory = _json(DEFAULT_INVENTORY)

    gap = copy.deepcopy(taxonomy)
    gap["entries"].pop()
    assert any(
        "every shared archetype" in error
        for error in validate_taxonomy(gap, catalog, inventory)
    )

    drifted = copy.deepcopy(taxonomy)
    drifted["canonical_truth_labels"].append("illustrative")
    assert any(
        "must match" in error
        for error in validate_taxonomy(drifted, catalog, inventory)
    )


def test_taxonomy_rejects_identity_drift():
    taxonomy = _json(DEFAULT_TAXONOMY)
    catalog = _json(DEFAULT_CATALOG)
    inventory = _json(DEFAULT_INVENTORY)

    bumped = copy.deepcopy(taxonomy)
    bumped["schema_version"] = 2
    assert any(
        "taxonomy identity" in error
        for error in validate_taxonomy(bumped, catalog, inventory)
    )

    renamed = copy.deepcopy(taxonomy)
    renamed["taxonomy_id"] = "texas-asset-taxonomy-v2"
    assert any(
        "taxonomy identity" in error
        for error in validate_taxonomy(renamed, catalog, inventory)
    )


def test_taxonomy_rejects_an_illustrative_wording_policy_that_is_not_a_refusal():
    taxonomy = _json(DEFAULT_TAXONOMY)
    catalog = _json(DEFAULT_CATALOG)
    inventory = _json(DEFAULT_INVENTORY)

    softened = copy.deepcopy(taxonomy)
    softened["illustrative_wording_policy"] = (
        "illustrative means whatever the demo needs"
    )
    assert any(
        "not a truth label" in error
        for error in validate_taxonomy(softened, catalog, inventory)
    )

    missing = copy.deepcopy(taxonomy)
    del missing["illustrative_wording_policy"]
    assert any(
        "not a truth label" in error
        for error in validate_taxonomy(missing, catalog, inventory)
    )


def test_a_malformed_entry_becomes_a_validation_error_not_a_crash():
    taxonomy = _json(DEFAULT_TAXONOMY)
    catalog = _json(DEFAULT_CATALOG)
    inventory = _json(DEFAULT_INVENTORY)

    truncated = copy.deepcopy(taxonomy)
    del truncated["entries"][0]["archetype_id"]
    errors = validate_taxonomy(truncated, catalog, inventory)
    assert any("must contain exactly" in error for error in errors)

    extra = copy.deepcopy(taxonomy)
    extra["entries"][0]["vibe"] = "cinematic"
    assert any(
        "must contain exactly" in error
        for error in validate_taxonomy(extra, catalog, inventory)
    )


def test_taxonomy_binds_topology_source_to_the_activsg2000_reference():
    taxonomy = _json(DEFAULT_TAXONOMY)
    catalog = _json(DEFAULT_CATALOG)
    inventory = _json(DEFAULT_INVENTORY)

    activsg2000_entries = [
        entry
        for entry in taxonomy["entries"]
        if "activsg2000-current" in entry["source_record_ids"]
    ]
    assert activsg2000_entries
    assert all(
        entry["topology_source"] == "synthetic (ACTIVSg2000)"
        for entry in activsg2000_entries
    )
    assert all(
        entry["topology_source"] == "none"
        for entry in taxonomy["entries"]
        if "activsg2000-current" not in entry["source_record_ids"]
    )

    laundered = copy.deepcopy(taxonomy)
    laundered["entries"][0]["topology_source"] = "none"
    assert any(
        "must be 'synthetic (ACTIVSg2000)'" in error
        for error in validate_taxonomy(laundered, catalog, inventory)
    )

    borrowed = copy.deepcopy(taxonomy)
    borrowed["entries"][3]["topology_source"] = "synthetic (ACTIVSg2000)"
    assert any(
        "must be 'none'" in error
        for error in validate_taxonomy(borrowed, catalog, inventory)
    )

    invented = copy.deepcopy(taxonomy)
    invented["entries"][3]["topology_source"] = "minnesota five-bus fixture"
    assert any(
        "topology_source must be one of" in error
        for error in validate_taxonomy(invented, catalog, inventory)
    )


def test_taxonomy_requires_the_five_bus_fixture_disclaimer():
    taxonomy = _json(DEFAULT_TAXONOMY)
    catalog = _json(DEFAULT_CATALOG)
    inventory = _json(DEFAULT_INVENTORY)

    assert "five-bus" in taxonomy["five_bus_fixture_policy"]

    dropped = copy.deepcopy(taxonomy)
    del dropped["five_bus_fixture_policy"]
    assert any(
        "five_bus_fixture_policy" in error
        for error in validate_taxonomy(dropped, catalog, inventory)
    )


def test_canonical_labels_are_read_from_the_shared_catalog_not_a_local_copy():
    taxonomy = _json(DEFAULT_TAXONOMY)
    catalog = _json(DEFAULT_CATALOG)
    inventory = _json(DEFAULT_INVENTORY)

    drifted_catalog = copy.deepcopy(catalog)
    drifted_catalog["statusMaterials"]["allowedLabels"] = [
        "source_supported",
        "vibes_based",
    ]
    assert any(
        "must match the shared 3D contract labels" in error
        for error in validate_taxonomy(taxonomy, drifted_catalog, inventory)
    )

    silent_catalog = copy.deepcopy(catalog)
    silent_catalog["statusMaterials"]["allowedLabels"] = []
    assert any(
        "declares no statusMaterials.allowedLabels" in error
        for error in validate_taxonomy(taxonomy, silent_catalog, inventory)
    )


def _run_main(monkeypatch, capsys, **overrides):
    argv = ["validate_texas_asset_taxonomy.py"]
    for flag, default in (
        ("--taxonomy", DEFAULT_TAXONOMY),
        ("--catalog", DEFAULT_CATALOG),
        ("--inventory", DEFAULT_INVENTORY),
    ):
        argv += [flag, str(overrides.get(flag.lstrip("-"), default))]
    monkeypatch.setattr(sys, "argv", argv)
    code = main()
    return code, json.loads(capsys.readouterr().out)


def test_main_exits_zero_on_the_committed_files(monkeypatch, capsys):
    code, report = _run_main(monkeypatch, capsys)
    assert code == 0
    assert report == {"passed": True, "errors": []}


def test_main_exits_one_on_a_violating_taxonomy(monkeypatch, capsys, tmp_path):
    taxonomy = _json(DEFAULT_TAXONOMY)
    taxonomy["entries"][0]["source_record_ids"] = ["ghost-source"]
    broken = tmp_path / "texas-asset-taxonomy-v1.json"
    broken.write_text(json.dumps(taxonomy), encoding="utf-8")

    code, report = _run_main(monkeypatch, capsys, taxonomy=broken)
    assert code == 1
    assert report["passed"] is False
    assert any("only reference inventory" in error for error in report["errors"])


def test_main_exits_one_when_the_shared_catalog_labels_drift(
    monkeypatch, capsys, tmp_path
):
    catalog = _json(DEFAULT_CATALOG)
    catalog["statusMaterials"]["allowedLabels"] = ["source_supported", "vibes_based"]
    drifted = tmp_path / "asset-archetypes-v1.json"
    drifted.write_text(json.dumps(catalog), encoding="utf-8")

    code, report = _run_main(monkeypatch, capsys, catalog=drifted)
    assert code == 1
    assert report["passed"] is False
    assert any(
        "must match the shared 3D contract labels" in error
        for error in report["errors"]
    )

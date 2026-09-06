from __future__ import annotations

import copy
import json

from scripts.validate_texas_asset_taxonomy import (
    DEFAULT_CATALOG,
    DEFAULT_INVENTORY,
    DEFAULT_TAXONOMY,
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
    assert any("only reference inventory" in error for error in validate_taxonomy(unknown, catalog, inventory))

    silent = copy.deepcopy(taxonomy)
    silent["entries"][0]["truth_label_policy"] = ""
    assert any("must be non-empty" in error for error in validate_taxonomy(silent, catalog, inventory))


def test_taxonomy_rejects_a_catalog_gap_and_illustrative_label_drift():
    taxonomy = _json(DEFAULT_TAXONOMY)
    catalog = _json(DEFAULT_CATALOG)
    inventory = _json(DEFAULT_INVENTORY)

    gap = copy.deepcopy(taxonomy)
    gap["entries"].pop()
    assert any("every shared archetype" in error for error in validate_taxonomy(gap, catalog, inventory))

    drifted = copy.deepcopy(taxonomy)
    drifted["canonical_truth_labels"].append("illustrative")
    assert any("must match" in error for error in validate_taxonomy(drifted, catalog, inventory))

"""Keep Minnesota physical-source availability claims mechanically honest."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "data/sources/minnesota-source-authority-ledger-v1.json"


def test_ledger_has_explicit_scope_and_known_source_statuses():
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    assert ledger["state"] == "MN"
    assert "not statewide completeness" in ledger["purpose"]
    statuses = set(ledger["source_status_values"])
    assert statuses == {"accepted_limited", "candidate", "restricted", "unavailable"}
    for source in ledger["sources"]:
        assert source["status"] in statuses
        assert source["url"].startswith("https://")
        assert source["spatial_extent"]
        assert source["geometry_accuracy_basis"]


def test_ledger_does_not_promote_limited_geometry_to_statewide_or_connectivity_coverage():
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    coverage = {row["class_id"]: row for row in ledger["physical_class_coverage"]}
    assert coverage["retail_service_area"]["coverage_denominator"] == 192
    assert coverage["transmission_line"]["coverage_denominator"] is None
    assert coverage["substation"]["coverage_denominator"] is None
    assert coverage["distribution_line_and_device"]["status"] == "unavailable"
    assert coverage["real_electrical_connectivity"]["status"] == "unavailable"
    assert coverage["cross_border_interface"]["status"] == "restricted"
    mille_lacs = next(
        source
        for source in ledger["sources"]
        if source["source_id"] == "mille_lacs_county_utilities_mapserver_2026"
    )
    assert [layer["returned_feature_count"] for layer in mille_lacs["verified_layers"]] == [11, 31]
    assert "statewide denominator" in mille_lacs["verified_layers"][1]["denominator_scope"]

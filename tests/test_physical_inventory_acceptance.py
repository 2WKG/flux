from __future__ import annotations

from copy import deepcopy

import pytest

from pipelines.physical_inventory import CONTRACT_VERSION, artifact_sha256
from scripts.verify_physical_inventory import AcceptanceError, build_receipt


def _artifact() -> dict:
    artifact = {
        "artifact_id": "tx:physical-inventory:1.0.0",
        "contract_version": CONTRACT_VERSION,
        "geography_id": "tx",
        "artifact_version": "1.0.0",
        "inventory_mode": "physical_observed",
        "electrical_model_mode": "none",
        "created_at": "2026-09-06T12:00:00+00:00",
        "content_sha256": "0" * 64,
        "sources": [
            {
                "source_id": "eia2025er",
                "authority": "EIA",
                "source_ref": "https://www.eia.gov/electricity/data/eia860/",
                "source_version": "2025ER",
                "retrieved_at": "2026-09-06T12:00:00+00:00",
                "license_or_terms": "public data",
                "content_sha256": "a" * 64,
            }
        ],
        "assets": [
            {
                "asset_id": "eia:plant:1",
                "asset_class": "generation",
                "asset_kind": "plant",
                "source_id": "eia2025er",
                "source_record_id": "1",
                "geometry": {"type": "Point", "coordinates": [-97.0, 32.0]},
                "geometry_crs": "EPSG:4326",
                "geometry_precision_m": 10.0,
                "geometry_accuracy_basis": "EIA-reported latitude/longitude",
                "geometry_derivation_method": None,
                "geometry_status": "source",
            },
            {
                "asset_id": "eia:plant:2",
                "asset_class": "generation",
                "asset_kind": "plant",
                "source_id": "eia2025er",
                "source_record_id": "2",
                "geometry": {"type": "Point", "coordinates": [-98.0, 31.0]},
                "geometry_crs": "EPSG:4326",
                "geometry_precision_m": 10.0,
                "geometry_accuracy_basis": "EIA-reported latitude/longitude",
                "geometry_derivation_method": None,
                "geometry_status": "source",
            },
        ],
        "terminals": [],
        "connectivity_edges": [],
        "coverage": [
            {
                "asset_class": "generation",
                "scope_id": "tx",
                "status": "partial",
                "observed_count": 2,
                "denominator_count": None,
                "unknown_count": None,
                "unavailable_count": None,
                "denominator_basis": "source_returned_count:EIA2025ER",
                "source_scope": "EIA2025ER:Texas-reported-plants",
                "reason": "Source-returned plants are not an owner-level class denominator.",
            }
        ],
    }
    artifact["content_sha256"] = artifact_sha256(artifact)
    return artifact


def test_offline_receipt_keeps_api_and_browser_unverified() -> None:
    receipt = build_receipt(_artifact(), state="tx", expected_version="1.0.0")
    assert receipt["offline_result"] == "VERIFIED"
    assert receipt["coverage"][0]["source_returned_count"] == 2
    assert receipt["coverage"][0]["authoritative_state_class_denominator"] is None
    assert receipt["stages"]["spatial_api_transport"] == "NOT VERIFIED"
    assert receipt["end_to_end_result"] == "NOT VERIFIED"


def test_state_receipt_accepts_a_scoped_state_geography_without_promoting_coverage() -> (
    None
):
    artifact = _artifact()
    artifact["geography_id"] = "mn:mille-lacs-county"
    artifact["artifact_id"] = "mn:mille-lacs-county:physical-inventory:1.0.0"
    artifact["coverage"][0]["scope_id"] = "mn:mille-lacs-county:source-layer"
    artifact["content_sha256"] = artifact_sha256(artifact)
    receipt = build_receipt(artifact, state="mn")
    assert receipt["state"] == "mn"
    assert receipt["coverage"][0]["denominator_evidence"] == "source_local_or_unknown"


def test_state_receipt_accepts_the_canonical_us_prefixed_state_geography() -> None:
    artifact = _artifact()
    artifact["geography_id"] = "us-tx"
    artifact["artifact_id"] = "us-tx:physical-inventory:1.0.0"
    artifact["coverage"][0]["scope_id"] = "us-tx"
    artifact["content_sha256"] = artifact_sha256(artifact)
    assert build_receipt(artifact, state="tx")["offline_result"] == "VERIFIED"


def test_rejects_dropped_normalized_asset() -> None:
    artifact = _artifact()
    artifact["assets"].pop()
    artifact["content_sha256"] = artifact_sha256(artifact)
    receipt = build_receipt(artifact, state="tx")
    assert receipt["offline_result"] == "REJECTED"
    assert "coverage observed_count=2 but normalized assets=1" in receipt["errors"][0]


def test_rejects_source_returned_count_as_a_statewide_complete_claim() -> None:
    artifact = _artifact()
    row = artifact["coverage"][0]
    row.update(
        status="complete", denominator_count=2, unknown_count=0, unavailable_count=0
    )
    artifact["content_sha256"] = artifact_sha256(artifact)
    receipt = build_receipt(artifact, state="tx")
    assert receipt["offline_result"] == "REJECTED"
    assert "authoritative_state_class:tx" in receipt["errors"][0]


def test_rejects_version_mismatch_and_preserves_contract_hash_checks() -> None:
    with pytest.raises(AcceptanceError, match="does not match expected"):
        build_receipt(_artifact(), state="tx", expected_version="2.0.0")
    artifact = deepcopy(_artifact())
    artifact["sources"][0]["source_version"] = "other"
    with pytest.raises(AcceptanceError, match="content_sha256"):
        build_receipt(artifact, state="tx")


def test_rejects_complete_class_when_one_coordinate_is_unavailable() -> None:
    artifact = _artifact()
    artifact["assets"][1].update(
        geometry=None,
        geometry_crs=None,
        geometry_precision_m=None,
        geometry_accuracy_basis=None,
        geometry_derivation_method=None,
        geometry_status="unavailable",
    )
    row = artifact["coverage"][0]
    row.update(
        status="complete",
        denominator_count=2,
        unknown_count=0,
        unavailable_count=0,
        denominator_basis="authoritative_state_class:tx",
        source_scope="statewide:tx",
    )
    artifact["content_sha256"] = artifact_sha256(artifact)
    receipt = build_receipt(artifact, state="tx")
    assert receipt["offline_result"] == "REJECTED"
    assert any("source geometry" in error for error in receipt["errors"])


def test_rejects_overcounted_denominator_and_fabricated_unavailable_metadata() -> None:
    artifact = _artifact()
    row = artifact["coverage"][0]
    row.update(
        status="partial",
        denominator_count=1,
        unavailable_count=0,
        denominator_basis="authoritative_state_class:tx",
        source_scope="statewide:tx",
    )
    artifact["content_sha256"] = artifact_sha256(artifact)
    receipt = build_receipt(artifact, state="tx")
    assert receipt["offline_result"] == "REJECTED"
    assert any("exactly equal" in error for error in receipt["errors"])

    artifact = _artifact()
    asset = artifact["assets"][0]
    asset.update(geometry=None, geometry_status="unavailable")
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(AcceptanceError, match="unavailable geometry"):
        build_receipt(artifact, state="tx")


def test_rejects_a_claimed_epsg_code_that_is_not_a_real_coordinate_reference() -> None:
    artifact = _artifact()
    artifact["assets"][0]["geometry_crs"] = "EPSG:103705"
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(AcceptanceError, match="not a registered CRS"):
        build_receipt(artifact, state="tx")

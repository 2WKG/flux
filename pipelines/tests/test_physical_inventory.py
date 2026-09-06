from __future__ import annotations

from copy import deepcopy

import duckdb
import pytest

from pipelines.physical_inventory import (
    CONTRACT_VERSION,
    PhysicalInventoryError,
    artifact_sha256,
    validate_artifact,
    write_artifact,
)


def _artifact() -> dict:
    artifact = {
        "artifact_id": "tx:physical-inventory:1.0.0",
        "contract_version": CONTRACT_VERSION,
        "geography_id": "tx",
        "artifact_version": "1.0.0",
        "inventory_mode": "physical_observed",
        "electrical_model_mode": "none",
        "created_at": "2026-09-06T12:00:00Z",
        "content_sha256": "0" * 64,
        "sources": [
            {
                "source_id": "eia860",
                "authority": "EIA",
                "source_ref": "https://example.test/eia860",
                "source_version": "2025",
                "retrieved_at": "2026-09-06T12:00:00Z",
                "license_or_terms": "public data",
                "content_sha256": "a" * 64,
            }
        ],
        "assets": [
            {
                "asset_id": "eia860:plant:1",
                "asset_class": "generation",
                "asset_kind": "plant",
                "source_id": "eia860",
                "source_record_id": "1",
                "geometry": {"type": "Point", "coordinates": [-97.0, 32.0]},
                "geometry_crs": "EPSG:4326",
                "geometry_precision_m": 10.0,
                "geometry_accuracy_basis": "source-reported plant coordinate",
                "geometry_derivation_method": None,
                "geometry_status": "source",
            }
        ],
        "terminals": [],
        "connectivity_edges": [],
        "coverage": [
            {
                "asset_class": "generation",
                "scope_id": "tx",
                "status": "partial",
                "observed_count": 1,
                "denominator_count": None,
                "unknown_count": None,
                "unavailable_count": None,
                "denominator_basis": "unknown",
                "source_scope": "EIA-860 reported Texas plants",
                "reason": "The source reports observed plants but no statewide completeness denominator.",
            },
            {
                "asset_class": "line",
                "scope_id": "tx",
                "status": "unavailable",
                "observed_count": 0,
                "denominator_count": None,
                "unknown_count": None,
                "unavailable_count": None,
                "denominator_basis": "unknown",
                "source_scope": "Texas statewide",
                "reason": "No source artifact was acquired for this release.",
            },
        ],
    }
    artifact["content_sha256"] = artifact_sha256(artifact)
    return artifact


def test_persists_reproducible_observed_inventory_and_unknown_coverage() -> None:
    artifact = _artifact()
    con = duckdb.connect(":memory:")
    assert write_artifact(con, artifact) == artifact["artifact_id"]
    assert write_artifact(con, deepcopy(artifact)) == artifact["artifact_id"]
    assert con.execute(
        "SELECT inventory_mode, electrical_model_mode FROM physical_inventory_manifests"
    ).fetchone() == ("physical_observed", "none")
    assert con.execute(
        "SELECT geometry_crs, geometry_precision_m, geometry_accuracy_basis FROM physical_assets"
    ).fetchone() == ("EPSG:4326", 10.0, "source-reported plant coordinate")
    assert con.execute(
        "SELECT denominator_count, status FROM physical_coverage WHERE asset_class='generation'"
    ).fetchone() == (None, "partial")


def test_rejects_complete_claim_without_a_coverage_denominator() -> None:
    artifact = _artifact()
    artifact["coverage"][0]["status"] = "complete"
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(PhysicalInventoryError, match="cannot claim complete"):
        validate_artifact(artifact)


def test_rejects_unsourced_connectivity_and_invalid_geometry() -> None:
    artifact = _artifact()
    artifact["connectivity_edges"] = [
        {
            "edge_id": "made-up",
            "from_terminal_id": "a",
            "to_terminal_id": "b",
            "source_id": "eia860",
            "source_record_id": "none",
        }
    ]
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(PhysicalInventoryError, match="sourced distinct terminals"):
        validate_artifact(artifact)
    artifact = _artifact()
    artifact["assets"][0]["geometry"]["coordinates"] = [-197.0, 32.0]
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(PhysicalInventoryError, match="invalid EPSG:4326"):
        validate_artifact(artifact)


def test_rejects_coverage_omissions_and_unavailable_geometry_metadata() -> None:
    artifact = _artifact()
    artifact["coverage"] = []
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(PhysicalInventoryError, match="coverage must declare"):
        validate_artifact(artifact)
    artifact = _artifact()
    asset = artifact["assets"][0]
    asset.update(
        {
            "geometry": None,
            "geometry_crs": "EPSG:4326",
            "geometry_precision_m": 0.01,
            "geometry_accuracy_basis": "invented",
            "geometry_status": "unavailable",
        }
    )
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(PhysicalInventoryError, match="unavailable geometry"):
        validate_artifact(artifact)


def test_rejects_missing_asset_coverage_overcount_and_unproven_derived_geometry() -> (
    None
):
    artifact = _artifact()
    artifact["coverage"] = [artifact["coverage"][1]]
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(
        PhysicalInventoryError, match="required for observed asset classes"
    ):
        validate_artifact(artifact)
    artifact = _artifact()
    row = artifact["coverage"][0]
    row.update(
        {
            "status": "complete",
            "denominator_count": 1,
            "unknown_count": 0,
            "unavailable_count": 0,
            "observed_count": 2,
        }
    )
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(PhysicalInventoryError, match="exact reconciled"):
        validate_artifact(artifact)
    artifact = _artifact()
    asset = artifact["assets"][0]
    asset.update({"geometry_status": "derived", "geometry_derivation_method": None})
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(PhysicalInventoryError, match="derivation method"):
        validate_artifact(artifact)


def test_accepts_registered_esri_source_crs_and_rejects_unknown_authority_code() -> (
    None
):
    artifact = _artifact()
    artifact["assets"][0]["geometry_crs"] = "ESRI:103705"
    artifact["content_sha256"] = artifact_sha256(artifact)
    assert validate_artifact(artifact) is artifact
    artifact["assets"][0]["geometry_crs"] = "ESRI:999999999"
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(PhysicalInventoryError, match="not a registered CRS"):
        validate_artifact(artifact)

from __future__ import annotations

from copy import deepcopy

import duckdb
import pytest

from pipelines.physical_inventory import (
    CONTRACT_VERSION,
    PhysicalInventoryError,
    artifact_sha256,
    ensure_physical_inventory_schema,
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


def test_rejects_an_artifact_whose_digest_does_not_cover_its_own_content() -> None:
    artifact = _artifact()
    artifact["assets"][0]["source_record_id"] = "tampered-after-digest"
    with pytest.raises(PhysicalInventoryError, match="content_sha256 does not match"):
        validate_artifact(artifact)


def test_refuses_a_second_write_of_the_same_artifact_id_with_different_content() -> (
    None
):
    con = duckdb.connect(":memory:")
    first = _artifact()
    write_artifact(con, first)
    conflicting = _artifact()
    conflicting["assets"][0]["source_record_id"] = "2"
    conflicting["content_sha256"] = artifact_sha256(conflicting)
    assert conflicting["artifact_id"] == first["artifact_id"]
    assert conflicting["content_sha256"] != first["content_sha256"]
    with pytest.raises(
        PhysicalInventoryError, match="conflicts with persisted content"
    ):
        write_artifact(con, conflicting)
    assert con.execute(
        "SELECT content_sha256 FROM physical_inventory_manifests"
    ).fetchall() == [(first["content_sha256"],)]
    assert (
        con.execute(
            "SELECT count(*) FROM physical_assets WHERE source_record_id='2'"
        ).fetchone()[0]
        == 0
    )


def test_rejects_a_crs_code_that_resolves_to_a_different_authority() -> None:
    # ESRI:102124 is registered, but resolves to EPSG:26701; EPSG:102100 resolves
    # to ESRI:102100.  Accepting either would silently relabel the declared CRS.
    for mislabelled in ("ESRI:102124", "EPSG:102100"):
        artifact = _artifact()
        artifact["assets"][0]["geometry_crs"] = mislabelled
        artifact["content_sha256"] = artifact_sha256(artifact)
        with pytest.raises(
            PhysicalInventoryError, match="retain its declared authority"
        ):
            validate_artifact(artifact)


def test_refuses_to_write_into_a_schema_recorded_at_another_contract_version() -> None:
    con = duckdb.connect(":memory:")
    write_artifact(con, _artifact())
    con.execute(
        "UPDATE physical_inventory_schema_meta SET value='0.9.0' WHERE key='contract_version'"
    )
    with pytest.raises(RuntimeError, match="requires an explicit migration"):
        ensure_physical_inventory_schema(con)
    con.execute("DELETE FROM physical_inventory_schema_meta")
    with pytest.raises(RuntimeError, match="requires an explicit migration"):
        ensure_physical_inventory_schema(con)


def test_refuses_a_pre_existing_physical_schema_without_recorded_metadata() -> None:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE physical_assets (asset_id TEXT)")
    with pytest.raises(RuntimeError, match="migrate explicitly"):
        ensure_physical_inventory_schema(con)


class _FailingOn:
    """Delegate to a real connection but fail one statement, to drive rollback."""

    def __init__(self, con: duckdb.DuckDBPyConnection, fragment: str) -> None:
        self._con = con
        self._fragment = fragment

    def execute(self, statement: str, *args: object) -> object:
        if self._fragment in statement:
            raise duckdb.Error(f"injected failure on {self._fragment!r}")
        return self._con.execute(statement, *args)


def test_rolls_back_a_partially_written_artifact() -> None:
    con = duckdb.connect(":memory:")
    with pytest.raises(duckdb.Error, match="injected failure"):
        write_artifact(_FailingOn(con, "INSERT INTO physical_coverage"), _artifact())
    assert (
        con.execute("SELECT count(*) FROM physical_inventory_manifests").fetchone()[0]
        == 0
    )
    assert con.execute("SELECT count(*) FROM physical_assets").fetchone()[0] == 0
    assert (
        con.execute("SELECT count(*) FROM physical_inventory_sources").fetchone()[0]
        == 0
    )


def test_rejects_source_geometry_that_claims_a_derivation_method() -> None:
    """`source` status means the source supplied the geometry, not a transform."""
    artifact = _artifact()
    artifact["assets"][0]["geometry_status"] = "source"
    artifact["assets"][0]["geometry_derivation_method"] = "snapped to a county centroid"
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(
        PhysicalInventoryError, match="must not claim a derivation method"
    ):
        validate_artifact(artifact)

from __future__ import annotations

import gzip
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from pipelines.assemble_physical_inventory import assemble_artifacts
from pipelines.physical_inventory import CONTRACT_VERSION, artifact_sha256
from scripts.verify_physical_inventory import (
    AcceptanceError,
    build_receipt,
    published_binding,
)


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


def test_rejects_overcounted_denominator_and_contract_rejects_fabricated_unavailable_metadata() -> (
    None
):
    """The second half asserts contract 11, not the verifier: build_receipt calls
    validate_artifact first, so fabricated unavailable metadata never reaches any
    verifier branch."""
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


def test_contract_rejects_a_claimed_epsg_code_that_is_not_a_real_coordinate_reference() -> (
    None
):
    """Also a contract assertion: validate_artifact resolves the CRS before the
    verifier sees the asset."""
    artifact = _artifact()
    artifact["assets"][0]["geometry_crs"] = "EPSG:103705"
    artifact["content_sha256"] = artifact_sha256(artifact)
    with pytest.raises(AcceptanceError, match="not a registered CRS"):
        build_receipt(artifact, state="tx")


def test_rejects_normalized_assets_that_have_no_state_coverage_row() -> None:
    """A class whose only coverage row is scoped outside the state is not covered."""
    artifact = _artifact()
    artifact["assets"].append(
        {
            "asset_id": "hifld:line:1",
            "asset_class": "line",
            "asset_kind": "transmission_line",
            "source_id": "eia2025er",
            "source_record_id": "line-1",
            "geometry": {
                "type": "LineString",
                "coordinates": [[-97.0, 32.0], [-96.0, 31.0]],
            },
            "geometry_crs": "EPSG:4326",
            "geometry_precision_m": 10.0,
            "geometry_accuracy_basis": "source route geometry",
            "geometry_derivation_method": None,
            "geometry_status": "source",
        }
    )
    artifact["coverage"].append(
        {
            "asset_class": "line",
            "scope_id": "ercot:zone-a",
            "status": "partial",
            "observed_count": 1,
            "denominator_count": None,
            "unknown_count": None,
            "unavailable_count": None,
            "denominator_basis": "source_returned_count:HIFLD",
            "source_scope": "ercot:zone-a",
            "reason": "Zone-scoped source rows are not a Texas class denominator.",
        }
    )
    artifact["content_sha256"] = artifact_sha256(artifact)
    receipt = build_receipt(artifact, state="tx")
    assert receipt["offline_result"] == "REJECTED"
    assert any(
        "line: normalized assets have no tx coverage row" in error
        for error in receipt["errors"]
    )


# --- the committed release artifacts, re-verified rather than restated ---------

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "data/artifacts/physical_inventory/manifest-1.1.0.json"
RECEIPT_DIR = REPO_ROOT / "docs/data/acceptance_receipts"
STATE_RELEASE = RECEIPT_DIR / "physical-inventory-state-release-1.1.0.json"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("state", ["mn", "tx"])
def test_published_release_matches_every_manifest_field(state: str) -> None:
    """Re-hash the committed .gz and its canonical content; restating is not enough."""
    entry = next(row for row in _manifest()["artifacts"] if row["state"] == state)
    published = REPO_ROOT / entry["published_path"]
    compressed = published.read_bytes()
    assert entry["compressed_bytes"] == len(compressed)
    assert entry["compressed_sha256"] == _sha256(compressed)
    canonical = gzip.decompress(compressed)
    assert entry["canonical_json_bytes"] == len(canonical)
    artifact = json.loads(canonical)
    assert entry["canonical_content_sha256"] == artifact["content_sha256"]
    assert artifact["content_sha256"] == artifact_sha256(artifact)
    assert entry["artifact_id"] == artifact["artifact_id"]
    assert entry["asset_count"] == len(artifact["assets"])
    assert entry["input_artifact_sha256s"] == artifact["input_artifact_sha256s"]
    # No absolute path may be committed in the manifest.
    assert "/Users/" not in MANIFEST.read_text(encoding="utf-8")
    assert not entry["published_path"].startswith("/")


@pytest.mark.parametrize("state", ["mn", "tx"])
def test_committed_receipt_is_exactly_what_the_tool_emits(state: str) -> None:
    """The receipt is regenerable: file == build_receipt output, byte for byte."""
    entry = next(row for row in _manifest()["artifacts"] if row["state"] == state)
    published = REPO_ROOT / entry["published_path"]
    artifact = json.loads(gzip.decompress(published.read_bytes()))
    regenerated = build_receipt(
        artifact,
        state=state,
        expected_version=entry["artifact_id"].rsplit(":", 1)[1],
        published_artifact=published,
    )
    committed_path = (
        RECEIPT_DIR / f"physical-inventory-{state}-1.1.0-offline-receipt.json"
    )
    assert (
        committed_path.read_text(encoding="utf-8")
        == json.dumps(regenerated, indent=2, sort_keys=True) + "\n"
    )
    committed = json.loads(committed_path.read_text(encoding="utf-8"))
    assert committed["offline_result"] == "VERIFIED"
    assert committed["errors"] == []
    # The two fields that bind a receipt to a published file are tool-emitted.
    assert committed["artifact"]["published_path"] == entry["published_path"]
    assert committed["artifact"]["published_compressed_sha256"] == _sha256(
        published.read_bytes()
    )
    assert (
        sum(row["normalized_asset_count"] for row in committed["coverage"])
        == entry["asset_count"]
    )


TRACKED_COMPONENTS = (
    "data/artifacts/physical_inventory/mn/eia860-2025er-physical-inventory-1.0.0.json",
    "data/artifacts/physical_inventory/tx/eia860-2025er-physical-inventory-1.0.0.json",
    "data/physical-inventory/minnesota/mille-lacs-county/v1/physical-inventory.json",
)


def test_minnesota_release_lineage_resolves_to_tracked_component_artifacts() -> None:
    """Every MN input digest names a component artifact that exists in this clone."""
    tracked = {
        json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))[
            "content_sha256"
        ]: path
        for path in TRACKED_COMPONENTS
    }
    entry = next(row for row in _manifest()["artifacts"] if row["state"] == "mn")
    artifact = json.loads(
        gzip.decompress((REPO_ROOT / entry["published_path"]).read_bytes())
    )
    assert artifact["input_artifact_sha256s"]
    for digest in artifact["input_artifact_sha256s"]:
        assert digest in tracked, digest
    # Reassembling the tracked components reproduces the published release exactly.
    components = [
        json.loads((REPO_ROOT / tracked[digest]).read_text(encoding="utf-8"))
        for digest in artifact["input_artifact_sha256s"]
    ]
    rebuilt = assemble_artifacts(components, release_version="1.1.0")
    assert rebuilt == artifact


def test_texas_release_lineage_names_its_untracked_component_honestly() -> None:
    """TX has one input that no clone can resolve; the manifest must not imply it can."""
    entry = next(row for row in _manifest()["artifacts"] if row["state"] == "tx")
    artifact = json.loads(
        gzip.decompress((REPO_ROOT / entry["published_path"]).read_bytes())
    )
    tracked = {
        json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))["content_sha256"]
        for path in TRACKED_COMPONENTS
    }
    unresolved = [d for d in artifact["input_artifact_sha256s"] if d not in tracked]
    assert unresolved, "update untracked_input_artifact_sha256s if TX lineage lands"
    assert sorted(unresolved) == sorted(entry["untracked_input_artifact_sha256s"])
    assert entry["untracked_input_reason"]


def test_published_binding_refuses_a_path_outside_the_repository(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "physical-inventory-1.1.0.json.gz"
    outside.write_bytes(gzip.compress(b"{}"))
    with pytest.raises(AcceptanceError, match="outside the repository"):
        published_binding(outside)


def test_minnesota_receipt_source_digests_match_the_committed_capture_bytes() -> None:
    """The MN release's Mille Lacs source rows attest to files in this repository."""
    captures = REPO_ROOT / "data/physical-inventory/minnesota/mille-lacs-county/v1"
    entry = next(row for row in _manifest()["artifacts"] if row["state"] == "mn")
    artifact = json.loads(
        gzip.decompress((REPO_ROOT / entry["published_path"]).read_bytes())
    )
    digests = {row["source_id"]: row["content_sha256"] for row in artifact["sources"]}
    for source_id, capture in (
        (
            "mille_lacs_county_utilities_mapserver_2026:transmission-lines-layer-2",
            "lines.arcgis.json",
        ),
        (
            "mille_lacs_county_utilities_mapserver_2026:substations-layer-0",
            "substations.arcgis.json",
        ),
    ):
        assert digests[source_id] == _sha256((captures / capture).read_bytes())

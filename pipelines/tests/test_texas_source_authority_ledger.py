"""Keep Texas physical-source availability claims mechanically honest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "data/sources/texas-source-authority-ledger-v1.json"

HIFLD_SERVICE_URL = (
    "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
    "US_Electric_Power_Transmission_Lines/FeatureServer/0"
)

# Every physical class the ledger declares, pinned to the state its evidence
# supports. This ledger acquired no artifact, so no class may be complete and
# no class may carry a denominator.
EXPECTED_CLASS_STATUS = {
    "generation": "candidate",
    "line": "candidate",
    "substation": "restricted",
    "distribution_feeder": "unavailable",
    "terminal": "unavailable",
    "electric_service_area": "candidate",
    "intertie_and_seam": "unavailable",
}

# Exact workbook row counts observed on 2026-09-06. They are receipts, not
# denominators, and a fabricated count must not survive here.
EIA_2025_ER_OBSERVATION = {
    "zip_bytes": 23285571,
    "sha256": "bd05bac5149371a6aab869e8a4c737ccb2e6c2f83f0daadac895982af9510bf1",
    "texas_plant_rows": 1514,
    "texas_plants_missing_reported_lat_or_lon": 0,
    "texas_operable_generator_rows": 2376,
    "texas_proposed_generator_rows": 643,
    "texas_retired_or_canceled_generator_rows": 374,
    "texas_operable_storage_rows": 207,
    "texas_proposed_storage_rows": 208,
}


def _ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _source(ledger: dict, source_id: str) -> dict:
    return next(
        row for row in ledger["source_records"] if row["source_id"] == source_id
    )


def test_ledger_declares_its_state_scope_and_status_vocabulary():
    ledger = _ledger()
    assert ledger["schema_version"] == 1
    assert ledger["state"] == "TX"
    assert "not statewide completeness" in ledger["purpose"]
    assert set(ledger["source_status_values"]) == {
        "accepted_limited",
        "candidate",
        "denied",
        "restricted",
        "unavailable",
    }
    for source in ledger["source_records"]:
        assert source["acquisition_state"] in ledger["source_status_values"]
        assert source["url"].startswith("https://")
        assert source["source_crs"]
        assert source["spatial_extent"]


def test_no_physical_class_carries_a_denominator_or_a_complete_status():
    ledger = _ledger()
    coverage = {row["class_id"]: row for row in ledger["physical_class_coverage"]}
    assert {
        cid: row["status"] for cid, row in coverage.items()
    } == EXPECTED_CLASS_STATUS
    for class_id, row in coverage.items():
        assert row["denominator"] is None, class_id
        assert row["known_count"] is None, class_id
        assert row["accepted_source_ids"] == [], class_id
        assert row["reason"].strip()


def test_2wkg_443_required_rows_exist_and_stay_honest():
    ledger = _ledger()
    coverage = {row["class_id"]: row for row in ledger["physical_class_coverage"]}
    seam = coverage["intertie_and_seam"]
    assert seam["status"] == "unavailable"
    assert "ERCOT" in seam["scope"]
    # Unknown, never zero: an unsourced class must not read as "there are none".
    assert "unknown, not zero" in seam["reason"]
    assert coverage["electric_service_area"]["candidate_source_ids"] == [
        "puct-sb1093-electric-service-area-boundaries"
    ]


def test_prohibited_inference_policy_is_present_and_non_empty():
    ledger = _ledger()
    prohibited = ledger["truth_policy"]["prohibited_inference"]
    assert len(prohibited) >= 3
    assert any("ACTIVSg2000" in entry for entry in prohibited)
    forbidden = ledger["implementation_handoff"]["forbidden_derivations"]
    assert set(prohibited) <= set(forbidden)
    assert any("envelope" in entry for entry in forbidden)


def test_the_restricted_substation_source_stays_restricted():
    ledger = _ledger()
    wind = _source(ledger, "hifld-texas-wind-energy-infrastructure-2017")
    assert wind["acquisition_state"] == "restricted"
    assert "499" in wind["access"]
    assert "499" in wind["restriction_reason"]
    assert wind["identity_fields"] == []
    assert "substation_coverage" in wind["does_not_support"]


def test_eia_early_release_observation_matches_the_audited_artifact():
    ledger = _ledger()
    observation = _source(ledger, "eia-860-2025-early-release")["audit_observation"]
    for field, value in EIA_2025_ER_OBSERVATION.items():
        assert observation[field] == value, field
    assert observation["retrieved_at"].startswith("2026-09-06")


def test_the_texas_envelope_count_records_the_query_that_produced_it():
    ledger = _ledger()
    hifld = _source(ledger, "hifld-us-transmission-lines-2024-archive")
    assert hifld["url"] == HIFLD_SERVICE_URL

    envelope = hifld["texas_envelope"]
    assert envelope["crs"] == "EPSG:4269"
    assert (envelope["xmin"], envelope["ymin"], envelope["xmax"], envelope["ymax"]) == (
        -106.645646,
        25.837048,
        -93.508039,
        36.500704,
    )
    assert "tl_2024_us_county.zip" in envelope["provenance"]

    queries = {query["query_id"]: query for query in hifld["verified_queries"]}
    assert set(queries) == {"national_count", "texas_envelope_count"}
    assert queries["national_count"]["returned_feature_count"] == 94619
    texas = queries["texas_envelope_count"]
    assert texas["returned_feature_count"] == 10235
    parameters = texas["query_parameters"]
    assert parameters["geometryType"] == "esriGeometryEnvelope"
    assert parameters["inSR"] == "4269"
    assert parameters["spatialRel"] == "esriSpatialRelIntersects"
    assert json.loads(parameters["geometry"])["xmin"] == envelope["xmin"]

    for query in queries.values():
        # Full URL, not just the parameters: repointing the host must fail.
        assert query["url"].startswith(HIFLD_SERVICE_URL + "/query?")
        verification = query["verification"]
        raw = (ROOT / verification["response_file"]).read_bytes()
        assert len(raw) == verification["response_bytes"]
        assert hashlib.sha256(raw).hexdigest() == verification["response_sha256"]
        assert json.loads(raw)["count"] == query["returned_feature_count"]

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.data.event_baseline_receipt import (
    eaglei_acquisition_from_operational_receipt,
)

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "event_baseline_validate", ROOT / "scripts/data/event_baseline_validate.py"
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def bundle() -> dict:
    receipt = {
        "receipt_id": "source_receipt",
        "provider": "test provider",
        "url": "https://example.invalid/source",
        "release": None,
        "retrieved_at_utc": "2026-09-06T00:00:00Z",
        "license_or_access": "test only",
        "raw_sha256": None,
        "filtered_sha256": None,
        "bytes": None,
        "etag": None,
        "units": "documented in source",
        "timezone_conversion": "source UTC",
        "filters": "test fixture",
        "grid_index_mapping": "not applicable",
        "gaps": ["synthetic test fixture"],
        "capture_method": "synthetic fixture, no bytes retrieved",
        "verification": {"sha256_computed_from_response_body": False},
        "files": {},
        "uncertainty": "synthetic fixture; establishes nothing about the real source",
    }
    return {
        "schema_version": "event-baseline/v1",
        "hazard": "test_hazard",
        "event": {
            "event_id": "test-event",
            "parent_system_id": "test-system",
            "primary_hazard": "test",
            "secondary_hazards": [],
            "compound": False,
            "source_event_ids": ["test-event-id"],
            "context_window": {
                "start_utc": "2021-01-01T00:00:00Z",
                "end_utc": "2021-01-03T00:00:00Z",
            },
            "event_window": {
                "start_utc": "2021-01-01T06:00:00Z",
                "end_utc": "2021-01-01T12:00:00Z",
            },
            "recovery_window": {
                "start_utc": "2021-01-01T12:00:00Z",
                "end_utc": "2021-01-02T00:00:00Z",
            },
            "disposition": "accepted",
            "selection_basis": "synthetic validation fixture",
            "uncertainties": ["not source evidence"],
        },
        "source_receipts": [receipt],
        "records": [
            {
                "record_id": "test-record",
                "county_fips": "27053",
                "boundary_vintage": "2024",
                "scenario_id": "test-scenario",
                "window_start_utc": "2021-01-01T06:00:00Z",
                "window_end_utc": "2021-01-01T12:00:00Z",
                "disposition": "accepted",
                "mode": "replay",
                "provenance_receipt_ids": ["source_receipt"],
                "source_evidence_status": "available",
                "source_row_keys": [
                    "source_receipt:test-release:27053:2021-01-01T06:00:00Z"
                ],
                "source_slices": [
                    {
                        "receipt_id": "source_receipt",
                        "county_fips": "27053",
                        "start_utc": "2021-01-01T06:00:00Z",
                        "end_utc": "2021-01-01T12:00:00Z",
                    }
                ],
                "weather": {
                    "coverage": "covered",
                    "evidence_kind": "time_series_or_grid",
                    "observation_kind": "observed",
                    "source_receipt_ids": ["source_receipt"],
                    "expected_samples": 24,
                    "observed_samples": 24,
                    "missing_timestamps": [],
                    "event_report": None,
                    "notes": "fixture",
                },
                "outage": {
                    "coverage": "covered",
                    "evidence_kind": "time_series_or_grid",
                    "observation_kind": "observed",
                    "source_receipt_ids": ["source_receipt"],
                    "expected_samples": 24,
                    "observed_samples": 24,
                    "missing_timestamps": [],
                    "event_report": None,
                    "notes": "fixture",
                },
                "matched_coverage_decision": "matched",
                "label": {
                    "rule_version": "county_outage_5pct_v1",
                    "status": "computed",
                    "aggregation": "max_customers_out_over_window_samples",
                    "observed_outage_customers": 50,
                    "customer_denominator": {"status": "available", "value": 1000},
                    "outage_rate": 0.05,
                    "positive": True,
                },
                "forecast": {
                    "prediction_cutoff_utc": None,
                    "forecast_evaluation": "not_forecast_scored",
                    "inputs": [],
                },
            }
        ],
    }


def test_accepts_a_matched_six_hour_record() -> None:
    validator.validate_bundle(bundle())


def test_uncovered_eaglei_label_cannot_be_accepted() -> None:
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["outage"]["coverage"] = "UncoveredLabel"
    candidate["records"][0]["label"].update(
        {
            "status": "UncoveredLabel",
            "observed_outage_customers": None,
            "outage_rate": None,
            "positive": None,
        }
    )
    with pytest.raises(
        validator.ValidationError, match="UncoveredLabel may not masquerade"
    ):
        validator.validate_bundle(candidate)


def test_accepted_row_rejects_partial_outage_coverage() -> None:
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["outage"].update(
        {"observed_samples": 5, "missing_timestamps": ["2021-01-01T11:00:00Z"]}
    )
    with pytest.raises(validator.ValidationError, match="complete expected/observed"):
        validator.validate_bundle(candidate)


def test_county_event_report_can_support_weather_without_fake_samples() -> None:
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["weather"] = {
        "coverage": "covered",
        "evidence_kind": "authoritative_event_report",
        "observation_kind": "observed",
        "source_receipt_ids": ["source_receipt"],
        "expected_samples": None,
        "observed_samples": None,
        "missing_timestamps": [],
        "event_report": {
            "source_event_ids": ["test-event-id"],
            "source_window": {
                "start_utc": "2021-01-01T05:00:00Z",
                "end_utc": "2021-01-01T13:00:00Z",
            },
            "spatial_scope": "county",
            "scope_identifier": "27053",
            "limitations": "report evidence, not a time series",
        },
        "notes": "fixture",
    }
    validator.validate_bundle(candidate)


def _zone_report(scope: str, identifier: str) -> dict:
    return {
        "coverage": "covered",
        "evidence_kind": "authoritative_event_report",
        "observation_kind": "observed",
        "source_receipt_ids": ["source_receipt"],
        "expected_samples": None,
        "observed_samples": None,
        "missing_timestamps": [],
        "event_report": {
            "source_event_ids": ["test-event-id"],
            "source_window": {
                "start_utc": "2021-01-01T05:00:00Z",
                "end_utc": "2021-01-01T13:00:00Z",
            },
            "spatial_scope": scope,
            "scope_identifier": identifier,
            "limitations": "not a county time series",
        },
        "notes": "fixture",
    }


def _in_county(candidate: dict, county_fips: str) -> dict:
    """Move the fixture's single record to another county, slices included."""
    record = candidate["records"][0]
    record["county_fips"] = county_fips
    for source_slice in record["source_slices"]:
        source_slice["county_fips"] = county_fips
    return candidate


def test_zone_one_to_one_with_its_county_supports_covered_weather() -> None:
    """MNZ060 is exactly Hennepin 27053 in the NWS correlation, so its report covers."""
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["weather"] = _zone_report(
        "zone", "NWS public forecast zone MNZ060 (Hennepin); NCEI CZ_FIPS:060"
    )
    validator.validate_bundle(candidate)


def test_zone_in_a_multi_zone_county_cannot_claim_covered_county_weather() -> None:
    """Cook County 17031 holds ILZ103/ILZ104/ILZ105, so one zone is not the county."""
    candidate = _in_county(copy.deepcopy(bundle()), "17031")
    candidate["records"][0]["weather"] = _zone_report(
        "zone", "NWS public forecast zone ILZ104 (Central Cook)"
    )
    with pytest.raises(
        validator.ValidationError,
        match=r"county 17031 \(Cook\) contains zones \['ILZ103', 'ILZ104', 'ILZ105'\]",
    ):
        validator.validate_bundle(candidate)


def test_zone_spanning_two_counties_cannot_claim_covered_county_weather() -> None:
    """MNZ012 spans Cook 27031 and Lake 27075; it covers neither on its own."""
    candidate = _in_county(copy.deepcopy(bundle()), "27031")
    candidate["records"][0]["weather"] = _zone_report(
        "zone", "NWS public forecast zone MNZ012 (Northern Cook/Northern Lake)"
    )
    with pytest.raises(
        validator.ValidationError,
        match=r"zone MNZ012 spans counties \['27031', '27075'\]",
    ):
        validator.validate_bundle(candidate)


def test_county_scope_label_cannot_launder_a_zone_report() -> None:
    """Flipping spatial_scope to county on a zone identifier must not buy coverage."""
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["weather"] = _zone_report(
        "county", "NCEI MN zone 060 HENNEPIN"
    )
    with pytest.raises(
        validator.ValidationError, match="county-scoped report names a zone"
    ):
        validator.validate_bundle(candidate)


def test_county_scope_must_name_the_records_county() -> None:
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["weather"] = _zone_report("county", "Ramsey County")
    with pytest.raises(
        validator.ValidationError,
        match="names neither county 27053 nor Hennepin County",
    ):
        validator.validate_bundle(candidate)


def test_covered_zone_report_needs_a_resolvable_zone_id() -> None:
    """A vague zone name cannot be checked against the correlation, so it is refused."""
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["weather"] = _zone_report("zone", "MN zone")
    with pytest.raises(
        validator.ValidationError, match="carries no resolvable NWS zone id"
    ):
        validator.validate_bundle(candidate)


def test_the_correlation_rule_also_governs_outage_reports() -> None:
    """The same epistemic defect one field over: a zone-backed covered outage."""
    candidate = _in_county(copy.deepcopy(bundle()), "17031")
    candidate["event"]["disposition"] = "candidate_only"
    candidate["records"][0]["disposition"] = "candidate_only"
    candidate["records"][0]["matched_coverage_decision"] = "unavailable"
    candidate["records"][0]["outage"] = _zone_report(
        "zone", "NWS public forecast zone ILZ104 (Central Cook)"
    )
    candidate["records"][0]["label"].update(
        {
            "status": "unavailable",
            "observed_outage_customers": None,
            "outage_rate": None,
            "positive": None,
        }
    )
    with pytest.raises(
        validator.ValidationError,
        match=r"records\[0\]\.outage: county 17031 \(Cook\) contains zones",
    ):
        validator.validate_bundle(candidate)


def test_the_verdict_follows_the_correlation_file_not_the_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Give Hennepin a second zone and the very same record must go red.

    This is the probe that proves the rule reads real data: nothing about the
    bundle changes, only the correlation the validator consults.
    """
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["weather"] = _zone_report(
        "zone", "NWS public forecast zone MNZ060 (Hennepin); NCEI CZ_FIPS:060"
    )
    validator.validate_bundle(candidate)

    real = validator.ZONE_COUNTY_CORRELATION_PATH.read_text()
    swapped = tmp_path / "swapped.psv"
    swapped.write_text(
        real
        + "MN|999|MPX|Test Second Hennepin Zone|MN999|Hennepin|27053|C|se|45.0|-93.4\n"
    )
    monkeypatch.setattr(validator, "ZONE_COUNTY_CORRELATION_PATH", swapped)
    monkeypatch.setattr(validator._zone_county_correlation, "cache", None)
    try:
        with pytest.raises(
            validator.ValidationError,
            match=r"county 27053 \(Hennepin\) contains zones \['MNZ060', 'MNZ999'\]",
        ):
            validator.validate_bundle(candidate)
    finally:
        validator._zone_county_correlation.cache = None


def test_the_committed_correlation_slice_is_the_receipted_bytes() -> None:
    """The slice the rule reads must be the file its receipt vouches for."""
    receipt = json.loads(
        (
            validator.ZONE_COUNTY_CORRELATION_PATH.parent / "bp05mr24.receipt.json"
        ).read_text()
    )
    digest = hashlib.sha256(
        validator.ZONE_COUNTY_CORRELATION_PATH.read_bytes()
    ).hexdigest()
    assert (
        digest == receipt["filtered_sha256"] == receipt["files"]["filtered"]["sha256"]
    )
    assert receipt["url"].endswith("bp05mr24.dbx")
    zone_to_counties, county_to_zones, county_names = (
        validator._zone_county_correlation()
    )
    assert zone_to_counties["MNZ060"] == {"27053"}
    assert county_to_zones["17031"] == {"ILZ103", "ILZ104", "ILZ105"}
    assert county_names["27053"] == "Hennepin"


def test_missing_denominator_is_honest_accepted_observation() -> None:
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["label"].update(
        {
            "status": "unavailable",
            "observed_outage_customers": 50,
            "customer_denominator": {"status": "unavailable", "value": None},
            "outage_rate": None,
            "positive": None,
        }
    )
    validator.validate_bundle(candidate)


def test_dynamic_denominator_cannot_produce_scalar_label() -> None:
    candidate = copy.deepcopy(bundle())
    label = candidate["records"][0]["label"]
    label["denominator_observations"] = {
        "status": "dynamic",
        "present_rows": 24,
        "missing_rows": 0,
        "min": 100,
        "max": 101,
    }
    with pytest.raises(validator.ValidationError, match="dynamic denominators"):
        validator.validate_bundle(candidate)


def test_candidate_without_fetched_rows_does_not_need_invented_source_keys() -> None:
    candidate = copy.deepcopy(bundle())
    candidate["event"]["disposition"] = "candidate_only"
    record = candidate["records"][0]
    record.update(
        {
            "disposition": "candidate_only",
            "source_evidence_status": "unavailable",
            "source_row_keys": [],
            "source_slices": [],
            "provenance_receipt_ids": [],
        }
    )
    record["weather"] = {
        "coverage": "uncovered",
        "evidence_kind": "not_assessed",
        "observation_kind": "not_applicable",
        "source_receipt_ids": [],
        "expected_samples": None,
        "observed_samples": None,
        "missing_timestamps": [],
        "event_report": None,
        "notes": "not fetched",
    }
    record["outage"] = {
        "coverage": "UncoveredLabel",
        "evidence_kind": "time_series_or_grid",
        "observation_kind": "observed",
        "source_receipt_ids": [],
        "expected_samples": None,
        "observed_samples": None,
        "missing_timestamps": [],
        "event_report": None,
        "notes": "not fetched",
    }
    record["matched_coverage_decision"] = "unavailable"
    record["label"].update(
        {
            "status": "UncoveredLabel",
            "observed_outage_customers": None,
            "outage_rate": None,
            "positive": None,
        }
    )
    validator.validate_bundle(candidate)


def test_forecast_rejects_input_available_after_cutoff() -> None:
    candidate = copy.deepcopy(bundle())
    record = candidate["records"][0]
    record["mode"] = "forecast"
    record["forecast"] = {
        "prediction_cutoff_utc": "2021-01-01T00:00:00Z",
        "forecast_evaluation": "eligible",
        "inputs": [
            {
                "receipt_id": "source_receipt",
                "published_or_available_at_utc": "2021-01-01T01:00:00Z",
                "run_or_init_utc": "2021-01-01T00:00:00Z",
                "lead_hours": 6,
                "valid_time_utc": "2021-01-01T06:00:00Z",
                "f00_receipt_id": "source_receipt",
                "f01_receipt_id": "source_receipt",
            }
        ],
    }
    with pytest.raises(validator.ValidationError, match="after prediction cutoff"):
        validator.validate_bundle(candidate)


def test_assembler_preserves_event_and_county_window_dispositions(
    tmp_path: Path,
) -> None:
    events = tmp_path / "events" / "test_hazard"
    events.mkdir(parents=True)
    (events / "test-event.json").write_text(json.dumps(bundle()))
    output = tmp_path / "event_catalog.csv"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/data/event_baseline_assemble.py"),
            "--events-dir",
            str(tmp_path / "events"),
            "--output",
            str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "1 county-window rows" in result.stdout
    header, row = output.read_text().splitlines()
    assert "event_disposition" in header and "record_disposition" in header
    assert ",accepted," in row


def test_operational_eaglei_receipt_maps_to_acquisition_proof() -> None:
    raw = {"raw_sha256": "a" * 64, "filtered_sha256": "b" * 64}
    sidecar = {
        "acquisition_complete": True,
        "acquisition_method": "exhaustive_annual_stream",
        "source_system_id": "figshare:24237376:53581661",
        "source_file": "eaglei_outages_2024.csv",
        "source_file_id": 53581661,
        "source_file_bytes": 12,
        "integrity_basis": "figshare_file_metadata_md5_and_size",
        "raw_sha256": "a" * 64,
    }
    proof = eaglei_acquisition_from_operational_receipt(
        raw,
        sidecar,
        raw_artifact_uri="approved://raw",
        source_sidecar_uri="approved://sidecar",
        source_sidecar_sha256="c" * 64,
        filtered_artifact_uri="approved://filtered",
    )
    assert proof["source_file_id"] == 53581661
    assert proof["filtered_artifact_sha256"] == "b" * 64


def test_window_must_be_aligned_to_the_six_hour_vocabulary() -> None:
    """docs/specs/02-outage-model.md: 'Window = 6 h, aligned to 00/06/12/18 UTC'."""
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["window_start_utc"] = "2021-01-01T15:00:00Z"
    candidate["records"][0]["window_end_utc"] = "2021-01-01T21:00:00Z"
    # the published schema refuses the unaligned start by pattern ...
    with pytest.raises(validator.ValidationError, match="schema violation"):
        validator.validate_bundle(candidate)
    # ... and the hand-written rule refuses it independently of the schema.
    with pytest.raises(validator.ValidationError, match="aligned to"):
        validator.validate_bundle_rules(candidate)


def test_window_must_be_exactly_six_hours() -> None:
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["window_end_utc"] = "2021-01-01T18:00:00Z"
    with pytest.raises(validator.ValidationError, match="exactly six hours"):
        validator.validate_bundle(candidate)


def test_five_percent_rule_is_enforced_on_both_sides() -> None:
    below = copy.deepcopy(bundle())
    below["records"][0]["label"].update(
        {"observed_outage_customers": 49, "outage_rate": 0.049, "positive": False}
    )
    validator.validate_bundle(below)
    below["records"][0]["label"]["positive"] = True
    with pytest.raises(validator.ValidationError, match="five-percent rule"):
        validator.validate_bundle(below)

    at_threshold = copy.deepcopy(bundle())
    at_threshold["records"][0]["label"]["positive"] = False
    with pytest.raises(validator.ValidationError, match="five-percent rule"):
        validator.validate_bundle(at_threshold)


def test_outage_rate_must_equal_observed_over_denominator() -> None:
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["label"]["outage_rate"] = 0.5
    with pytest.raises(validator.ValidationError, match="outage_rate must equal"):
        validator.validate_bundle(candidate)


def test_label_aggregation_is_spec_02_max() -> None:
    """docs/specs/02-outage-model.md: max customers_out over the 15-min samples."""
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["label"]["aggregation"] = "mean_over_window_samples"
    # the published schema pins the const ...
    with pytest.raises(validator.ValidationError, match="schema violation"):
        validator.validate_bundle(candidate)
    # ... and the hand-written rule refuses it independently of the schema.
    with pytest.raises(validator.ValidationError, match="aggregation"):
        validator.validate_bundle_rules(candidate)


def test_denominator_below_five_hundred_customers_is_unusable() -> None:
    """docs/specs/02-outage-model.md drops counties with total_customers < 500."""
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["label"]["customer_denominator"]["value"] = 400
    candidate["records"][0]["label"]["observed_outage_customers"] = 20
    with pytest.raises(validator.ValidationError, match="schema violation"):
        validator.validate_bundle(candidate)

    # the same rule holds when the schema's numeric bound is not the first to fire
    bare = copy.deepcopy(bundle())
    record = bare["records"][0]["label"]
    record["customer_denominator"]["value"] = 400
    record["observed_outage_customers"] = 20
    record["outage_rate"] = 0.05
    with pytest.raises(validator.ValidationError, match="total_customers < 500"):
        validator._validate_label(record, "covered", "label")


def test_duplicate_county_window_identity_is_refused() -> None:
    candidate = copy.deepcopy(bundle())
    twin = copy.deepcopy(candidate["records"][0])
    twin["record_id"] = "test-record-twin"
    candidate["records"].append(twin)
    with pytest.raises(
        validator.ValidationError, match="duplicate canonical county-window identity"
    ):
        validator.validate_bundle(candidate)


def test_source_row_key_must_name_a_slice_receipt() -> None:
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["source_row_keys"] = [
        "not_a_slice_receipt:test-release:27053:2021-01-01T06:00:00Z"
    ]
    with pytest.raises(
        validator.ValidationError, match="each key must be <slice receipt_id>"
    ):
        validator.validate_bundle(candidate)


def test_accepted_requires_matched_covered_weather_and_outage() -> None:
    for coverage_name in ("weather", "outage"):
        candidate = copy.deepcopy(bundle())
        candidate["records"][0][coverage_name]["coverage"] = "uncovered"
        with pytest.raises(
            validator.ValidationError,
            match="accepted requires matched covered weather and outage evidence",
        ):
            validator.validate_bundle(candidate)

    unmatched = copy.deepcopy(bundle())
    unmatched["records"][0]["matched_coverage_decision"] = "not_matched"
    with pytest.raises(
        validator.ValidationError,
        match="accepted requires matched covered weather and outage evidence",
    ):
        validator.validate_bundle(unmatched)


def test_accepted_requires_real_source_row_keys_and_slices() -> None:
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["source_evidence_status"] = "unavailable"
    candidate["records"][0]["source_row_keys"] = []
    candidate["records"][0]["source_slices"] = []
    with pytest.raises(
        validator.ValidationError, match="available source-row keys and slices"
    ):
        validator.validate_bundle(candidate)


def test_eaglei_gap_requires_uncovered_label_status() -> None:
    candidate = copy.deepcopy(bundle())
    record = candidate["records"][0]
    candidate["event"]["disposition"] = "candidate_only"
    record["disposition"] = "candidate_only"
    record["matched_coverage_decision"] = "unavailable"
    record["outage"]["coverage"] = "UncoveredLabel"
    record["label"].update(
        {
            "status": "unavailable",
            "observed_outage_customers": None,
            "customer_denominator": {"status": "unavailable", "value": None},
            "outage_rate": None,
            "positive": None,
        }
    )
    with pytest.raises(
        validator.ValidationError, match="EAGLE-I gap requires label.status"
    ):
        validator.validate_bundle(candidate)


def test_published_schema_is_enforced_not_decorative() -> None:
    """The schema file is the single structural definition, not documentation."""
    candidate = copy.deepcopy(bundle())
    candidate["unexpected_top_level_key"] = "should be refused"
    with pytest.raises(validator.ValidationError, match="schema violation"):
        validator.validate_bundle(candidate)

    per_record = copy.deepcopy(bundle())
    per_record["records"][0]["unexpected_record_key"] = "should be refused"
    with pytest.raises(validator.ValidationError, match="schema violation"):
        validator.validate_bundle(per_record)

    missing = copy.deepcopy(bundle())
    del missing["records"][0]["label"]
    with pytest.raises(validator.ValidationError, match="schema violation"):
        validator.validate_bundle(missing)


def test_receipts_carry_the_repo_receipt_convention() -> None:
    """capture_method / verification / files / uncertainty, as in pipelines/hrrr.py."""
    for field in ("capture_method", "verification", "files", "uncertainty"):
        candidate = copy.deepcopy(bundle())
        del candidate["source_receipts"][0][field]
        with pytest.raises(validator.ValidationError, match="schema violation"):
            validator.validate_bundle(candidate)

    empty = copy.deepcopy(bundle())
    empty["source_receipts"][0]["capture_method"] = "   "
    with pytest.raises(validator.ValidationError, match="non-empty statement"):
        validator.validate_bundle(empty)


def test_eaglei_covered_window_expects_fifteen_minute_cadence() -> None:
    """docs/specs/01-data-ingest.md: EAGLE-I is 15-minute cadence -> 24 per window."""
    candidate = copy.deepcopy(bundle())
    receipt = candidate["source_receipts"][0]
    receipt["provider"] = "EAGLE-I / ORNL"
    receipt["acquisition"] = {
        "acquisition_complete": True,
        "acquisition_method": "exhaustive_annual_stream",
        "source_system_id": "figshare:24237376:42547891",
        "source_file": "eaglei_outages_2021.csv",
        "source_file_id": 42547891,
        "source_file_bytes": 1196000000,
        "integrity_basis": "figshare_file_metadata_md5_and_size",
        "raw_artifact_uri": "approved://raw",
        "raw_artifact_sha256": "a" * 64,
        "source_sidecar_uri": "approved://sidecar",
        "source_sidecar_sha256": "c" * 64,
        "filtered_artifact_uri": "approved://filtered",
        "filtered_artifact_sha256": "b" * 64,
    }
    validator.validate_bundle(candidate)

    hourly = copy.deepcopy(candidate)
    hourly["records"][0]["outage"].update(
        {"expected_samples": 6, "observed_samples": 6}
    )
    with pytest.raises(validator.ValidationError, match="15-minute cadence"):
        validator.validate_bundle(hourly)


def test_uncovered_window_may_not_record_a_gap_as_zero() -> None:
    """An EAGLE-I gap is never a measured zero, in either direction."""
    candidate = copy.deepcopy(bundle())
    candidate["event"]["disposition"] = "candidate_only"
    record = candidate["records"][0]
    record["disposition"] = "candidate_only"
    record["matched_coverage_decision"] = "unavailable"
    record["outage"]["coverage"] = "UncoveredLabel"
    record["label"].update(
        {
            "status": "UncoveredLabel",
            "observed_outage_customers": None,
            "customer_denominator": {"status": "unavailable", "value": None},
            "outage_rate": None,
            "positive": None,
        }
    )
    validator.validate_bundle(candidate)

    zeroed = copy.deepcopy(candidate)
    zeroed["records"][0]["label"]["observed_outage_customers"] = 0
    with pytest.raises(validator.ValidationError, match="gap_recorded_as_zero"):
        validator.validate_bundle(zeroed)

    # ... and the same holds when only the label carries the uncovered status.
    label_only = copy.deepcopy(candidate)
    label_only["records"][0]["outage"]["coverage"] = "uncovered"
    label_only["records"][0]["label"]["observed_outage_customers"] = 0
    with pytest.raises(validator.ValidationError, match="gap_recorded_as_zero"):
        validator.validate_bundle(label_only)


def test_exactly_six_hours_but_off_grid_is_still_refused() -> None:
    """A 6h span that is off the 00/06/12/18Z grid is not a valid window."""
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["window_start_utc"] = "2022-09-28T15:00:00Z"
    candidate["records"][0]["window_end_utc"] = "2022-09-28T21:00:00Z"
    with pytest.raises(validator.ValidationError, match="schema violation"):
        validator.validate_bundle(candidate)
    with pytest.raises(validator.ValidationError, match="aligned to"):
        validator.validate_bundle_rules(candidate)

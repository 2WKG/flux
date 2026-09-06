from __future__ import annotations

import copy
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
                    "expected_samples": 6,
                    "observed_samples": 6,
                    "missing_timestamps": [],
                    "event_report": None,
                    "notes": "fixture",
                },
                "outage": {
                    "coverage": "covered",
                    "evidence_kind": "time_series_or_grid",
                    "observation_kind": "observed",
                    "source_receipt_ids": ["source_receipt"],
                    "expected_samples": 6,
                    "observed_samples": 6,
                    "missing_timestamps": [],
                    "event_report": None,
                    "notes": "fixture",
                },
                "matched_coverage_decision": "matched",
                "label": {
                    "rule_version": "county_outage_5pct_v1",
                    "status": "computed",
                    "observed_outage_customers": 5,
                    "customer_denominator": {"status": "available", "value": 100},
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
    with pytest.raises(validator.ValidationError, match="accepted"):
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


def test_missing_denominator_is_honest_accepted_observation() -> None:
    candidate = copy.deepcopy(bundle())
    candidate["records"][0]["label"].update(
        {
            "status": "unavailable",
            "observed_outage_customers": 5,
            "customer_denominator": {"status": "unavailable", "value": None},
            "outage_rate": None,
            "positive": None,
        }
    )
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
    raw = {
        "acquisition_complete": True,
        "acquisition_method": "exhaustive_annual_stream",
        "source_system_id": "figshare:24237376:53581661",
        "source_file": "eaglei_outages_2024.csv",
        "source_file_id": 53581661,
        "source_file_bytes": 12,
        "integrity_basis": "figshare_file_metadata_md5_and_size",
        "raw_sha256": "a" * 64,
        "filtered_sha256": "b" * 64,
    }
    proof = eaglei_acquisition_from_operational_receipt(
        raw,
        raw_artifact_uri="approved://raw",
        source_sidecar_uri="approved://sidecar",
        source_sidecar_sha256="c" * 64,
        filtered_artifact_uri="approved://filtered",
    )
    assert proof["source_file_id"] == 53581661
    assert proof["filtered_artifact_sha256"] == "b" * 64

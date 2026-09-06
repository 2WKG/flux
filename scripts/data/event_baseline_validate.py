#!/usr/bin/env python3
"""Validate Flux historical-event baseline bundles without external schema deps."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "event-baseline/v1"
LABEL_RULE_VERSION = "county_outage_5pct_v1"
SIX_HOURS = timedelta(hours=6)
DISPOSITIONS = {"candidate_only", "accepted", "rejected", "shortfall"}
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
FIPS = re.compile(r"^[0-9]{5}$")


class ValidationError(ValueError):
    pass


def _require(obj: dict[str, Any], key: str, where: str) -> Any:
    if key not in obj:
        raise ValidationError(f"{where}: missing {key}")
    return obj[key]


def _utc(value: Any, where: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValidationError(f"{where}: expected UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise ValidationError(f"{where}: invalid timestamp {value!r}") from exc


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValidationError(f"{where}: expected lower-case stable identifier")
    return value


def _receipt_ids(value: Any, known: set[str], where: str, *, required: bool = False) -> None:
    if not isinstance(value, list):
        raise ValidationError(f"{where}: expected receipt ID list")
    if required and not value:
        raise ValidationError(f"{where}: requires at least one receipt ID")
    unknown = set(value) - known
    if unknown:
        raise ValidationError(f"{where}: unknown receipt IDs {sorted(unknown)}")


def _window(window: Any, where: str) -> tuple[datetime, datetime]:
    if not isinstance(window, dict):
        raise ValidationError(f"{where}: expected window object")
    start = _utc(_require(window, "start_utc", where), f"{where}.start_utc")
    end = _utc(_require(window, "end_utc", where), f"{where}.end_utc")
    if end <= start:
        raise ValidationError(f"{where}: end must be after start")
    return start, end


def _validate_receipts(receipts: Any, where: str) -> set[str]:
    if not isinstance(receipts, list) or not receipts:
        raise ValidationError(f"{where}: source_receipts must be a non-empty list")
    known: set[str] = set()
    for index, receipt in enumerate(receipts):
        prefix = f"{where}[{index}]"
        if not isinstance(receipt, dict):
            raise ValidationError(f"{prefix}: expected object")
        receipt_id = _identifier(_require(receipt, "receipt_id", prefix), f"{prefix}.receipt_id")
        if receipt_id in known:
            raise ValidationError(f"{prefix}: duplicate receipt_id {receipt_id}")
        known.add(receipt_id)
        for field in ("provider", "url", "retrieved_at_utc", "license_or_access", "units", "timezone_conversion", "filters", "grid_index_mapping", "gaps"):
            _require(receipt, field, prefix)
        _utc(receipt["retrieved_at_utc"], f"{prefix}.retrieved_at_utc")
        if not isinstance(receipt["url"], str) or "://" not in receipt["url"]:
            raise ValidationError(f"{prefix}.url: expected absolute URL")
        for digest in ("raw_sha256", "filtered_sha256"):
            value = _require(receipt, digest, prefix)
            if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)):
                raise ValidationError(f"{prefix}.{digest}: expected lowercase SHA-256 or null")
        for field in ("release", "bytes", "etag"):
            _require(receipt, field, prefix)
    return known


def _validate_label(label: Any, outage_coverage: str, where: str) -> None:
    if not isinstance(label, dict):
        raise ValidationError(f"{where}: expected object")
    for field in ("rule_version", "status", "observed_outage_customers", "customer_denominator", "outage_rate", "positive"):
        _require(label, field, where)
    if label["rule_version"] != LABEL_RULE_VERSION:
        raise ValidationError(f"{where}.rule_version: expected {LABEL_RULE_VERSION}")
    status = label["status"]
    if status not in {"computed", "unavailable", "UncoveredLabel"}:
        raise ValidationError(f"{where}.status: invalid label status")
    denom = label["customer_denominator"]
    if not isinstance(denom, dict) or denom.get("status") not in {"available", "unavailable"} or "value" not in denom:
        raise ValidationError(f"{where}.customer_denominator: expected availability and value")
    observed, value, rate, positive = label["observed_outage_customers"], denom["value"], label["outage_rate"], label["positive"]
    if outage_coverage == "UncoveredLabel" and status != "UncoveredLabel":
        raise ValidationError(f"{where}: EAGLE-I gap requires label.status=UncoveredLabel")
    if status == "computed":
        if denom["status"] != "available" or not isinstance(value, (int, float)) or value <= 0:
            raise ValidationError(f"{where}: computed label requires a positive available customer denominator")
        if not isinstance(observed, (int, float)) or observed < 0 or observed > value:
            raise ValidationError(f"{where}: observed outages must be between zero and denominator")
        if not isinstance(rate, (int, float)) or abs(rate - observed / value) > 1e-12:
            raise ValidationError(f"{where}: outage_rate must equal observed_outage_customers / denominator")
        if positive is not (rate >= 0.05):
            raise ValidationError(f"{where}: positive must implement the five-percent rule")
    else:
        if denom["status"] == "unavailable" and value is not None:
            raise ValidationError(f"{where}: unavailable denominator must have null value")
        if rate is not None or positive is not None:
            raise ValidationError(f"{where}: unavailable/uncovered labels cannot assert rate or positivity")


def _validate_forecast(forecast: Any, mode: str, known_receipts: set[str], where: str) -> None:
    if not isinstance(forecast, dict):
        raise ValidationError(f"{where}: expected object")
    cutoff = _require(forecast, "prediction_cutoff_utc", where)
    evaluation = _require(forecast, "forecast_evaluation", where)
    inputs = _require(forecast, "inputs", where)
    if mode == "replay":
        if cutoff is not None or evaluation != "not_forecast_scored" or inputs:
            raise ValidationError(f"{where}: replay must be not_forecast_scored with no cutoff or forecast inputs")
        return
    cutoff_at = _utc(cutoff, f"{where}.prediction_cutoff_utc")
    if evaluation != "eligible" or not isinstance(inputs, list) or not inputs:
        raise ValidationError(f"{where}: forecast requires eligible evaluation and at least one input")
    for index, item in enumerate(inputs):
        prefix = f"{where}.inputs[{index}]"
        if not isinstance(item, dict):
            raise ValidationError(f"{prefix}: expected object")
        for field in ("receipt_id", "published_or_available_at_utc", "run_or_init_utc", "lead_hours", "valid_time_utc", "f00_receipt_id", "f01_receipt_id"):
            _require(item, field, prefix)
        _receipt_ids([item["receipt_id"]], known_receipts, f"{prefix}.receipt_id", required=True)
        available = _utc(item["published_or_available_at_utc"], f"{prefix}.published_or_available_at_utc")
        _utc(item["run_or_init_utc"], f"{prefix}.run_or_init_utc")
        _utc(item["valid_time_utc"], f"{prefix}.valid_time_utc")
        if available > cutoff_at:
            raise ValidationError(f"{prefix}: input became available after prediction cutoff")
        for receipt_field in ("f00_receipt_id", "f01_receipt_id"):
            receipt = item[receipt_field]
            if receipt is not None:
                _receipt_ids([receipt], known_receipts, f"{prefix}.{receipt_field}", required=True)


def validate_bundle(bundle: dict[str, Any], source: str = "bundle") -> None:
    if not isinstance(bundle, dict):
        raise ValidationError(f"{source}: expected JSON object")
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError(f"{source}: expected schema_version {SCHEMA_VERSION}")
    _identifier(_require(bundle, "hazard", source), f"{source}.hazard")
    event = _require(bundle, "event", source)
    if not isinstance(event, dict):
        raise ValidationError(f"{source}.event: expected object")
    for field in ("event_id", "parent_system_id", "primary_hazard", "secondary_hazards", "compound", "source_event_ids", "context_window", "event_window", "recovery_window", "disposition", "selection_basis", "uncertainties"):
        _require(event, field, f"{source}.event")
    _identifier(event["event_id"], f"{source}.event.event_id")
    _identifier(event["parent_system_id"], f"{source}.event.parent_system_id")
    if not isinstance(event["source_event_ids"], list) or not all(isinstance(value, str) and value for value in event["source_event_ids"]):
        raise ValidationError(f"{source}.event.source_event_ids: expected source event ID list")
    if event["disposition"] not in DISPOSITIONS:
        raise ValidationError(f"{source}.event.disposition: invalid disposition")
    if bool(event["secondary_hazards"]) != bool(event["compound"]):
        raise ValidationError(f"{source}.event: compound must match whether secondary_hazards is populated")
    context_start, context_end = _window(event["context_window"], f"{source}.event.context_window")
    event_start, event_end = _window(event["event_window"], f"{source}.event.event_window")
    recovery_start, recovery_end = _window(event["recovery_window"], f"{source}.event.recovery_window")
    if not (context_start <= event_start < event_end <= recovery_start < recovery_end <= context_end):
        raise ValidationError(f"{source}.event: windows must nest context → event → recovery")
    known_receipts = _validate_receipts(_require(bundle, "source_receipts", source), f"{source}.source_receipts")
    records = _require(bundle, "records", source)
    if not isinstance(records, list) or not records:
        raise ValidationError(f"{source}.records: expected non-empty list")
    identities: set[tuple[str, str, datetime]] = set()
    for index, record in enumerate(records):
        prefix = f"{source}.records[{index}]"
        if not isinstance(record, dict):
            raise ValidationError(f"{prefix}: expected object")
        for field in ("record_id", "county_fips", "boundary_vintage", "scenario_id", "window_start_utc", "window_end_utc", "disposition", "mode", "provenance_receipt_ids", "source_evidence_status", "source_row_keys", "source_slices", "weather", "outage", "matched_coverage_decision", "label", "forecast"):
            _require(record, field, prefix)
        _identifier(record["record_id"], f"{prefix}.record_id")
        if not isinstance(record["county_fips"], str) or not FIPS.fullmatch(record["county_fips"]):
            raise ValidationError(f"{prefix}.county_fips: expected five digits")
        _identifier(record["scenario_id"], f"{prefix}.scenario_id")
        start, end = _utc(record["window_start_utc"], f"{prefix}.window_start_utc"), _utc(record["window_end_utc"], f"{prefix}.window_end_utc")
        if end - start != SIX_HOURS:
            raise ValidationError(f"{prefix}: county window must be exactly six hours")
        identity = (record["county_fips"], record["scenario_id"], start)
        if identity in identities:
            raise ValidationError(f"{prefix}: duplicate canonical county-window identity")
        identities.add(identity)
        if record["disposition"] not in DISPOSITIONS or record["mode"] not in {"replay", "forecast"}:
            raise ValidationError(f"{prefix}: invalid disposition or mode")
        _receipt_ids(record["provenance_receipt_ids"], known_receipts, f"{prefix}.provenance_receipt_ids", required=record["disposition"] == "accepted")
        if record["source_evidence_status"] not in {"available", "unavailable"}:
            raise ValidationError(f"{prefix}.source_evidence_status: expected available or unavailable")
        if not isinstance(record["source_row_keys"], list) or not all(isinstance(key, str) and key for key in record["source_row_keys"]):
            raise ValidationError(f"{prefix}.source_row_keys: expected stable string keys")
        if len(record["source_row_keys"]) != len(set(record["source_row_keys"])):
            raise ValidationError(f"{prefix}.source_row_keys: duplicate source row key")
        if not isinstance(record["source_slices"], list):
            raise ValidationError(f"{prefix}.source_slices: expected receipt/county/time slice list")
        if record["disposition"] == "accepted" and (record["source_evidence_status"] != "available" or not record["source_row_keys"] or not record["source_slices"]):
            raise ValidationError(f"{prefix}: accepted record requires available source-row keys and slices")
        if record["source_evidence_status"] == "unavailable" and (record["source_row_keys"] or record["source_slices"]):
            raise ValidationError(f"{prefix}: unavailable source evidence must not invent row keys or slices")
        for slice_index, source_slice in enumerate(record["source_slices"]):
            slice_prefix = f"{prefix}.source_slices[{slice_index}]"
            if not isinstance(source_slice, dict):
                raise ValidationError(f"{slice_prefix}: expected object")
            _receipt_ids([_require(source_slice, "receipt_id", slice_prefix)], known_receipts, f"{slice_prefix}.receipt_id", required=True)
            if not isinstance(_require(source_slice, "county_fips", slice_prefix), str) or not FIPS.fullmatch(source_slice["county_fips"]):
                raise ValidationError(f"{slice_prefix}.county_fips: expected five digits")
            slice_start = _utc(_require(source_slice, "start_utc", slice_prefix), f"{slice_prefix}.start_utc")
            slice_end = _utc(_require(source_slice, "end_utc", slice_prefix), f"{slice_prefix}.end_utc")
            if slice_end <= slice_start:
                raise ValidationError(f"{slice_prefix}: end must be after start")
        slice_receipt_ids = {source_slice["receipt_id"] for source_slice in record["source_slices"]}
        for source_key in record["source_row_keys"]:
            receipt_id, separator, native_key = source_key.partition(":")
            if not separator or not native_key or receipt_id not in slice_receipt_ids:
                raise ValidationError(f"{prefix}.source_row_keys: each key must be <slice receipt_id>:<source-native-row-key>")
        for coverage_name in ("weather", "outage"):
            coverage = record[coverage_name]
            if not isinstance(coverage, dict) or coverage.get("coverage") not in {"covered", "uncovered", "UncoveredLabel"}:
                raise ValidationError(f"{prefix}.{coverage_name}: invalid coverage state")
            _receipt_ids(coverage.get("source_receipt_ids"), known_receipts, f"{prefix}.{coverage_name}.source_receipt_ids", required=record["disposition"] == "accepted")
            for field in ("evidence_kind", "observation_kind", "expected_samples", "observed_samples", "missing_timestamps", "event_report", "notes"):
                _require(coverage, field, f"{prefix}.{coverage_name}")
            expected, observed, missing = coverage["expected_samples"], coverage["observed_samples"], coverage["missing_timestamps"]
            if not isinstance(missing, list):
                raise ValidationError(f"{prefix}.{coverage_name}.missing_timestamps: expected list")
            for timestamp in missing:
                _utc(timestamp, f"{prefix}.{coverage_name}.missing_timestamps")
            kind, observation = coverage["evidence_kind"], coverage["observation_kind"]
            if kind == "time_series_or_grid":
                if observation not in {"observed", "modeled"} or coverage["event_report"] is not None:
                    raise ValidationError(f"{prefix}.{coverage_name}: sampled/grid evidence needs observed or modeled kind and no event_report")
                if coverage["coverage"] == "covered" and (not isinstance(expected, int) or expected <= 0 or observed != expected or missing):
                    raise ValidationError(f"{prefix}.{coverage_name}: covered requires complete expected/observed samples and no gaps")
            elif kind == "authoritative_event_report":
                report = coverage["event_report"]
                if observation != "observed" or expected is not None or observed is not None or missing:
                    raise ValidationError(f"{prefix}.{coverage_name}: event report cannot fabricate sample counts")
                if not isinstance(report, dict) or report.get("spatial_scope") not in {"county", "zone"}:
                    raise ValidationError(f"{prefix}.{coverage_name}: report evidence requires county or zone scope")
                report_start, report_end = _window(report.get("source_window"), f"{prefix}.{coverage_name}.event_report.source_window")
                if report_end <= start or report_start >= end:
                    raise ValidationError(f"{prefix}.{coverage_name}: report interval must intersect county window")
            elif kind == "not_assessed":
                if observation != "not_applicable" or expected is not None or observed is not None or missing or coverage["event_report"] is not None:
                    raise ValidationError(f"{prefix}.{coverage_name}: not_assessed evidence must not claim samples or report coverage")
            else:
                raise ValidationError(f"{prefix}.{coverage_name}: invalid evidence kind")
            if kind != "authoritative_event_report" and expected is not None and (not isinstance(observed, int) or observed > expected):
                raise ValidationError(f"{prefix}.{coverage_name}: observed samples may not exceed expected samples")
        weather_state, outage_state = record["weather"]["coverage"], record["outage"]["coverage"]
        if record["disposition"] == "accepted" and record["outage"]["evidence_kind"] != "time_series_or_grid":
            raise ValidationError(f"{prefix}.outage: outage labels require time_series_or_grid evidence")
        if record["disposition"] == "accepted" and (weather_state != "covered" or outage_state != "covered" or record["matched_coverage_decision"] != "matched"):
            raise ValidationError(f"{prefix}: accepted requires matched covered weather and outage evidence")
        if outage_state == "UncoveredLabel" and record["disposition"] == "accepted":
            raise ValidationError(f"{prefix}: UncoveredLabel may not masquerade as accepted")
        _validate_label(record["label"], outage_state, f"{prefix}.label")
        _validate_forecast(record["forecast"], record["mode"], known_receipts, f"{prefix}.forecast")


def load_and_validate(path: Path) -> dict[str, Any]:
    try:
        bundle = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{path}: cannot read JSON: {exc}") from exc
    validate_bundle(bundle, str(path))
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles", nargs="+", type=Path, help="event bundle JSON files")
    args = parser.parse_args(argv)
    failures = 0
    for path in args.bundles:
        try:
            load_and_validate(path)
            print(f"VALID {path}")
        except ValidationError as exc:
            print(f"INVALID {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

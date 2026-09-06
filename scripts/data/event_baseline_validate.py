"""Validate Flux historical-event baseline bundles against the published schema.

The published JSON Schema (``event_baseline.schema.json``) is the single
structural definition: it is loaded and enforced here, including its
``additionalProperties: false``. The hand-written rules below only add the
cross-field reality contracts a JSON Schema cannot express.
"""

from __future__ import annotations

import sys

# This validator needs the interpreter pinned by pyproject.toml (>=3.12,<3.13):
# `datetime.UTC` below is 3.11+, so an older interpreter would otherwise die on a
# bare ImportError that reads like a bundle failure. Fail loudly, with its own
# exit code, so an environment problem is never mistaken for a validation red.
if sys.version_info < (3, 12):  # noqa: UP036 - the point is to catch older runtimes
    sys.stderr.write(
        "INTERPRETER event_baseline_validate.py requires Python >=3.12 "
        f"(pyproject.toml requires-python); got {sys.version.split()[0]}. "
        "This is an environment failure, not a bundle validation failure. "
        "Run `uv run python scripts/data/event_baseline_validate.py ...`.\n"
    )
    raise SystemExit(2)

import argparse
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/data/event-baseline/event_baseline.schema.json"
)
SCHEMA_VERSION = "event-baseline/v1"
LABEL_RULE_VERSION = "county_outage_5pct_v1"
SIX_HOURS = timedelta(hours=6)
DISPOSITIONS = {"candidate_only", "accepted", "rejected", "shortfall"}
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
FIPS = re.compile(r"^[0-9]{5}$")
# docs/specs/02-outage-model.md: "Window = 6 h, aligned to 00/06/12/18 UTC".
ALIGNED_WINDOW_START_HOURS = (0, 6, 12, 18)
# docs/specs/01-data-ingest.md: EAGLE-I is 15-minute cadence (minutes 00/15/30/45,
# verified on the 2021 and 2024 files) -> 24 samples in a six-hour window.
EAGLEI_SAMPLES_PER_WINDOW = 24
# docs/specs/02-outage-model.md: counties with total_customers < 500 are dropped.
MINIMUM_CUSTOMER_DENOMINATOR = 500
LABEL_AGGREGATION = "max_customers_out_over_window_samples"
# docs/data/event-baseline/README.md: a zone-scoped event report establishes county
# weather coverage only when the NWS public forecast zone is 1:1 with the county in
# NOAA's own zone/county correlation file. The receipted slice next to it records the
# source URL, retrieval, and sha256 of the rows below.
ZONE_COUNTY_CORRELATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/data/event-baseline/controls-metadata/nws-zone-county-correlation"
    / "bp05mr24.psv"
)
# STATE_ZONE column form, e.g. "MN060"; also how a covered report must name its zone.
NWS_ZONE_ID = re.compile(r"\b([A-Z]{2})Z?([0-9]{3})\b")
ZONE_WORD = re.compile(r"\bzones?\b", re.IGNORECASE)


class ValidationError(ValueError):
    pass


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text())


def _schema_validator() -> jsonschema.protocols.Validator:
    schema = _load_schema()
    validator_class = jsonschema.validators.validator_for(schema)
    validator_class.check_schema(schema)
    return validator_class(schema)


def validate_against_published_schema(bundle: Any, source: str = "bundle") -> None:
    """Enforce the published JSON Schema, including additionalProperties: false."""
    errors = sorted(_schema_validator().iter_errors(bundle), key=str)
    if not errors:
        return
    first = errors[0]
    location = "/".join(str(part) for part in first.absolute_path) or "<root>"
    raise ValidationError(f"{source}: schema violation at {location}: {first.message}")


def _is_eaglei_receipt(receipt: dict[str, Any]) -> bool:
    return (
        "eagle-i" in str(receipt.get("provider", "")).casefold()
        or "eaglei" in str(receipt.get("url", "")).casefold()
    )


def _require(obj: dict[str, Any], key: str, where: str) -> Any:
    if key not in obj:
        raise ValidationError(f"{where}: missing {key}")
    return obj[key]


def _utc(value: Any, where: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValidationError(f"{where}: expected UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError as exc:
        raise ValidationError(f"{where}: invalid timestamp {value!r}") from exc


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValidationError(f"{where}: expected lower-case stable identifier")
    return value


def _receipt_ids(
    value: Any, known: set[str], where: str, *, required: bool = False
) -> None:
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


def _zone_county_correlation() -> tuple[
    dict[str, set[str]], dict[str, set[str]], dict[str, str]
]:
    """Parse the receipted NWS zone/county correlation slice.

    Returns ``(zone -> county FIPS set, county FIPS -> zone id set, county FIPS ->
    county name)``. Zone ids are normalised to ``<STATE>Z<NNN>`` (e.g. ``MNZ060``).
    """
    if _zone_county_correlation.cache is None:  # type: ignore[attr-defined]
        zone_to_counties: dict[str, set[str]] = {}
        county_to_zones: dict[str, set[str]] = {}
        county_names: dict[str, str] = {}
        text = ZONE_COUNTY_CORRELATION_PATH.read_text()
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split("|")
            if len(fields) < 7:
                raise ValidationError(
                    f"{ZONE_COUNTY_CORRELATION_PATH.name}: expected the eleven-column "
                    "NWS correlation layout"
                )
            state, zone, county, fips = fields[0], fields[1], fields[5], fields[6]
            zone_id = f"{state}Z{zone}"
            zone_to_counties.setdefault(zone_id, set()).add(fips)
            county_to_zones.setdefault(fips, set()).add(zone_id)
            county_names[fips] = county
        _zone_county_correlation.cache = (  # type: ignore[attr-defined]
            zone_to_counties,
            county_to_zones,
            county_names,
        )
    return _zone_county_correlation.cache  # type: ignore[attr-defined]


_zone_county_correlation.cache = None  # type: ignore[attr-defined]


def _report_establishes_county_coverage(
    report: dict[str, Any], county_fips: str, where: str
) -> None:
    """Refuse a ``covered`` event report that the correlation does not support.

    A zone-scoped report establishes coverage of a county only when the correlation
    makes the two 1:1 -- the zone lies in that county and no other, and the county
    contains that zone and no other. A county-scoped report must actually name the
    record's county, so flipping ``spatial_scope`` on a zone identifier cannot buy
    coverage.
    """
    zone_to_counties, county_to_zones, county_names = _zone_county_correlation()
    scope = report.get("spatial_scope")
    identifier = report.get("scope_identifier")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValidationError(f"{where}: covered report requires a scope_identifier")
    if county_fips not in county_to_zones:
        raise ValidationError(
            f"{where}: county {county_fips} is absent from the NWS zone/county "
            f"correlation ({ZONE_COUNTY_CORRELATION_PATH.name}); coverage cannot be "
            "established"
        )
    if scope == "county":
        county_name = county_names[county_fips]
        if ZONE_WORD.search(identifier):
            raise ValidationError(
                f"{where}: county-scoped report names a zone "
                f"({identifier!r}); a zone report may not be relabelled as county scope"
            )
        if (
            county_name.lower() not in identifier.lower()
            and county_fips not in identifier
        ):
            raise ValidationError(
                f"{where}: county-scoped report identifier {identifier!r} names neither "
                f"county {county_fips} nor {county_name} County"
            )
        return
    match = NWS_ZONE_ID.search(identifier)
    if match is None:
        raise ValidationError(
            f"{where}: covered zone report identifier {identifier!r} carries no "
            "resolvable NWS zone id (expected e.g. MNZ060)"
        )
    zone_id = f"{match.group(1)}Z{match.group(2)}"
    counties = zone_to_counties.get(zone_id)
    if not counties:
        raise ValidationError(
            f"{where}: zone {zone_id} is absent from the NWS zone/county correlation "
            f"({ZONE_COUNTY_CORRELATION_PATH.name})"
        )
    if counties != {county_fips}:
        raise ValidationError(
            f"{where}: zone {zone_id} spans counties {sorted(counties)} in the NWS "
            f"correlation, so it does not establish coverage of county {county_fips}"
        )
    zones = county_to_zones[county_fips]
    if zones != {zone_id}:
        raise ValidationError(
            f"{where}: county {county_fips} ({county_names[county_fips]}) contains "
            f"zones {sorted(zones)} in the NWS correlation, so zone {zone_id} covers "
            "only part of it"
        )


def _validate_receipts(receipts: Any, where: str) -> dict[str, dict[str, Any]]:
    if not isinstance(receipts, list) or not receipts:
        raise ValidationError(f"{where}: source_receipts must be a non-empty list")
    known: dict[str, dict[str, Any]] = {}
    for index, receipt in enumerate(receipts):
        prefix = f"{where}[{index}]"
        if not isinstance(receipt, dict):
            raise ValidationError(f"{prefix}: expected object")
        receipt_id = _identifier(
            _require(receipt, "receipt_id", prefix), f"{prefix}.receipt_id"
        )
        if receipt_id in known:
            raise ValidationError(f"{prefix}: duplicate receipt_id {receipt_id}")
        known[receipt_id] = receipt
        for field in (
            "provider",
            "url",
            "retrieved_at_utc",
            "license_or_access",
            "units",
            "timezone_conversion",
            "filters",
            "grid_index_mapping",
            "gaps",
            "capture_method",
            "verification",
            "files",
            "uncertainty",
        ):
            _require(receipt, field, prefix)
        for field in ("capture_method", "uncertainty"):
            if not isinstance(receipt[field], str) or not receipt[field].strip():
                raise ValidationError(
                    f"{prefix}.{field}: expected a non-empty statement "
                    f"(same receipt convention as pipelines/hrrr.py)"
                )
        verification = receipt["verification"]
        if (
            not isinstance(verification, dict)
            or "sha256_computed_from_response_body" not in verification
        ):
            raise ValidationError(
                f"{prefix}.verification: expected an object recording "
                f"sha256_computed_from_response_body"
            )
        _utc(receipt["retrieved_at_utc"], f"{prefix}.retrieved_at_utc")
        if not isinstance(receipt["url"], str) or "://" not in receipt["url"]:
            raise ValidationError(f"{prefix}.url: expected absolute URL")
        for digest in ("raw_sha256", "filtered_sha256"):
            value = _require(receipt, digest, prefix)
            if value is not None and (
                not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
            ):
                raise ValidationError(
                    f"{prefix}.{digest}: expected lowercase SHA-256 or null"
                )
        for field in ("release", "bytes", "etag"):
            _require(receipt, field, prefix)
    return known


def _validate_eaglei_acquisition(receipt: dict[str, Any], where: str) -> None:
    acquisition = receipt.get("acquisition")
    required = (
        "acquisition_complete",
        "acquisition_method",
        "source_system_id",
        "source_file",
        "source_file_id",
        "source_file_bytes",
        "integrity_basis",
        "raw_artifact_uri",
        "raw_artifact_sha256",
        "source_sidecar_uri",
        "source_sidecar_sha256",
        "filtered_artifact_uri",
        "filtered_artifact_sha256",
    )
    if (
        not isinstance(acquisition, dict)
        or acquisition.get("acquisition_complete") is not True
    ):
        raise ValidationError(
            f"{where}: definitive EAGLE-I evidence requires complete acquisition proof"
        )
    for field in required:
        if field not in acquisition or acquisition[field] in {None, ""}:
            raise ValidationError(f"{where}.acquisition: missing {field}")
    for field in (
        "raw_artifact_sha256",
        "source_sidecar_sha256",
        "filtered_artifact_sha256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", acquisition[field]):
            raise ValidationError(f"{where}.acquisition.{field}: expected SHA-256")


def _validate_label(label: Any, outage_coverage: str, where: str) -> None:
    if not isinstance(label, dict):
        raise ValidationError(f"{where}: expected object")
    for field in (
        "rule_version",
        "status",
        "aggregation",
        "observed_outage_customers",
        "customer_denominator",
        "outage_rate",
        "positive",
    ):
        _require(label, field, where)
    if label["rule_version"] != LABEL_RULE_VERSION:
        raise ValidationError(f"{where}.rule_version: expected {LABEL_RULE_VERSION}")
    if label["aggregation"] != LABEL_AGGREGATION:
        raise ValidationError(
            f"{where}.aggregation: {LABEL_RULE_VERSION} is spec 02's y_out and takes the "
            f"max customers_out over the window's samples ({LABEL_AGGREGATION})"
        )
    status = label["status"]
    if status not in {"computed", "unavailable", "UncoveredLabel"}:
        raise ValidationError(f"{where}.status: invalid label status")
    denom = label["customer_denominator"]
    if (
        not isinstance(denom, dict)
        or denom.get("status") not in {"available", "unavailable"}
        or "value" not in denom
    ):
        raise ValidationError(
            f"{where}.customer_denominator: expected availability and value"
        )
    observed, value, rate, positive = (
        label["observed_outage_customers"],
        denom["value"],
        label["outage_rate"],
        label["positive"],
    )
    observations = label.get("denominator_observations")
    if observations is not None:
        if not isinstance(observations, dict) or observations.get("status") not in {
            "constant",
            "dynamic",
            "unavailable",
        }:
            raise ValidationError(f"{where}.denominator_observations: invalid status")
        if observations["status"] == "dynamic" and (
            status != "unavailable"
            or label.get("unavailability_reason") != "dynamic_denominator_unsupported"
        ):
            raise ValidationError(
                f"{where}: dynamic denominators require unavailable scalar label"
            )
    if outage_coverage == "UncoveredLabel" and status != "UncoveredLabel":
        raise ValidationError(
            f"{where}: EAGLE-I gap requires label.status=UncoveredLabel"
        )
    # An uncovered window has no measured count. The rule above already forces
    # status == "UncoveredLabel" whenever the outage coverage is a gap, so this
    # one clause covers both directions.
    if status == "UncoveredLabel" and observed is not None:
        raise ValidationError(
            f"{where}: gap_recorded_as_zero — an uncovered window has no measured "
            f"outage count, so observed_outage_customers must be null, not "
            f"{observed!r}"
        )
    if status == "computed":
        if (
            denom["status"] != "available"
            or not isinstance(value, (int, float))
            or value <= 0
        ):
            raise ValidationError(
                f"{where}: computed label requires a positive available customer denominator"
            )
        if value < MINIMUM_CUSTOMER_DENOMINATOR:
            raise ValidationError(
                f"{where}: docs/specs/02-outage-model.md drops counties with "
                f"total_customers < {MINIMUM_CUSTOMER_DENOMINATOR}; denominator "
                f"{value} is unusable for county_outage_5pct_v1"
            )
        if not isinstance(observed, (int, float)) or observed < 0 or observed > value:
            raise ValidationError(
                f"{where}: observed outages must be between zero and denominator"
            )
        if not isinstance(rate, (int, float)) or abs(rate - observed / value) > 1e-12:
            raise ValidationError(
                f"{where}: outage_rate must equal observed_outage_customers / denominator"
            )
        if positive is not (rate >= 0.05):
            raise ValidationError(
                f"{where}: positive must implement the five-percent rule"
            )
    else:
        if denom["status"] == "unavailable" and value is not None:
            raise ValidationError(
                f"{where}: unavailable denominator must have null value"
            )
        if rate is not None or positive is not None:
            raise ValidationError(
                f"{where}: unavailable/uncovered labels cannot assert rate or positivity"
            )


def _validate_forecast(
    forecast: Any, mode: str, known_receipts: set[str], where: str
) -> None:
    if not isinstance(forecast, dict):
        raise ValidationError(f"{where}: expected object")
    cutoff = _require(forecast, "prediction_cutoff_utc", where)
    evaluation = _require(forecast, "forecast_evaluation", where)
    inputs = _require(forecast, "inputs", where)
    if mode == "replay":
        if cutoff is not None or evaluation != "not_forecast_scored" or inputs:
            raise ValidationError(
                f"{where}: replay must be not_forecast_scored with no cutoff or forecast inputs"
            )
        return
    cutoff_at = _utc(cutoff, f"{where}.prediction_cutoff_utc")
    if evaluation != "eligible" or not isinstance(inputs, list) or not inputs:
        raise ValidationError(
            f"{where}: forecast requires eligible evaluation and at least one input"
        )
    for index, item in enumerate(inputs):
        prefix = f"{where}.inputs[{index}]"
        if not isinstance(item, dict):
            raise ValidationError(f"{prefix}: expected object")
        for field in (
            "receipt_id",
            "published_or_available_at_utc",
            "run_or_init_utc",
            "lead_hours",
            "valid_time_utc",
            "f00_receipt_id",
            "f01_receipt_id",
        ):
            _require(item, field, prefix)
        _receipt_ids(
            [item["receipt_id"]], known_receipts, f"{prefix}.receipt_id", required=True
        )
        available = _utc(
            item["published_or_available_at_utc"],
            f"{prefix}.published_or_available_at_utc",
        )
        _utc(item["run_or_init_utc"], f"{prefix}.run_or_init_utc")
        _utc(item["valid_time_utc"], f"{prefix}.valid_time_utc")
        if available > cutoff_at:
            raise ValidationError(
                f"{prefix}: input became available after prediction cutoff"
            )
        for receipt_field in ("f00_receipt_id", "f01_receipt_id"):
            receipt = item[receipt_field]
            if receipt is not None:
                _receipt_ids(
                    [receipt],
                    known_receipts,
                    f"{prefix}.{receipt_field}",
                    required=True,
                )


def validate_bundle(bundle: dict[str, Any], source: str = "bundle") -> None:
    """Enforce the published schema, then the cross-field reality contracts."""
    if not isinstance(bundle, dict):
        raise ValidationError(f"{source}: expected JSON object")
    validate_against_published_schema(bundle, source)
    validate_bundle_rules(bundle, source)


def validate_bundle_rules(bundle: dict[str, Any], source: str = "bundle") -> None:
    """Cross-field rules a JSON Schema cannot express. Run after the schema."""
    if not isinstance(bundle, dict):
        raise ValidationError(f"{source}: expected JSON object")
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError(f"{source}: expected schema_version {SCHEMA_VERSION}")
    _identifier(_require(bundle, "hazard", source), f"{source}.hazard")
    event = _require(bundle, "event", source)
    if not isinstance(event, dict):
        raise ValidationError(f"{source}.event: expected object")
    for field in (
        "event_id",
        "parent_system_id",
        "primary_hazard",
        "secondary_hazards",
        "compound",
        "source_event_ids",
        "context_window",
        "event_window",
        "recovery_window",
        "disposition",
        "selection_basis",
        "uncertainties",
    ):
        _require(event, field, f"{source}.event")
    _identifier(event["event_id"], f"{source}.event.event_id")
    _identifier(event["parent_system_id"], f"{source}.event.parent_system_id")
    if not isinstance(event["source_event_ids"], list) or not all(
        isinstance(value, str) and value for value in event["source_event_ids"]
    ):
        raise ValidationError(
            f"{source}.event.source_event_ids: expected source event ID list"
        )
    if event["disposition"] not in DISPOSITIONS:
        raise ValidationError(f"{source}.event.disposition: invalid disposition")
    if bool(event["secondary_hazards"]) != bool(event["compound"]):
        raise ValidationError(
            f"{source}.event: compound must match whether secondary_hazards is populated"
        )
    context_start, context_end = _window(
        event["context_window"], f"{source}.event.context_window"
    )
    event_start, event_end = _window(
        event["event_window"], f"{source}.event.event_window"
    )
    recovery_start, recovery_end = _window(
        event["recovery_window"], f"{source}.event.recovery_window"
    )
    if not (
        context_start
        <= event_start
        < event_end
        <= recovery_start
        < recovery_end
        <= context_end
    ):
        raise ValidationError(
            f"{source}.event: windows must nest context → event → recovery"
        )
    receipt_map = _validate_receipts(
        _require(bundle, "source_receipts", source), f"{source}.source_receipts"
    )
    known_receipts = set(receipt_map)
    records = _require(bundle, "records", source)
    if not isinstance(records, list) or not records:
        raise ValidationError(f"{source}.records: expected non-empty list")
    identities: set[tuple[str, str, datetime]] = set()
    for index, record in enumerate(records):
        prefix = f"{source}.records[{index}]"
        if not isinstance(record, dict):
            raise ValidationError(f"{prefix}: expected object")
        for field in (
            "record_id",
            "county_fips",
            "boundary_vintage",
            "scenario_id",
            "window_start_utc",
            "window_end_utc",
            "disposition",
            "mode",
            "provenance_receipt_ids",
            "source_evidence_status",
            "source_row_keys",
            "source_slices",
            "weather",
            "outage",
            "matched_coverage_decision",
            "label",
            "forecast",
        ):
            _require(record, field, prefix)
        _identifier(record["record_id"], f"{prefix}.record_id")
        if not isinstance(record["county_fips"], str) or not FIPS.fullmatch(
            record["county_fips"]
        ):
            raise ValidationError(f"{prefix}.county_fips: expected five digits")
        _identifier(record["scenario_id"], f"{prefix}.scenario_id")
        start, end = (
            _utc(record["window_start_utc"], f"{prefix}.window_start_utc"),
            _utc(record["window_end_utc"], f"{prefix}.window_end_utc"),
        )
        if end - start != SIX_HOURS:
            raise ValidationError(f"{prefix}: county window must be exactly six hours")
        if (
            start.hour not in ALIGNED_WINDOW_START_HOURS
            or start.minute
            or start.second
            or start.microsecond
        ):
            raise ValidationError(
                f"{prefix}: six-hour windows are a closed vocabulary aligned to "
                f"00/06/12/18 UTC (docs/specs/02-outage-model.md); "
                f"{record['window_start_utc']} is not an aligned window start"
            )
        identity = (record["county_fips"], record["scenario_id"], start)
        if identity in identities:
            raise ValidationError(
                f"{prefix}: duplicate canonical county-window identity"
            )
        identities.add(identity)
        if record["disposition"] not in DISPOSITIONS or record["mode"] not in {
            "replay",
            "forecast",
        }:
            raise ValidationError(f"{prefix}: invalid disposition or mode")
        _receipt_ids(
            record["provenance_receipt_ids"],
            known_receipts,
            f"{prefix}.provenance_receipt_ids",
            required=record["disposition"] == "accepted",
        )
        if record["source_evidence_status"] not in {"available", "unavailable"}:
            raise ValidationError(
                f"{prefix}.source_evidence_status: expected available or unavailable"
            )
        if not isinstance(record["source_row_keys"], list) or not all(
            isinstance(key, str) and key for key in record["source_row_keys"]
        ):
            raise ValidationError(
                f"{prefix}.source_row_keys: expected stable string keys"
            )
        if len(record["source_row_keys"]) != len(set(record["source_row_keys"])):
            raise ValidationError(f"{prefix}.source_row_keys: duplicate source row key")
        if not isinstance(record["source_slices"], list):
            raise ValidationError(
                f"{prefix}.source_slices: expected receipt/county/time slice list"
            )
        if record["disposition"] == "accepted" and (
            record["source_evidence_status"] != "available"
            or not record["source_row_keys"]
            or not record["source_slices"]
        ):
            raise ValidationError(
                f"{prefix}: accepted record requires available source-row keys and slices"
            )
        if record["source_evidence_status"] == "unavailable" and (
            record["source_row_keys"] or record["source_slices"]
        ):
            raise ValidationError(
                f"{prefix}: unavailable source evidence must not invent row keys or slices"
            )
        for slice_index, source_slice in enumerate(record["source_slices"]):
            slice_prefix = f"{prefix}.source_slices[{slice_index}]"
            if not isinstance(source_slice, dict):
                raise ValidationError(f"{slice_prefix}: expected object")
            _receipt_ids(
                [_require(source_slice, "receipt_id", slice_prefix)],
                known_receipts,
                f"{slice_prefix}.receipt_id",
                required=True,
            )
            if not isinstance(
                _require(source_slice, "county_fips", slice_prefix), str
            ) or not FIPS.fullmatch(source_slice["county_fips"]):
                raise ValidationError(
                    f"{slice_prefix}.county_fips: expected five digits"
                )
            slice_start = _utc(
                _require(source_slice, "start_utc", slice_prefix),
                f"{slice_prefix}.start_utc",
            )
            slice_end = _utc(
                _require(source_slice, "end_utc", slice_prefix),
                f"{slice_prefix}.end_utc",
            )
            if slice_end <= slice_start:
                raise ValidationError(f"{slice_prefix}: end must be after start")
        slice_receipt_ids = {
            source_slice["receipt_id"] for source_slice in record["source_slices"]
        }
        for source_key in record["source_row_keys"]:
            receipt_id, separator, native_key = source_key.partition(":")
            if not separator or not native_key or receipt_id not in slice_receipt_ids:
                raise ValidationError(
                    f"{prefix}.source_row_keys: each key must be <slice receipt_id>:<source-native-row-key>"
                )
        for coverage_name in ("weather", "outage"):
            coverage = record[coverage_name]
            if not isinstance(coverage, dict) or coverage.get("coverage") not in {
                "covered",
                "uncovered",
                "UncoveredLabel",
            }:
                raise ValidationError(
                    f"{prefix}.{coverage_name}: invalid coverage state"
                )
            _receipt_ids(
                coverage.get("source_receipt_ids"),
                known_receipts,
                f"{prefix}.{coverage_name}.source_receipt_ids",
                required=record["disposition"] == "accepted",
            )
            for field in (
                "evidence_kind",
                "observation_kind",
                "expected_samples",
                "observed_samples",
                "missing_timestamps",
                "event_report",
                "notes",
            ):
                _require(coverage, field, f"{prefix}.{coverage_name}")
            expected, observed, missing = (
                coverage["expected_samples"],
                coverage["observed_samples"],
                coverage["missing_timestamps"],
            )
            if not isinstance(missing, list):
                raise ValidationError(
                    f"{prefix}.{coverage_name}.missing_timestamps: expected list"
                )
            for timestamp in missing:
                _utc(timestamp, f"{prefix}.{coverage_name}.missing_timestamps")
            kind, observation = coverage["evidence_kind"], coverage["observation_kind"]
            if kind == "time_series_or_grid":
                if (
                    observation not in {"observed", "modeled"}
                    or coverage["event_report"] is not None
                ):
                    raise ValidationError(
                        f"{prefix}.{coverage_name}: sampled/grid evidence needs observed or modeled kind and no event_report"
                    )
                if coverage["coverage"] == "covered" and (
                    not isinstance(expected, int)
                    or expected <= 0
                    or observed != expected
                    or missing
                ):
                    raise ValidationError(
                        f"{prefix}.{coverage_name}: covered requires complete expected/observed samples and no gaps"
                    )
            elif kind == "authoritative_event_report":
                report = coverage["event_report"]
                if (
                    observation != "observed"
                    or expected is not None
                    or observed is not None
                    or missing
                ):
                    raise ValidationError(
                        f"{prefix}.{coverage_name}: event report cannot fabricate sample counts"
                    )
                if not isinstance(report, dict) or report.get("spatial_scope") not in {
                    "county",
                    "zone",
                }:
                    raise ValidationError(
                        f"{prefix}.{coverage_name}: report evidence requires county or zone scope"
                    )
                if coverage["coverage"] == "covered":
                    _report_establishes_county_coverage(
                        report,
                        record["county_fips"],
                        f"{prefix}.{coverage_name}",
                    )
                report_start, report_end = _window(
                    report.get("source_window"),
                    f"{prefix}.{coverage_name}.event_report.source_window",
                )
                if report_end <= start or report_start >= end:
                    raise ValidationError(
                        f"{prefix}.{coverage_name}: report interval must intersect county window"
                    )
            elif kind == "not_assessed":
                if (
                    observation != "not_applicable"
                    or expected is not None
                    or observed is not None
                    or missing
                    or coverage["event_report"] is not None
                ):
                    raise ValidationError(
                        f"{prefix}.{coverage_name}: not_assessed evidence must not claim samples or report coverage"
                    )
            else:
                raise ValidationError(
                    f"{prefix}.{coverage_name}: invalid evidence kind"
                )
            if (
                kind != "authoritative_event_report"
                and expected is not None
                and (not isinstance(observed, int) or observed > expected)
            ):
                raise ValidationError(
                    f"{prefix}.{coverage_name}: observed samples may not exceed expected samples"
                )
        weather_state, outage_state = (
            record["weather"]["coverage"],
            record["outage"]["coverage"],
        )
        if (
            record["disposition"] == "accepted"
            and record["outage"]["evidence_kind"] != "time_series_or_grid"
        ):
            raise ValidationError(
                f"{prefix}.outage: outage labels require time_series_or_grid evidence"
            )
        if outage_state == "UncoveredLabel" and record["disposition"] == "accepted":
            raise ValidationError(
                f"{prefix}: UncoveredLabel may not masquerade as accepted"
            )
        if record["disposition"] == "accepted" and (
            weather_state != "covered"
            or outage_state != "covered"
            or record["matched_coverage_decision"] != "matched"
        ):
            raise ValidationError(
                f"{prefix}: accepted requires matched covered weather and outage evidence"
            )
        if outage_state in {"covered", "UncoveredLabel"}:
            for receipt_id in record["outage"]["source_receipt_ids"]:
                receipt = receipt_map[receipt_id]
                if _is_eaglei_receipt(receipt):
                    _validate_eaglei_acquisition(
                        receipt, f"{prefix}.outage[{receipt_id}]"
                    )
                    if (
                        record["outage"]["evidence_kind"] == "time_series_or_grid"
                        and outage_state == "covered"
                        and record["outage"]["expected_samples"]
                        != EAGLEI_SAMPLES_PER_WINDOW
                    ):
                        raise ValidationError(
                            f"{prefix}.outage: EAGLE-I is 15-minute cadence "
                            f"(docs/specs/01-data-ingest.md), so a covered six-hour "
                            f"window expects {EAGLEI_SAMPLES_PER_WINDOW} samples, not "
                            f"{record['outage']['expected_samples']}"
                        )
        _validate_label(record["label"], outage_state, f"{prefix}.label")
        _validate_forecast(
            record["forecast"], record["mode"], known_receipts, f"{prefix}.forecast"
        )


def load_and_validate(path: Path) -> dict[str, Any]:
    try:
        bundle = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{path}: cannot read JSON: {exc}") from exc
    validate_bundle(bundle, str(path))
    return bundle


def iter_bundle_paths(events_dir: Path) -> list[Path]:
    """Every bundle JSON under an events tree, in stable order."""
    return sorted(events_dir.rglob("*.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundles", nargs="*", type=Path, help="event bundle JSON files")
    parser.add_argument(
        "--events-dir",
        type=Path,
        default=None,
        help="validate every *.json under this events tree",
    )
    args = parser.parse_args(argv)
    paths = list(args.bundles)
    if args.events_dir is not None:
        paths.extend(iter_bundle_paths(args.events_dir))
    if not paths:
        parser.error("give bundle paths or --events-dir")
    failures = 0
    for path in paths:
        try:
            load_and_validate(path)
            print(f"VALID {path}")
        except ValidationError as exc:
            print(f"INVALID {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

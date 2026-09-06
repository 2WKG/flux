"""Assemble validated event bundles into a deterministic county-window catalog."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from event_baseline_validate import ValidationError, load_and_validate

FIELDS = [
    "event_id",
    "parent_system_id",
    "primary_hazard",
    "secondary_hazards",
    "source_event_ids",
    "compound",
    "event_disposition",
    "record_id",
    "county_fips",
    "boundary_vintage",
    "scenario_id",
    "window_start_utc",
    "window_end_utc",
    "record_disposition",
    "mode",
    "weather_coverage",
    "weather_evidence_kind",
    "weather_observation_kind",
    "weather_expected_samples",
    "weather_observed_samples",
    "weather_missing_timestamps",
    "weather_event_report",
    "outage_coverage",
    "outage_evidence_kind",
    "outage_observation_kind",
    "outage_expected_samples",
    "outage_observed_samples",
    "outage_missing_timestamps",
    "outage_event_report",
    "matched_coverage_decision",
    "label_rule_version",
    "label_status",
    "observed_outage_customers",
    "customer_denominator_status",
    "customer_denominator",
    "outage_rate",
    "positive",
    "provenance_receipt_ids",
    "source_evidence_status",
    "source_row_keys",
    "source_slices",
    "uncertainties",
    "exclusions",
]


def catalog_rows(events_dir: Path) -> list[dict[str, object]]:
    paths = sorted(events_dir.glob("*/*.json"))
    if not paths:
        raise ValidationError(f"{events_dir}: no event bundle JSON files found")
    rows: list[dict[str, object]] = []
    identities: set[tuple[str, str, str]] = set()
    for path in paths:
        bundle = load_and_validate(path)
        event = bundle["event"]
        for record in bundle["records"]:
            identity = (
                record["county_fips"],
                record["scenario_id"],
                record["window_start_utc"],
            )
            if identity in identities:
                raise ValidationError(
                    f"duplicate canonical county-window identity across bundles: {identity}"
                )
            identities.add(identity)
            label = record["label"]
            denominator = label["customer_denominator"]
            rows.append(
                {
                    "event_id": event["event_id"],
                    "parent_system_id": event["parent_system_id"],
                    "primary_hazard": event["primary_hazard"],
                    "secondary_hazards": json_list(event["secondary_hazards"]),
                    "source_event_ids": json_list(event["source_event_ids"]),
                    "compound": str(event["compound"]).lower(),
                    "event_disposition": event["disposition"],
                    "record_id": record["record_id"],
                    "county_fips": record["county_fips"],
                    "boundary_vintage": record["boundary_vintage"],
                    "scenario_id": record["scenario_id"],
                    "window_start_utc": record["window_start_utc"],
                    "window_end_utc": record["window_end_utc"],
                    "record_disposition": record["disposition"],
                    "mode": record["mode"],
                    "weather_coverage": record["weather"]["coverage"],
                    "weather_evidence_kind": record["weather"]["evidence_kind"],
                    "weather_observation_kind": record["weather"]["observation_kind"],
                    "weather_expected_samples": record["weather"]["expected_samples"],
                    "weather_observed_samples": record["weather"]["observed_samples"],
                    "weather_missing_timestamps": json_list(
                        record["weather"]["missing_timestamps"]
                    ),
                    "weather_event_report": json_list(
                        record["weather"]["event_report"]
                    ),
                    "outage_coverage": record["outage"]["coverage"],
                    "outage_evidence_kind": record["outage"]["evidence_kind"],
                    "outage_observation_kind": record["outage"]["observation_kind"],
                    "outage_expected_samples": record["outage"]["expected_samples"],
                    "outage_observed_samples": record["outage"]["observed_samples"],
                    "outage_missing_timestamps": json_list(
                        record["outage"]["missing_timestamps"]
                    ),
                    "outage_event_report": json_list(record["outage"]["event_report"]),
                    "matched_coverage_decision": record["matched_coverage_decision"],
                    "label_rule_version": label["rule_version"],
                    "label_status": label["status"],
                    "observed_outage_customers": label["observed_outage_customers"],
                    "customer_denominator_status": denominator["status"],
                    "customer_denominator": denominator["value"],
                    "outage_rate": label["outage_rate"],
                    "positive": label["positive"],
                    "provenance_receipt_ids": json_list(
                        record["provenance_receipt_ids"]
                    ),
                    "source_evidence_status": record["source_evidence_status"],
                    "source_row_keys": json_list(record["source_row_keys"]),
                    "source_slices": json_list(record["source_slices"]),
                    "uncertainties": json_list(event["uncertainties"]),
                    "exclusions": json_list(event.get("exclusions", [])),
                }
            )
    return sorted(
        rows,
        key=lambda row: (
            str(row["event_id"]),
            str(row["county_fips"]),
            str(row["scenario_id"]),
            str(row["window_start_utc"]),
        ),
    )


def json_list(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rows = catalog_rows(args.events_dir)
    except ValidationError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"WROTE {args.output} ({len(rows)} county-window rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

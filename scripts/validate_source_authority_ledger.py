"""Validate a state physical-grid source-authority ledger against the shared schema.

Both `data/sources/minnesota-source-authority-ledger-v1.json` and
`data/sources/texas-source-authority-ledger-v1.json` implement the same
`2WKG-439` contract, so one validator covers both. Every check here is
mechanical: it either reads the ledger's own declarations or hashes a receipt
file that is checked into the repository. Nothing reaches a provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

LEDGER_GLOB = "data/sources/*-source-authority-ledger-v1.json"

REQUIRED_TOP_LEVEL = (
    "schema_version",
    "ledger_id",
    "state",
    "retrieved_at",
    "purpose",
    "truth_boundary",
    "source_status_values",
    "coverage_status_values",
    "source_records",
    "physical_class_coverage",
    "implementation_handoff",
)

REQUIRED_SOURCE_FIELDS = (
    "source_id",
    "acquisition_state",
    "publisher",
    "url",
    "version_or_vintage",
    "access",
    "spatial_extent",
    "source_crs",
    "geometry_accuracy_basis",
    "supports_classes",
    "does_not_support",
)

REQUIRED_COVERAGE_FIELDS = (
    "class_id",
    "status",
    "accepted_source_ids",
    "denominator",
    "known_count",
    "unknown_count",
    "unavailable_count",
    "reason",
)

# An acquisition state that did not yield an accepted artifact must say why, in
# a named field. A closed attempt without a reason is an unexplained gap.
REASON_FIELDS = ("unavailability_reason", "restriction_reason", "acquisition_condition")

# Coverage statuses that must never carry a denominator or a known_count: they
# describe an acquisition that produced no source-backed features at all.
EMPTY_COVERAGE_STATUSES = frozenset(
    {"unavailable", "restricted", "candidate", "denied"}
)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _check_receipt(
    root: Path, label: str, query: dict[str, Any], parent_url: str, errors: list[str]
) -> None:
    """A query receipt must replay: full URL under its own source, bytes on disk."""
    url = query.get("url")
    if not isinstance(url, str) or not url.startswith(parent_url):
        errors.append(
            f"{label}: verified_query.url {url!r} is not under {parent_url!r}"
        )
        return
    if "/query?" not in url:
        errors.append(f"{label}: verified_query.url {url!r} is not a /query request")
    verification = query.get("verification")
    if not isinstance(verification, dict):
        errors.append(f"{label}: verified_query has no verification block")
        return
    for field in (
        "retrieved_at",
        "capture_method",
        "response_file",
        "response_bytes",
        "response_sha256",
    ):
        if not verification.get(field):
            errors.append(f"{label}: verification.{field} is missing or empty")
    response_file = verification.get("response_file")
    if not isinstance(response_file, str):
        return
    path = root / response_file
    if not path.is_file():
        errors.append(
            f"{label}: verification.response_file {response_file} does not exist"
        )
        return
    payload = path.read_bytes()
    if len(payload) != verification.get("response_bytes"):
        errors.append(
            f"{label}: {response_file} is {len(payload)} bytes, "
            f"ledger records {verification.get('response_bytes')!r}"
        )
    actual = _sha256_bytes(payload)
    if actual != verification.get("response_sha256"):
        errors.append(
            f"{label}: {response_file} hashes to {actual}, "
            f"ledger records {verification.get('response_sha256')!r}"
        )
    try:
        observed = json.loads(payload)
    except ValueError:
        errors.append(f"{label}: {response_file} is not JSON")
        return
    if "count" in observed and observed["count"] != query.get("returned_feature_count"):
        errors.append(
            f"{label}: captured response count {observed['count']!r} does not equal "
            f"returned_feature_count {query.get('returned_feature_count')!r}"
        )


def validate_ledger(ledger: dict[str, Any], root: Path) -> list[str]:
    """Return every schema and honesty error found in one ledger."""
    errors: list[str] = []

    missing = [key for key in REQUIRED_TOP_LEVEL if key not in ledger]
    if missing:
        errors.append(f"ledger is missing top-level fields: {sorted(missing)}")
        return errors

    if ledger["schema_version"] != 1:
        errors.append(
            f"schema_version must be the integer 1, got {ledger['schema_version']!r}"
        )
    for key in ("ledger_id", "state", "retrieved_at", "purpose", "truth_boundary"):
        if not isinstance(ledger[key], str) or not ledger[key].strip():
            errors.append(f"{key} must be a non-empty string")

    source_states = ledger["source_status_values"]
    coverage_states = ledger["coverage_status_values"]
    for name, values in (
        ("source_status_values", source_states),
        ("coverage_status_values", coverage_states),
    ):
        if (
            not isinstance(values, list)
            or not values
            or len(set(values)) != len(values)
        ):
            errors.append(f"{name} must be a non-empty list of unique strings")

    source_ids: set[str] = set()
    for index, source in enumerate(ledger["source_records"]):
        label = f"source_records[{index}]"
        absent = [field for field in REQUIRED_SOURCE_FIELDS if field not in source]
        if absent:
            errors.append(f"{label}: missing fields {sorted(absent)}")
            continue
        label = f"source_records[{source['source_id']}]"
        if source["source_id"] in source_ids:
            errors.append(f"{label}: duplicate source_id")
        source_ids.add(source["source_id"])
        state = source["acquisition_state"]
        if state not in source_states:
            errors.append(
                f"{label}: acquisition_state {state!r} is not in source_status_values"
            )
        if not str(source["url"]).startswith("https://"):
            errors.append(f"{label}: url must be https, got {source['url']!r}")
        for field in (
            "spatial_extent",
            "source_crs",
            "geometry_accuracy_basis",
            "version_or_vintage",
        ):
            if not isinstance(source[field], str) or not source[field].strip():
                errors.append(f"{label}: {field} must be a non-empty string")
        if state == "accepted_limited" and source["source_crs"].startswith(
            "unavailable"
        ):
            errors.append(
                f"{label}: an accepted source must declare a real source_crs, "
                f"got {source['source_crs']!r}"
            )
        if state != "accepted_limited" and not any(
            source.get(field) for field in REASON_FIELDS
        ):
            errors.append(
                f"{label}: acquisition_state {state!r} must carry one of {list(REASON_FIELDS)}"
            )
        if "verified_query" in source:
            _check_receipt(root, label, source["verified_query"], source["url"], errors)
        for layer in source.get("verified_layers", []):
            layer_label = f"{label}.{layer.get('class_id', '?')}"
            layer_url = layer.get("layer_url", "")
            if not str(layer_url).startswith(source["url"]):
                errors.append(
                    f"{layer_label}: layer_url {layer_url!r} is not under {source['url']!r}"
                )
            if layer.get("denominator") != layer.get("returned_feature_count"):
                errors.append(
                    f"{layer_label}: denominator {layer.get('denominator')!r} must equal "
                    f"returned_feature_count {layer.get('returned_feature_count')!r}"
                )
            if not str(layer.get("denominator_scope", "")).strip():
                errors.append(
                    f"{layer_label}: denominator_scope is required next to a denominator"
                )
            if "verified_query" in layer:
                _check_receipt(
                    root, layer_label, layer["verified_query"], layer_url, errors
                )

    seen_classes: set[str] = set()
    for index, row in enumerate(ledger["physical_class_coverage"]):
        label = f"physical_class_coverage[{index}]"
        absent = [field for field in REQUIRED_COVERAGE_FIELDS if field not in row]
        if absent:
            errors.append(f"{label}: missing fields {sorted(absent)}")
            continue
        label = f"physical_class_coverage[{row['class_id']}]"
        if row["class_id"] in seen_classes:
            errors.append(f"{label}: duplicate class_id")
        seen_classes.add(row["class_id"])
        if row["status"] not in coverage_states:
            errors.append(
                f"{label}: status {row['status']!r} is not in coverage_status_values"
            )
        unknown = [sid for sid in row["accepted_source_ids"] if sid not in source_ids]
        if unknown:
            errors.append(
                f"{label}: accepted_source_ids reference unknown sources {unknown}"
            )
        if row["status"] in EMPTY_COVERAGE_STATUSES:
            if row["denominator"] is not None:
                errors.append(
                    f"{label}: status {row['status']!r} must keep denominator null, "
                    f"got {row['denominator']!r}"
                )
            if row["known_count"] is not None:
                errors.append(
                    f"{label}: status {row['status']!r} must keep known_count null, "
                    f"got {row['known_count']!r}"
                )
            if row["accepted_source_ids"]:
                errors.append(
                    f"{label}: status {row['status']!r} cannot list accepted_source_ids"
                )
        elif not row["accepted_source_ids"]:
            errors.append(
                f"{label}: status {row['status']!r} requires at least one accepted source"
            )
        if (
            row["denominator"] is not None
            and not str(row.get("denominator_scope", "")).strip()
        ):
            errors.append(
                f"{label}: a non-null denominator requires a denominator_scope"
            )
        if not str(row["reason"]).strip():
            errors.append(f"{label}: reason must be a non-empty string")

    handoff = ledger["implementation_handoff"]
    if not isinstance(handoff, dict) or not handoff.get("forbidden_derivations"):
        errors.append(
            "implementation_handoff.forbidden_derivations must be a non-empty list"
        )

    return errors


def discover_ledgers(root: Path) -> list[Path]:
    """Return every checked-in source-authority ledger, sorted by path."""
    return sorted(root.glob(LEDGER_GLOB))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "ledgers", nargs="*", type=Path, help="ledger paths (default: all)"
    )
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args(argv)

    paths = args.ledgers or discover_ledgers(args.root)
    if not paths:
        print(f"no ledger matched {LEDGER_GLOB}", file=sys.stderr)
        return 2

    failed = False
    for path in paths:
        errors = validate_ledger(
            json.loads(path.read_text(encoding="utf-8")), args.root
        )
        if errors:
            failed = True
            print(f"{path}: {len(errors)} error(s)")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"{path}: ok")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

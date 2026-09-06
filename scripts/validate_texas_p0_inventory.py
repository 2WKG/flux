"""Validate the checked-in Texas P0 evidence inventory and emit a JSON report."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ALLOWED_STATUSES = frozenset({"ingested", "validated", "unavailable", "excluded"})
REQUIRED_RECORD_FIELDS = frozenset(
    {
        "id",
        "category",
        "provider",
        "source_url",
        "vintage",
        "license_access",
        "artifacts",
        "coverage",
        "timezone",
        "units",
        "destinations",
        "status",
        "ingestion_timestamp",
        "reason",
    }
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_public(record: dict[str, Any]) -> bool:
    return record["license_access"].get("access") == "public"


# Statuses that assert evidence is checked into the repository. Every one of them
# must point at a tracked receipt and carry the receipt's retrieval timestamp;
# the two remaining statuses must carry neither.
EVIDENCED_STATUSES = frozenset({"ingested", "validated"})
UNEVIDENCED_STATUSES = frozenset({"unavailable", "excluded"})


def validate_inventory(inventory: dict[str, Any]) -> list[str]:
    """Return schema and honesty errors without reaching out to a provider."""
    return _validate(inventory)[0]


def _validate(inventory: dict[str, Any]) -> tuple[list[str], set[int]]:
    """Return errors plus the indices of records that failed validation."""
    errors: list[str] = []
    invalid: set[int] = set()
    if inventory.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    caveat = inventory.get("synthetic_geometry_caveat", "").lower()
    if "synthetic" not in caveat or "not the real ercot" not in caveat:
        errors.append(
            "synthetic_geometry_caveat must say the topology is synthetic and not the real ERCOT network"
        )
    records = inventory.get("records")
    if not isinstance(records, list) or not records:
        return errors + ["records must be a non-empty list"], set()
    seen: set[str] = set()
    for index, record in enumerate(records):
        before = len(errors)
        _validate_record(record, f"records[{index}]", seen, errors)
        if len(errors) > before:
            invalid.add(index)
    return errors, invalid


def _validate_record(
    record: Any, prefix: str, seen: set[str], errors: list[str]
) -> None:
    if not isinstance(record, dict):
        errors.append(f"{prefix} must be an object")
        return
    missing = REQUIRED_RECORD_FIELDS - record.keys()
    if missing:
        errors.append(f"{prefix} is missing {', '.join(sorted(missing))}")
        return
    identifier = record["id"]
    if not isinstance(identifier, str) or not identifier:
        errors.append(f"{prefix}.id must be a non-empty string")
    elif identifier in seen:
        errors.append(f"duplicate record id: {identifier}")
    else:
        seen.add(identifier)
    if record["status"] not in ALLOWED_STATUSES:
        errors.append(f"{prefix}.status must be one of {sorted(ALLOWED_STATUSES)}")
    if not isinstance(record["reason"], str) or not record["reason"].strip():
        errors.append(f"{prefix}.reason must explain the status")
    if not str(record["source_url"]).startswith("https://"):
        errors.append(f"{prefix}.source_url must be an https URL")
    access = record["license_access"]
    if (
        not isinstance(access, dict)
        or not access.get("license")
        or not access.get("access")
    ):
        errors.append(f"{prefix}.license_access must name license and access")
    elif not _is_public(record):
        errors.append(
            f"{prefix} is outside this public-only inventory (access must be public)"
        )
    artifacts = record["artifacts"]
    if not isinstance(artifacts, list) or not all(
        isinstance(artifact, dict) and isinstance(artifact.get("logical_name"), str)
        for artifact in artifacts
    ):
        errors.append(
            f"{prefix}.artifacts must be a list of objects with a logical_name"
        )
        artifacts = []
    if not isinstance(record["units"], dict) or not record["units"]:
        errors.append(f"{prefix}.units must be a non-empty object")
    if not isinstance(record["destinations"], list):
        errors.append(f"{prefix}.destinations must be a list")
    status = record["status"]
    if status == "validated" and not any(
        artifact.get("immutable_id") for artifact in artifacts
    ):
        errors.append(
            f"{prefix}.validated record needs an immutable artifact identifier"
        )
    receipt = record.get("checked_in_receipt")
    timestamp = record["ingestion_timestamp"]
    if status in EVIDENCED_STATUSES:
        if not isinstance(receipt, str) or not receipt.strip():
            errors.append(f"{prefix}.{status} record needs a checked_in_receipt path")
        if not isinstance(timestamp, str) or not timestamp.strip():
            errors.append(f"{prefix}.{status} record needs an ingestion_timestamp")
    elif status in UNEVIDENCED_STATUSES:
        if receipt is not None:
            errors.append(
                f"{prefix}.{status} record must not claim a checked_in_receipt"
            )
        if timestamp is not None:
            errors.append(
                f"{prefix}.{status} record must have a null ingestion_timestamp"
            )


def _runtime_artifacts(record: dict[str, Any], raw_root: Path) -> list[dict[str, Any]]:
    result = []
    for artifact in record["artifacts"]:
        raw_path = artifact.get("raw_path")
        path = raw_root / raw_path if raw_path else None
        present = bool(path and path.is_file())
        entry = {
            "logical_name": artifact.get("logical_name"),
            "immutable_id": artifact.get("immutable_id"),
            "raw_path": raw_path,
            "present_in_requested_raw_root": present,
        }
        if (
            present
            and isinstance(artifact.get("immutable_id"), str)
            and artifact["immutable_id"].startswith("sha256:")
        ):
            actual = _sha256(path)
            entry["observed_sha256"] = actual
            entry["checksum_matches_inventory"] = actual == artifact[
                "immutable_id"
            ].removeprefix("sha256:")
        result.append(entry)
    return result


def _receipt_validation(
    record: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Match a validated record's declared hashes to its tracked receipt.

    Paths are emitted with ``as_posix`` so the published ledger is identical on
    every operating system; ``str(Path(...))`` would write Windows separators.
    """
    receipt_name = record.get("checked_in_receipt")
    if receipt_name is None:
        return None, []
    receipt_path = Path(receipt_name)
    if not receipt_path.is_file():
        return {"path": receipt_path.as_posix(), "passed": False}, [
            f"{record['id']} receipt is missing: {receipt_path}"
        ]
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {"path": receipt_path.as_posix(), "passed": False}, [
            f"{record['id']} receipt is invalid JSON: {error.msg}"
        ]
    mismatches: list[str] = []
    receipt_files = receipt.get("files", {})
    for artifact in record["artifacts"]:
        immutable_id = artifact.get("immutable_id")
        if isinstance(immutable_id, str) and immutable_id.startswith("sha256:"):
            receipt_hash = receipt_files.get(artifact["logical_name"], {}).get("sha256")
            if receipt_hash != immutable_id.removeprefix("sha256:"):
                mismatches.append(artifact["logical_name"])
    if receipt.get("retrieved_at") != record["ingestion_timestamp"]:
        mismatches.append("retrieved_at")
    result = {
        "path": receipt_path.as_posix(),
        "passed": not mismatches,
        "mismatches": mismatches,
    }
    errors = (
        [f"{record['id']} receipt does not match inventory: {', '.join(mismatches)}"]
        if mismatches
        else []
    )
    return result, errors


def build_report(inventory: dict[str, Any], raw_root: Path) -> dict[str, Any]:
    errors, invalid = _validate(inventory)
    records = []
    raw_records = inventory.get("records")
    for index, record in enumerate(
        raw_records if isinstance(raw_records, list) else []
    ):
        if not isinstance(record, dict):
            record = {}
        if index in invalid:
            # The record already failed validation; never run artifact or receipt
            # checks on a shape we did not validate.
            runtime_artifacts: list[dict[str, Any]] = []
            receipt_validation = None
        else:
            runtime_artifacts = _runtime_artifacts(record, raw_root)
            receipt_validation, receipt_errors = _receipt_validation(record)
            errors.extend(receipt_errors)
        records.append(
            {
                "id": record.get("id"),
                "category": record.get("category"),
                "provider": record.get("provider"),
                "source_url": record.get("source_url"),
                "vintage": record.get("vintage"),
                "license_access": record.get("license_access"),
                "coverage": record.get("coverage"),
                "timezone": record.get("timezone"),
                "units": record.get("units"),
                "destinations": record.get("destinations"),
                "status": record.get("status"),
                "ingestion_timestamp": record.get("ingestion_timestamp"),
                "reason": record.get("reason"),
                "artifacts": runtime_artifacts,
                "checked_in_receipt": receipt_validation,
                "schema_valid": index not in invalid,
            }
        )
    counts = Counter(record["status"] for record in records)
    report = {
        "report_schema_version": 1,
        "inventory_id": inventory.get("inventory_id"),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "validation": {"passed": not errors, "errors": errors},
        "summary": {
            status: counts.get(status, 0) for status in sorted(ALLOWED_STATUSES)
        },
        "requested_raw_root": raw_root.as_posix(),
        "synthetic_geometry_caveat": inventory.get("synthetic_geometry_caveat"),
        "records": records,
    }
    return report


def _error_report(message: str) -> dict[str, Any]:
    return {
        "report_schema_version": 1,
        "inventory_id": None,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "validation": {"passed": False, "errors": [message]},
        "summary": {status: 0 for status in sorted(ALLOWED_STATUSES)},
        "records": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory", type=Path, default=Path("data/sources/texas-p0-inventory.json")
    )
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Write the JSON report to this path instead of stdout. Generated reports "
            "carry a timestamp; keep them outside the repository."
        ),
    )
    args = parser.parse_args()
    try:
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        report = _error_report(f"inventory unreadable: {args.inventory}: {error}")
    except json.JSONDecodeError as error:
        report = _error_report(
            f"inventory is invalid JSON: {args.inventory}: {error.msg}"
        )
    else:
        if not isinstance(inventory, dict):
            report = _error_report(f"inventory must be a JSON object: {args.inventory}")
        else:
            report = build_report(inventory, args.raw_root)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.report is None:
        print(rendered, end="")
    else:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    return 0 if report["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

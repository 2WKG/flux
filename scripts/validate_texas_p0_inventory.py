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


def validate_inventory(inventory: dict[str, Any]) -> list[str]:
    """Return schema and honesty errors without reaching out to a provider."""
    errors: list[str] = []
    if inventory.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    caveat = inventory.get("synthetic_geometry_caveat", "").lower()
    if "synthetic" not in caveat or "not the real ercot" not in caveat:
        errors.append(
            "synthetic_geometry_caveat must say the topology is synthetic and not the real ERCOT network"
        )
    records = inventory.get("records")
    if not isinstance(records, list) or not records:
        return errors + ["records must be a non-empty list"]
    seen: set[str] = set()
    for index, record in enumerate(records):
        prefix = f"records[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing = REQUIRED_RECORD_FIELDS - record.keys()
        if missing:
            errors.append(f"{prefix} is missing {', '.join(sorted(missing))}")
            continue
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
        if not isinstance(record["artifacts"], list):
            errors.append(f"{prefix}.artifacts must be a list")
        if not isinstance(record["units"], dict) or not record["units"]:
            errors.append(f"{prefix}.units must be a non-empty object")
        if not isinstance(record["destinations"], list):
            errors.append(f"{prefix}.destinations must be a list")
        if record["status"] == "validated" and not any(
            artifact.get("immutable_id") for artifact in record["artifacts"]
        ):
            errors.append(
                f"{prefix}.validated record needs an immutable artifact identifier"
            )
    return errors


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
    """Match a validated record's declared hashes to its tracked receipt."""
    receipt_name = record.get("checked_in_receipt")
    if receipt_name is None:
        return None, []
    receipt_path = Path(receipt_name)
    if not receipt_path.is_file():
        return {"path": str(receipt_path), "passed": False}, [
            f"{record['id']} receipt is missing: {receipt_path}"
        ]
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return {"path": str(receipt_path), "passed": False}, [
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
        "path": str(receipt_path),
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
    errors = validate_inventory(inventory)
    records = []
    for record in inventory.get("records", []):
        runtime_artifacts = (
            _runtime_artifacts(record, raw_root) if isinstance(record, dict) else []
        )
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
        "requested_raw_root": str(raw_root),
        "synthetic_geometry_caveat": inventory.get("synthetic_geometry_caveat"),
        "records": records,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory", type=Path, default=Path("data/sources/texas-p0-inventory.json")
    )
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/texas-p0-inventory-validation-report.json"),
    )
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    report = build_report(inventory, args.raw_root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

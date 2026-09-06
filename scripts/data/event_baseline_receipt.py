"""Map an operational EAGLE-I acquisition receipt to contract provenance."""

from __future__ import annotations

from typing import Any


def eaglei_acquisition_from_operational_receipt(
    receipt: dict[str, Any],
    *,
    raw_artifact_uri: str,
    source_sidecar_uri: str,
    source_sidecar_sha256: str,
    filtered_artifact_uri: str,
) -> dict[str, Any]:
    """Preserve the completed annual-stream proof without copying raw artifacts."""
    required = (
        "acquisition_complete",
        "acquisition_method",
        "source_system_id",
        "source_file",
        "source_file_id",
        "source_file_bytes",
        "integrity_basis",
        "raw_sha256",
        "filtered_sha256",
    )
    missing = [field for field in required if receipt.get(field) in (None, "")]
    if missing or receipt.get("acquisition_complete") is not True:
        raise ValueError(
            f"operational receipt lacks completed acquisition proof: {missing}"
        )
    return {
        "acquisition_complete": True,
        "acquisition_method": receipt["acquisition_method"],
        "source_system_id": receipt["source_system_id"],
        "source_file": receipt["source_file"],
        "source_file_id": receipt["source_file_id"],
        "source_file_bytes": receipt["source_file_bytes"],
        "integrity_basis": receipt["integrity_basis"],
        "raw_artifact_uri": raw_artifact_uri,
        "raw_artifact_sha256": receipt["raw_sha256"],
        "source_sidecar_uri": source_sidecar_uri,
        "source_sidecar_sha256": source_sidecar_sha256,
        "filtered_artifact_uri": filtered_artifact_uri,
        "filtered_artifact_sha256": receipt["filtered_sha256"],
    }

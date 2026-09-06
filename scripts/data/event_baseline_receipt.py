"""Map an operational EAGLE-I acquisition receipt to contract provenance."""

from __future__ import annotations

from typing import Any


def eaglei_acquisition_from_operational_receipt(
    receipt: dict[str, Any],
    sidecar: dict[str, Any],
    *,
    raw_artifact_uri: str,
    source_sidecar_uri: str,
    source_sidecar_sha256: str,
    filtered_artifact_uri: str,
) -> dict[str, Any]:
    """Compose a selected-slice receipt with its verified annual sidecar."""
    for field in ("raw_sha256", "filtered_sha256"):
        if receipt.get(field) in (None, ""):
            raise ValueError(f"operational receipt lacks {field}")
    required = (
        "acquisition_complete",
        "acquisition_method",
        "source_system_id",
        "source_file",
        "source_file_id",
        "source_file_bytes",
        "integrity_basis",
        "raw_sha256",
    )
    missing = [field for field in required if sidecar.get(field) in (None, "")]
    if missing or sidecar.get("acquisition_complete") is not True:
        raise ValueError(f"annual sidecar lacks completed acquisition proof: {missing}")
    for field in ("raw_sha256", "source_system_id", "source_file", "source_file_id"):
        if (
            field in receipt
            and receipt[field] not in (None, "")
            and str(receipt[field]) != str(sidecar[field])
        ):
            raise ValueError(f"receipt and annual sidecar conflict on {field}")
    return {
        "acquisition_complete": True,
        "acquisition_method": sidecar["acquisition_method"],
        "source_system_id": sidecar["source_system_id"],
        "source_file": sidecar["source_file"],
        "source_file_id": sidecar["source_file_id"],
        "source_file_bytes": sidecar["source_file_bytes"],
        "integrity_basis": sidecar["integrity_basis"],
        "raw_artifact_uri": raw_artifact_uri,
        "raw_artifact_sha256": sidecar["raw_sha256"],
        "source_sidecar_uri": source_sidecar_uri,
        "source_sidecar_sha256": source_sidecar_sha256,
        "filtered_artifact_uri": filtered_artifact_uri,
        "filtered_artifact_sha256": receipt["filtered_sha256"],
    }

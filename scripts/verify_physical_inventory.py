"""Generate an honest, offline acceptance receipt for a physical inventory.

This is deliberately not an API or browser test.  It verifies only the
immutable source-artifact -> normalized inventory boundary from contract 11.
The receipt records every later end-to-end stage as ``NOT VERIFIED`` until the
owning API and renderer work supplies executable evidence.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# ``python scripts/verify_physical_inventory.py`` is a documented invocation;
# add the project root before importing the shared pipeline contract.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.physical_inventory import PhysicalInventoryError, validate_artifact

OFFLINE_STAGES = {
    "artifact_to_normalized_inventory": "VERIFIED",
    "spatial_api_transport": "NOT VERIFIED",
    "viewport_render": "NOT VERIFIED",
    "selection": "NOT VERIFIED",
    "inspector": "NOT VERIFIED",
    "browser_interaction": "NOT VERIFIED",
}


class AcceptanceError(ValueError):
    """The immutable inventory cannot support the proposed offline receipt."""


def _require_state(value: str) -> str:
    state = value.strip().lower()
    if not state or state != value.strip().lower() or not state.isalpha():
        raise AcceptanceError("state must be a lowercase alphabetic geography id")
    return state


def _state_scope_matches(value: str, state: str) -> bool:
    """Allow the canonical US-prefixed geography while retaining the state key."""
    candidate = value.lower()
    aliases = {state, f"us-{state}"}
    return any(
        candidate == alias or candidate.startswith(f"{alias}:") for alias in aliases
    )


def _coverage_by_class(
    artifact: dict[str, Any], state: str
) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in artifact["coverage"]:
        if _state_scope_matches(row["scope_id"], state):
            rows[row["asset_class"]].append(row)
    if not rows:
        raise AcceptanceError(f"artifact declares no coverage rows for {state}")
    return rows


def _is_authoritative_state_denominator(row: dict[str, Any], state: str) -> bool:
    """Recognize an explicit state-class denominator, never a source result count."""
    return (
        row["denominator_count"] is not None
        and row["denominator_basis"] == f"authoritative_state_class:{state}"
        and row["source_scope"] == f"statewide:{state}"
    )


REPO_ROOT = Path(__file__).resolve().parents[1]


def published_binding(published_artifact: Path) -> dict[str, str]:
    """Bind a receipt to the file actually published, by path and by digest.

    The path is recorded repository-relative so a receipt stays portable; a file
    outside the repository is refused rather than recorded as an absolute path.
    """
    resolved = published_artifact.resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise AcceptanceError(
            f"published artifact {published_artifact} is outside the repository; "
            "publish it under the repository before writing a receipt"
        ) from exc
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return {
        "published_path": relative.as_posix(),
        "published_compressed_sha256": digest.hexdigest(),
    }


def build_receipt(
    artifact: dict[str, Any],
    *,
    state: str,
    expected_version: str | None = None,
    published_artifact: Path | None = None,
) -> dict[str, Any]:
    """Verify contract-level parity and return an explicitly offline receipt.

    A class can be reported as offline-complete only when an authoritative,
    state-wide class denominator has been supplied.  A source query that
    returns N records is useful provenance but cannot become that denominator.
    """
    state = _require_state(state)
    try:
        validate_artifact(artifact)
    except PhysicalInventoryError as exc:
        raise AcceptanceError(f"invalid physical inventory artifact: {exc}") from exc
    geography = artifact["geography_id"].lower()
    if not _state_scope_matches(geography, state):
        raise AcceptanceError(
            f"artifact geography {artifact['geography_id']!r} does not match {state!r}"
        )
    if (
        expected_version is not None
        and artifact["artifact_version"] != expected_version
    ):
        raise AcceptanceError(
            f"artifact version {artifact['artifact_version']!r} does not match expected {expected_version!r}"
        )

    observed = Counter(asset["asset_class"] for asset in artifact["assets"])
    sourced_geometry = Counter(
        asset["asset_class"]
        for asset in artifact["assets"]
        if asset["geometry_status"] == "source"
    )
    unavailable_geometry = Counter(
        asset["asset_class"]
        for asset in artifact["assets"]
        if asset["geometry_status"] == "unavailable"
    )
    coverage = _coverage_by_class(artifact, state)
    classes: list[dict[str, Any]] = []
    errors: list[str] = []
    # Contract 11 already rejects fabricated metadata on unavailable geometry and
    # any CRS PROJ cannot resolve (validate_artifact above), so this verifier does
    # not restate those checks; it only adds the constraint the contract does not
    # make: a derived geometry must name the source it was derived from.
    for asset in artifact["assets"]:
        if (
            asset["geometry_status"] == "derived"
            and "source" not in asset["geometry_derivation_method"].casefold()
        ):
            errors.append(
                f"{asset['asset_id']}: derived geometry accuracy basis must name its source provenance"
            )
    for asset_class in sorted(coverage):
        # Contract forbids duplicate class/scope rows, but retain this guard if
        # the contract becomes additive in a future version.
        rows = coverage[asset_class]
        if len(rows) != 1:
            errors.append(f"{asset_class}: expected exactly one {state} coverage row")
            continue
        row = rows[0]
        actual = observed[asset_class]
        if row["observed_count"] != actual:
            errors.append(
                f"{asset_class}: coverage observed_count={row['observed_count']} but normalized assets={actual}"
            )
        authoritative = _is_authoritative_state_denominator(row, state)
        claimed_complete = row["status"] == "complete"
        if claimed_complete and not authoritative:
            errors.append(
                f"{asset_class}: complete is forbidden without authoritative_state_class:{state} and statewide:{state}"
            )
        if (
            authoritative
            and row["observed_count"] + (row["unavailable_count"] or 0)
            != row["denominator_count"]
        ):
            errors.append(
                f"{asset_class}: authoritative denominator must exactly equal observed plus unavailable"
            )
        geometry_ready = actual == sourced_geometry[asset_class]
        if claimed_complete and not geometry_ready:
            errors.append(
                f"{asset_class}: complete is forbidden while source geometry is absent or non-native"
            )
        classes.append(
            {
                "asset_class": asset_class,
                "normalized_asset_count": actual,
                "source_geometry_count": sourced_geometry[asset_class],
                "unavailable_geometry_count": unavailable_geometry[asset_class],
                "coverage_status": row["status"],
                "source_returned_count": row["observed_count"],
                "authoritative_state_class_denominator": row["denominator_count"]
                if authoritative
                else None,
                "denominator_evidence": "authoritative_state_class"
                if authoritative
                else "source_local_or_unknown",
                "source_scope": row["source_scope"],
                "unavailable_count": row["unavailable_count"],
                "unknown_or_unreported_count": row["unknown_count"],
                "reason": row["reason"],
            }
        )
    # No asset may silently disappear from coverage reporting.
    for asset_class in sorted(set(observed) - set(coverage)):
        errors.append(f"{asset_class}: normalized assets have no {state} coverage row")

    terminal_sources = {terminal["source_id"] for terminal in artifact["terminals"]}
    edge_sources = {edge["source_id"] for edge in artifact["connectivity_edges"]}
    binding = (
        {} if published_artifact is None else published_binding(published_artifact)
    )
    return {
        "receipt_kind": "physical_inventory_offline_acceptance",
        "receipt_version": "1.0.0",
        "state": state,
        "artifact": {
            **binding,
            "artifact_id": artifact["artifact_id"],
            "artifact_version": artifact["artifact_version"],
            "contract_version": artifact["contract_version"],
            "content_sha256": artifact["content_sha256"],
            "inventory_mode": artifact["inventory_mode"],
            "electrical_model_mode": artifact["electrical_model_mode"],
            "sources": [
                {
                    key: source[key]
                    for key in (
                        "source_id",
                        "authority",
                        "source_ref",
                        "source_version",
                        "content_sha256",
                    )
                }
                for source in artifact["sources"]
            ],
        },
        "offline_result": "VERIFIED" if not errors else "REJECTED",
        "coverage": classes,
        "connectivity": {
            "source_backed_terminal_count": len(artifact["terminals"]),
            "source_backed_edge_count": len(artifact["connectivity_edges"]),
            "terminal_source_ids": sorted(terminal_sources),
            "edge_source_ids": sorted(edge_sources),
        },
        "stages": OFFLINE_STAGES,
        "end_to_end_result": "NOT VERIFIED",
        "completion_claim": "No parent or state acceptance issue is complete from this offline receipt alone.",
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact", type=Path, required=True, help="canonical physical-inventory JSON"
    )
    parser.add_argument(
        "--state", required=True, help="artifact geography id, for example tx or mn"
    )
    parser.add_argument(
        "--expected-version", help="reject an unexpected semantic artifact version"
    )
    parser.add_argument(
        "--receipt", type=Path, required=True, help="output JSON receipt"
    )
    parser.add_argument(
        "--published-artifact",
        type=Path,
        help=(
            "the published (usually gzipped) file this receipt attests to; its "
            "repository-relative path and SHA-256 are written into the receipt"
        ),
    )
    args = parser.parse_args()
    try:
        if args.artifact.suffix == ".gz":
            with gzip.open(args.artifact, "rt", encoding="utf-8") as handle:
                artifact = json.load(handle)
        else:
            artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
        receipt = build_receipt(
            artifact,
            state=args.state,
            expected_version=args.expected_version,
            published_artifact=args.published_artifact,
        )
    except (OSError, json.JSONDecodeError, AcceptanceError) as exc:
        parser.error(str(exc))
    args.receipt.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if receipt["offline_result"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

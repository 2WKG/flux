"""Compose disjoint source artifacts into one truthful state inventory release."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

from pipelines.physical_inventory import (
    CONTRACT_VERSION,
    PhysicalInventoryError,
    artifact_sha256,
    validate_artifact,
)


class AssemblyError(PhysicalInventoryError):
    """Input artifacts cannot be composed without changing their meaning."""


def canonical_state_id(geography_id: str) -> str:
    """Resolve a documented state-qualified producer geography to its state key.

    Refuses any other geography rather than defaulting to the input string: an
    unrecognised producer geography must not become a state key by accident.
    """
    if re.fullmatch(r"[a-z]{2}", geography_id):
        return geography_id
    if re.fullmatch(r"us-[a-z]{2}", geography_id):
        return geography_id[3:]
    if re.fullmatch(r"[a-z]{2}:.+", geography_id):
        return geography_id[:2]
    raise AssemblyError(
        f"geography_id {geography_id!r} does not resolve to a state key; "
        "use 'us-<state>' or '<state>:<scope>'"
    )


def assemble_artifacts(
    artifacts: list[dict[str, Any]], *, release_version: str
) -> dict[str, Any]:
    """Return one release, retaining exact input-content digests as lineage.

    No counts are aggregated: coverage is a disjoint class/scope ledger, so a
    partial source cannot become a state-completeness claim during assembly.
    """
    if not artifacts:
        raise AssemblyError("at least one input artifact is required")
    for artifact in artifacts:
        validate_artifact(artifact)
    states = {canonical_state_id(artifact["geography_id"]) for artifact in artifacts}
    if len(states) != 1:
        raise AssemblyError(f"inputs do not resolve to one state: {sorted(states)!r}")
    modes = {
        (artifact["inventory_mode"], artifact["electrical_model_mode"])
        for artifact in artifacts
    }
    if len(modes) != 1:
        raise AssemblyError("inputs must share inventory and electrical model modes")
    if not isinstance(release_version, str) or not release_version:
        raise AssemblyError("release_version is required")
    state = next(iter(states))
    source_by_id: dict[str, dict[str, Any]] = {}
    collections = {"assets": set(), "terminals": set(), "connectivity_edges": set()}
    coverage_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    result: dict[str, Any] = {
        "artifact_id": f"{state}:physical-inventory:{release_version}",
        "contract_version": CONTRACT_VERSION,
        "geography_id": state,
        "artifact_version": release_version,
        "inventory_mode": artifacts[0]["inventory_mode"],
        "electrical_model_mode": artifacts[0]["electrical_model_mode"],
        "created_at": max(artifact["created_at"] for artifact in artifacts),
        "content_sha256": "0" * 64,
        "input_artifact_sha256s": sorted(
            artifact["content_sha256"] for artifact in artifacts
        ),
        "sources": [],
        "assets": [],
        "terminals": [],
        "connectivity_edges": [],
        "coverage": [],
    }
    if len(result["input_artifact_sha256s"]) != len(
        set(result["input_artifact_sha256s"])
    ):
        raise AssemblyError("input artifact content digests must be distinct")
    for artifact in sorted(artifacts, key=lambda item: item["content_sha256"]):
        for source in artifact["sources"]:
            previous = source_by_id.get(source["source_id"])
            if previous is None:
                source_by_id[source["source_id"]] = source
            elif previous != source:
                raise AssemblyError(
                    f"source_id {source['source_id']!r} has conflicting source content"
                )
        for name, key_name in (
            ("assets", "asset_id"),
            ("terminals", "terminal_id"),
            ("connectivity_edges", "edge_id"),
        ):
            for item in artifact[name]:
                if item[key_name] in collections[name]:
                    raise AssemblyError(
                        f"duplicate {name[:-1]} identity {item[key_name]!r}"
                    )
                collections[name].add(item[key_name])
                result[name].append(item)
        for row in artifact["coverage"]:
            key = (row["asset_class"], row["scope_id"])
            previous = coverage_by_key.get(key)
            if previous is None:
                coverage_by_key[key] = row
                result["coverage"].append(row)
            elif previous != row:
                raise AssemblyError(f"conflicting coverage class/scope {key!r}")
    result["sources"] = [source_by_id[key] for key in sorted(source_by_id)]
    for name, key_name in (
        ("assets", "asset_id"),
        ("terminals", "terminal_id"),
        ("connectivity_edges", "edge_id"),
    ):
        result[name].sort(key=lambda item: item[key_name])
    result["coverage"].sort(key=lambda item: (item["asset_class"], item["scope_id"]))
    result["content_sha256"] = artifact_sha256(result)
    return validate_artifact(result)


def read_artifact(path: Path) -> dict[str, Any]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def write_assembly(artifact: dict[str, Any], path: Path) -> Path:
    """Write canonical JSON; callers choose a tracked receipt or ignored bulk path."""
    validate_artifact(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path

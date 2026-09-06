"""Validate the shared 3D asset archetype catalog against its contract.

The contract is only real if a machine can check it. This refuses a catalog that
would let the eighteen models import inconsistently: a drifting unit or axis, a
pivot that is not on the ground, an LOD chain that does not actually reduce, a
budget nobody can meet, a connector role the runtime does not know, or a status
material bound to a label no server asserts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data/3d/asset-archetypes-v1.json"
RUNTIME_ASSET_ROOT = Path("web/public/assets/flux-grid")
PUBLISHED_RELEASE_RECEIPT = Path(
    "data/3d/packs/flux-grid-v1/releases/flux-grid-runtime-v1-20260906.json"
)
PUBLISHED_RUNTIME_INVENTORY = Path(
    "data/3d/packs/flux-grid-v1/releases/flux-grid-runtime-v1-20260906.inventory.json"
)
PUBLISHED_RUNTIME_RELEASE = {
    "release_tag": "flux-grid-runtime-v1-20260906",
    "asset_filename": "flux-grid-runtime-v1-20260906T103700Z.zip",
    "archive_sha256": "44ed49bd7e2a8392765825fdfc164e01061e7701befd8b89eaf38ac9ecc45d78",
    "runtime_manifest_sha256": "068ca96a44b9730f3d59ab55c454cf5a8959b285db62625bbd2bcad57afd067b",
    "release_contents": {"archetypes": 18, "glb_files": 54, "preview_png_files": 18},
}

CONTRACT_ID = "flux:3d-asset-archetypes:v1"
EXPECTED_ARCHETYPES = 18
# Labels the server actually asserts. "illustrative" is deliberately absent: the
# narrative-IA contract removed it because nothing on master produces it.
ALLOWED_LABELS = {
    "source_supported",
    "source_screened",
    "hypothetical",
    "synthetic",
    "unavailable",
    "request_failed",
}
CONNECTOR_ROLES = {"HV_IN", "HV_OUT", "MV_FEED", "NONE"}
CATEGORIES = {"network", "generation", "storage", "load", "critical_load"}
ARCHETYPE_FIELDS = {
    "id",
    "semantic_name",
    "category",
    "texas_issue",
    "minnesota_issue",
    "footprint_m",
    "connectors",
    "lod_triangles",
    "limit",
}
LOD1_MAX_SHARE = 0.40
LOD2_MAX_SHARE = 0.12

# Scan both the source and browser trees for diagnostics. The committed runtime
# pack is checked separately by tests/test_asset_archetypes.py against catalog
# identities; this report remains a working-tree inventory and intentionally
# includes unexpected local binaries.
MODEL_SEARCH_DIRS = ("data", "web")
MODEL_SUFFIXES = (".glb", ".gltf")
# Never walked: vendored, built or generated trees are not deliverables. The
# skip set exists to keep a developer's local build output from reading as a
# committed binary, so every entry must be something git already ignores —
# otherwise the walk would exempt a path a reviewer really could commit.
#
# That is why the anchored entries are matched by REPO-RELATIVE PATH and not by
# bare directory name. The .gitignore rules they mirror are anchored to `web/`
# and `data/`; a bare-name prune matches at any depth, so `data/test-results/`
# — which git tracks happily — would have been silently exempt. Missing one of
# these is not cosmetic in either direction: since the runtime pack landed, any
# .glb the walk finds outside web/public/assets/flux-grid is reported as an
# unverified binary, so an unskipped build directory turns a developer's suite
# red on their own harness build, while CI, which never writes one in the pytest
# job, stays green. web/dist-harness and web/dist-renderer-harness did exactly
# that: they are written by `npm run build:harness` and
# `npm run build:renderer-harness` (and therefore by
# `node --test web/test/renderer-artifact.test.mjs`), neither is named "dist",
# and neither was skipped.
#
# tests/test_asset_archetypes.py holds both halves against reality: the walk is
# proved to still report data/test-results/stray.glb, and every entry below is
# proved git-ignored with `git check-ignore` so the two can never drift apart.
_SKIP_PATHS = frozenset(
    {
        "web/dist",
        "web/dist-harness",
        "web/dist-renderer-harness",
        "web/test-results",
        "web/playwright-report",
        "data/parquet",
    }
)
# Names git ignores at ANY depth: `node_modules/`, `build/`, `.venv/` and
# `__pycache__/` carry no slash before their trailing one, so they are not
# anchored. `.git` is never a deliverable and is not walked either.
_SKIP_NAMES = frozenset(
    {
        "node_modules",
        "build",
        ".venv",
        "__pycache__",
        ".git",
    }
)
_SAFE_RUNTIME_GLB = re.compile(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+\.glb$")


def find_model_files(root: Path = ROOT) -> list[str]:
    """Return every committed-tree glTF binary, repo-relative and sorted.

    This is the honest answer to "has a .glb crept in?". It is derived, not
    declared: build_report reports what this finds, so the report goes true the
    moment a model appears.
    """
    found: list[str] = []
    for rel in MODEL_SEARCH_DIRS:
        base = root / rel
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            rel_dir = Path(dirpath).relative_to(root).as_posix()
            dirnames[:] = [
                d
                for d in dirnames
                if d not in _SKIP_NAMES and f"{rel_dir}/{d}" not in _SKIP_PATHS
            ]
            for name in filenames:
                if name.endswith(MODEL_SUFFIXES):
                    path = Path(dirpath, name)
                    found.append(path.relative_to(root).as_posix())
    return sorted(found)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is unreadable JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return None
    return value


def validate_published_runtime(root: Path, catalog: dict[str, Any]) -> list[str]:
    """Validate the one reviewed location where tracked runtime GLBs may live.

    Source kits and the historical source-only pack never authorize a binary.
    The published-release receipt and its per-file inventory are the authority
    for the same-origin runtime copy committed by PR #332.
    """
    errors: list[str] = []
    receipt = _read_json(
        root / PUBLISHED_RELEASE_RECEIPT, "published runtime receipt", errors
    )
    inventory = _read_json(
        root / PUBLISHED_RUNTIME_INVENTORY, "published runtime inventory", errors
    )
    catalog_path = root / "data/3d/asset-archetypes-v1.json"

    if receipt is not None:
        # Publication metadata is maintained separately from the installed-byte
        # contract. This guard only consumes the immutable fields shared by both
        # receipt states; the manifest and inventory below bind actual runtime
        # files to the verified archive.
        for field, expected in PUBLISHED_RUNTIME_RELEASE.items():
            if receipt.get(field) != expected:
                errors.append(f"published runtime receipt does not pin {field}")
        source = receipt.get("source_contract")
        if (
            not isinstance(source, dict)
            or source.get("file") != "data/3d/asset-archetypes-v1.json"
        ):
            errors.append("published runtime receipt does not pin the source catalog")
        elif not catalog_path.is_file() or source.get("sha256") != _sha256(
            catalog_path
        ):
            errors.append(
                "published runtime receipt source catalog hash does not match"
            )

    expected_ids = {
        entry.get("id")
        for entry in catalog.get("archetypes", [])
        if isinstance(entry, dict)
    }
    expected_paths = {
        f"{asset_id}/{asset_id}{suffix}"
        for asset_id in expected_ids
        if isinstance(asset_id, str)
        for suffix in (".glb", ".lod1.glb", ".lod2.glb")
    }
    if len(expected_paths) != EXPECTED_ARCHETYPES * 3:
        errors.append("catalog cannot define the published runtime path set")

    pinned: dict[str, dict[str, Any]] = {}
    if inventory is not None:
        if (
            inventory.get("schema_version") != 1
            or inventory.get("release_tag") != PUBLISHED_RUNTIME_RELEASE["release_tag"]
            or inventory.get("archive_sha256")
            != PUBLISHED_RUNTIME_RELEASE["archive_sha256"]
            or inventory.get("runtime_manifest_sha256")
            != PUBLISHED_RUNTIME_RELEASE["runtime_manifest_sha256"]
        ):
            errors.append(
                "published runtime inventory is not bound to the verified release"
            )
        files = inventory.get("files")
        if not isinstance(files, list):
            errors.append("published runtime inventory files must be a list")
        else:
            for entry in files:
                if not isinstance(entry, dict):
                    errors.append(
                        "published runtime inventory has a non-object file entry"
                    )
                    continue
                path = entry.get("path")
                digest = entry.get("sha256")
                size = entry.get("bytes")
                if not isinstance(path, str) or not _SAFE_RUNTIME_GLB.fullmatch(path):
                    errors.append("published runtime inventory has an unsafe GLB path")
                    continue
                if path in pinned:
                    errors.append(f"published runtime inventory duplicates {path}")
                    continue
                if not isinstance(digest, str) or not re.fullmatch(
                    r"[a-f0-9]{64}", digest
                ):
                    errors.append(
                        f"published runtime inventory has an invalid digest for {path}"
                    )
                    continue
                if not isinstance(size, int) or size <= 0:
                    errors.append(
                        f"published runtime inventory has an invalid byte size for {path}"
                    )
                    continue
                pinned[path] = entry
            if set(pinned) != expected_paths:
                errors.append(
                    "published runtime inventory does not pin exactly the 54 expected GLBs"
                )

    runtime_manifest = root / RUNTIME_ASSET_ROOT / "manifest.json"
    if not runtime_manifest.is_file():
        errors.append("published runtime manifest is missing from the runtime location")
    elif (
        _sha256(runtime_manifest)
        != PUBLISHED_RUNTIME_RELEASE["runtime_manifest_sha256"]
    ):
        errors.append(
            "published runtime manifest digest does not match the verified release"
        )

    actual_models = set(find_model_files(root))
    runtime_prefix = f"{RUNTIME_ASSET_ROOT.as_posix()}/"
    allowed_models = {f"{runtime_prefix}{path}" for path in expected_paths}
    unexpected = sorted(actual_models - allowed_models)
    missing = sorted(allowed_models - actual_models)
    if unexpected:
        errors.append(
            f"unverified model binary outside published runtime location: {unexpected}"
        )
    if missing:
        errors.append(f"published runtime is missing pinned model binaries: {missing}")
    for relative, entry in pinned.items():
        path = root / RUNTIME_ASSET_ROOT / relative
        if not path.is_file():
            continue
        if path.stat().st_size != entry["bytes"]:
            errors.append(
                f"published runtime byte size does not match inventory: {relative}"
            )
        if _sha256(path) != entry["sha256"]:
            errors.append(
                f"published runtime digest does not match inventory: {relative}"
            )
    return errors


def _issue_key(value: object) -> bool:
    return isinstance(value, str) and value.startswith("2WKG-") and value[5:].isdigit()


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    """Return every contract violation; an empty list means the catalog conforms."""
    errors: list[str] = []

    if catalog.get("schemaVersion") != 1 or catalog.get("contractId") != CONTRACT_ID:
        errors.append(f"catalog identity must be schemaVersion 1 and {CONTRACT_ID}")

    transform = catalog.get("transform", {})
    if transform.get("lengthUnit") != "meter" or transform.get("unitScale") != 1.0:
        errors.append("transform must declare metres at unit scale 1.0")
    if transform.get("upAxis") != "Y" or transform.get("forwardAxis") != "-Z":
        errors.append("transform must declare Y up and -Z forward")
    if transform.get("pivot") != "ground_center":
        errors.append("pivot must be ground_center so models sit on terrain")

    materials = catalog.get("statusMaterials", {})
    labels = set(materials.get("allowedLabels", []))
    if labels != ALLOWED_LABELS:
        errors.append(
            "status materials must bind exactly the server-asserted labels "
            f"{sorted(ALLOWED_LABELS)}"
        )
    if not materials.get("slotName"):
        errors.append("status materials must name the shared material slot")

    budgets = catalog.get("budgets", {})
    for key in (
        "perArchetypeTrianglesLod0",
        "perArchetypeFileBytes",
        "textureMaxPixels",
    ):
        if not isinstance(budgets.get(key), int) or budgets[key] <= 0:
            errors.append(f"budgets.{key} must be a positive integer")

    archetypes = catalog.get("archetypes")
    if not isinstance(archetypes, list) or len(archetypes) != EXPECTED_ARCHETYPES:
        errors.append(f"catalog must define exactly {EXPECTED_ARCHETYPES} archetypes")
        return errors

    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    seen_issues: set[str] = set()
    lod0_cap = budgets.get("perArchetypeTrianglesLod0", 0)

    for entry in archetypes:
        label = entry.get("id", "<missing id>")
        if set(entry) != ARCHETYPE_FIELDS:
            errors.append(f"{label}: fields must be exactly {sorted(ARCHETYPE_FIELDS)}")
            continue
        if entry["id"] in seen_ids:
            errors.append(f"{label}: duplicate archetype id")
        seen_ids.add(entry["id"])
        if entry["semantic_name"] in seen_names:
            errors.append(f"{label}: duplicate semantic name")
        seen_names.add(entry["semantic_name"])
        if entry["category"] not in CATEGORIES:
            errors.append(f"{label}: category must be one of {sorted(CATEGORIES)}")

        # Each archetype is claimed by exactly one Texas and one Minnesota work
        # item, and no work item may be claimed twice.
        for key in ("texas_issue", "minnesota_issue"):
            if not _issue_key(entry[key]):
                errors.append(f"{label}: {key} must be a 2WKG-NNN key")
            elif entry[key] in seen_issues:
                errors.append(f"{label}: {key} {entry[key]} is claimed twice")
            else:
                seen_issues.add(entry[key])

        footprint = entry["footprint_m"]
        if set(footprint) != {"length", "width"} or not all(
            isinstance(value, (int, float)) and value > 0
            for value in footprint.values()
        ):
            errors.append(f"{label}: footprint_m needs positive length and width")

        connectors = entry["connectors"]
        if not isinstance(connectors, list) or not connectors:
            errors.append(f"{label}: connectors must be a non-empty list")
        elif unknown := sorted(set(connectors) - CONNECTOR_ROLES):
            errors.append(f"{label}: unknown connector role(s) {unknown}")
        elif len(set(connectors)) != len(connectors):
            errors.append(f"{label}: duplicate connector role")
        elif "NONE" in connectors and len(connectors) > 1:
            errors.append(f"{label}: NONE cannot be combined with a real connector")

        lod = entry["lod_triangles"]
        if set(lod) != {"lod0", "lod1", "lod2"} or not all(
            isinstance(value, int) and value > 0 for value in lod.values()
        ):
            errors.append(f"{label}: lod_triangles needs positive lod0, lod1, lod2")
        else:
            if lod["lod0"] > lod0_cap:
                errors.append(f"{label}: lod0 {lod['lod0']} exceeds budget {lod0_cap}")
            if lod["lod1"] > lod["lod0"] * LOD1_MAX_SHARE:
                errors.append(f"{label}: lod1 must be <= {LOD1_MAX_SHARE:.0%} of lod0")
            if lod["lod2"] > lod["lod0"] * LOD2_MAX_SHARE:
                errors.append(f"{label}: lod2 must be <= {LOD2_MAX_SHARE:.0%} of lod0")

        if not entry["limit"].strip():
            errors.append(f"{label}: limit must state what the model does not assert")

    return errors


def build_report(catalog: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    errors = validate_catalog(catalog)
    model_files = find_model_files(root)
    archetypes = catalog.get("archetypes", [])
    categories: dict[str, int] = {}
    for entry in archetypes:
        if isinstance(entry, dict) and isinstance(entry.get("category"), str):
            categories[entry["category"]] = categories.get(entry["category"], 0) + 1
    return {
        "contractId": catalog.get("contractId"),
        "schemaVersion": catalog.get("schemaVersion"),
        "archetypeCount": len(archetypes),
        "categories": dict(sorted(categories.items())),
        "validation": {"passed": not errors, "errors": errors},
        "modelFilesPresent": bool(model_files),
        "modelFiles": model_files,
        "modelFilesNote": "modelFilesPresent is derived: data/ and web/ are walked for .glb/.gltf and every hit is listed in modelFiles. The checked-in Flux grid runtime pack is validated separately against catalog identities; this report also exposes unexpected local binaries.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    report = build_report(catalog)
    print(json.dumps(report, indent=2))
    return 0 if report["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

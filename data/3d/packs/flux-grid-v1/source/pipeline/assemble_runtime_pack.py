"""Assemble a checksum-pinned browser package from a successfully audited build.

The repository deliberately keeps generated GLBs out of Git.  This program is
the delivery boundary: it accepts only a complete independent audit, copies the
54 models, previews, and the already-rasterized symbol sprite into a portable
runtime directory, then writes the manifest and exact inventory consumed by a
renderer or installer.

Run after ``build_pack.py`` and ``validation/validate_pack.py``.  ``--symbols``
must contain ``flux-grid.png``, ``flux-grid@2x.png``, the two sprite JSON files,
and ``deck-icon-mapping.json``.  It is intentionally a local artifact writer,
not a Git writer.

The audit is **not** a detached token.  ``--audit`` is only a claim about a
specific set of bytes, so before anything is copied every GLB, metadata record
and preview named by the audit is re-hashed out of ``--build`` and compared with
the ``sha256``/``bytes`` the audit recorded for it, and the audit's
``contract_id`` is compared with the catalog.  Any mismatch is refused by file
name.  The same binding is re-run against the copied tree, so the manifest can
only ever describe bytes that the audit actually measured.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
PACK = HERE.parents[2]
REPOSITORY = HERE.parents[6]
DEFAULT_CATALOG = REPOSITORY / "data/3d/asset-archetypes-v1.json"
SYMBOL_FILES = (
    "flux-grid.png",
    "flux-grid@2x.png",
    "flux-grid.json",
    "flux-grid@2x.json",
    "deck-icon-mapping.json",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ValueError(f"output already exists: {destination}")
    shutil.copytree(source, destination)


def bind_file(path: Path, audited: dict[str, Any]) -> None:
    """Refuse unless ``path`` is exactly the bytes the audit recorded for it.

    The audit report carries a ``sha256`` (and, for GLBs, a ``bytes``) for every
    file it measured.  Re-deriving them here is what turns ``--audit`` from a
    detached token into a statement about ``--build``: a model replaced after the
    audit ran is named and rejected instead of being packaged and pinned.
    """
    if not path.is_file():
        raise ValueError(f"audited file is missing from the build: {path}")
    expected = audited.get("sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"audit records no usable sha256 for {path}")
    actual = digest(path)
    if actual != expected:
        raise ValueError(
            f"build bytes do not match the audit for {path}: "
            f"audit {expected}, build {actual}"
        )
    size = audited.get("bytes")
    if size is not None and path.stat().st_size != size:
        raise ValueError(
            f"build size does not match the audit for {path}: "
            f"audit {size}, build {path.stat().st_size}"
        )


def bind_audit(root: Path, audit: dict[str, Any], catalog: dict[str, Any]) -> None:
    """Bind every digest in ``audit`` to the bytes under ``root``/assets."""
    contract = catalog["contractId"]
    if audit.get("contract_id") != contract:
        raise ValueError(
            "audit was produced against a different contract: "
            f"audit {audit.get('contract_id')!r}, catalog {contract!r}"
        )
    known = {entry["id"] for entry in catalog["archetypes"]}
    for audited in audit["assets"]:
        asset_id = audited["archetype_id"]
        if asset_id not in known:
            raise ValueError(
                f"audit names an archetype the catalog does not: {asset_id}"
            )
        folder = root / "assets" / asset_id
        for lod in range(3):
            suffix = "" if lod == 0 else f".lod{lod}"
            bind_file(folder / f"{asset_id}{suffix}.glb", audited["lods"][f"lod{lod}"])
        bind_file(folder / f"{asset_id}.meta.json", audited["metadata"])
        bind_file(folder / f"{asset_id}.preview.png", audited["preview"])


def file_record(
    path: Path, relative: str, triangles: int | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": relative,
        "sha256": digest(path),
        "bytes": path.stat().st_size,
    }
    if triangles is not None:
        result["triangles"] = triangles
    return result


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_manifest(
    root: Path, audit: dict[str, Any], catalog: dict[str, Any]
) -> dict[str, Any]:
    by_id = {entry["id"]: entry for entry in catalog["archetypes"]}
    assets = []
    for audited in audit["assets"]:
        asset_id = audited["archetype_id"]
        entry = by_id[asset_id]
        folder = root / "assets" / asset_id
        lods = {}
        for lod in range(3):
            suffix = "" if lod == 0 else f".lod{lod}"
            filename = f"{asset_id}{suffix}.glb"
            lods[f"lod{lod}"] = file_record(
                folder / filename,
                f"{asset_id}/{filename}",
                audited["lods"][f"lod{lod}"]["triangles"],
            )
        meta = load_json(folder / f"{asset_id}.meta.json")
        assets.append(
            {
                "archetype_id": asset_id,
                "semantic_name": entry["semantic_name"],
                "category": entry["category"],
                "footprint_m": entry["footprint_m"],
                "lods": lods,
                "preview": f"{asset_id}/{asset_id}.preview.png",
                "metadata": f"{asset_id}/{asset_id}.meta.json",
                "bounds_m": meta["bounds_m"],
                "source_of_shape": meta["source_of_shape"],
                "license": meta["license"],
            }
        )
    symbols = root / "assets" / "symbols"
    return {
        "schema_version": 1,
        "contract_id": catalog["contractId"],
        "package_name": "flux-grid-assets-runtime",
        "completion": "complete_locally_generated",
        "transform": {
            "unit": "meter",
            "up": "Y",
            "forward": "-Z",
            "pivot": "ground_center",
        },
        "runtime_base_url": "/assets/flux-grid/",
        "status_material": "MAT_STATUS",
        "status_labels": [
            "source_supported",
            "source_screened",
            "hypothetical",
            "synthetic",
            "unavailable",
            "request_failed",
        ],
        "lod_zoom_defaults": {
            "symbol": [0, 12],
            "lod2": [12, 15],
            "lod1": [15, 17],
            "lod0": [17, 24],
        },
        "symbols": {
            "atlas": file_record(
                symbols / "flux-grid@2x.png", "symbols/flux-grid@2x.png"
            ),
            "mapping": file_record(
                symbols / "deck-icon-mapping.json", "symbols/deck-icon-mapping.json"
            ),
            "maplibre_sprite": "symbols/flux-grid",
        },
        "assets": assets,
        "verification": {
            "audit": "validation/independent-audit.json",
            "asset_count": len(assets),
            "asset_count_passed": audit["asset_count_passed"],
            "complete_pack": audit["complete_pack"],
            "note": "Generated locally from tracked procedural source. This package is reusable geometry only; placements still require accepted server artifacts.",
        },
    }


def write_inventory(root: Path) -> None:
    files = [root / "manifest.json"] + sorted(
        path for path in (root / "assets").rglob("*") if path.is_file()
    )
    lines = [f"{digest(path)}  {path.relative_to(root).as_posix()}" for path in files]
    (root / "package.SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_zip(root: Path, path: Path) -> None:
    if path.exists():
        raise ValueError(f"archive already exists: {path}")
    with zipfile.ZipFile(
        path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for item in sorted(path for path in root.rglob("*") if path.is_file()):
            archive.write(item, Path(root.name) / item.relative_to(root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build",
        type=Path,
        required=True,
        help="Complete build directory from build_pack.py",
    )
    parser.add_argument(
        "--audit", type=Path, required=True, help="Passing independent-audit.json"
    )
    parser.add_argument(
        "--symbols", type=Path, required=True, help="Rasterized symbol sprite directory"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New runtime package directory"
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--zip", type=Path, help="Optional new portable zip output")
    args = parser.parse_args(argv)
    audit, catalog = load_json(args.audit), load_json(args.catalog)
    archetypes = len(catalog["archetypes"])
    if (
        not audit.get("passed")
        or not audit.get("complete_pack")
        or audit.get("asset_count_passed") != archetypes
    ):
        raise ValueError("refusing incomplete or failing independent audit")
    if args.output.exists():
        raise ValueError(f"output already exists: {args.output}")
    expected = args.build / "assets"
    if not expected.is_dir():
        raise ValueError(f"build has no assets directory: {expected}")
    # Refuse before writing anything: an audit that does not describe this build
    # must not leave a half-assembled package behind.
    bind_audit(args.build, audit, catalog)
    copy_tree(expected, args.output / "assets")
    bind_audit(args.output, audit, catalog)
    symbol_out = args.output / "assets" / "symbols"
    symbol_out.mkdir()
    for filename in SYMBOL_FILES:
        source = args.symbols / filename
        if not source.is_file():
            raise ValueError(f"missing rasterized symbol runtime file: {source}")
        shutil.copy2(source, symbol_out / filename)
    (args.output / "validation").mkdir()
    shutil.copy2(args.audit, args.output / "validation" / "independent-audit.json")
    manifest = build_manifest(args.output, audit, catalog)
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    write_inventory(args.output)
    if args.zip:
        write_zip(args.output, args.zip)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "models": sum(len(asset["lods"]) for asset in manifest["assets"]),
                "assets": len(manifest["assets"]),
                "manifest": digest(args.output / "manifest.json"),
                "zip": str(args.zip) if args.zip else None,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

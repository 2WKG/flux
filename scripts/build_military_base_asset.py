"""Build the neutral military-base archetype delivery without committing binaries."""

from __future__ import annotations

import argparse
import json
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.asset_contract_lib import (
    CATALOG_PATH,
    ROOT,
    AssetContractError,
    catalog_entry,
    connector_roles,
    file_size_errors,
    glb_bytes,
    load_catalog,
    load_json,
    png_bytes,
    preview_pixels,
    require,
    required_filenames,
    triangle_budget_errors,
)

ARCHETYPE_ID = "military_base"
REQUEST = ROOT / "data/3d/requests/minnesota-military-base-v1.json"
# Deliveries never default into the working tree: the contract forbids committing
# binaries, so an argument-free run writes to the system temp directory instead.
DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "flux-3d" / ARCHETYPE_ID
# Authored massing height. Width and length are read from the request footprint.
HEIGHT_M = 24.0
# Faces of the ground-centred box, wound outward.
FACES = [
    0,
    1,
    2,
    0,
    2,
    3,
    4,
    6,
    5,
    4,
    7,
    6,
    0,
    4,
    5,
    0,
    5,
    1,
    1,
    5,
    6,
    1,
    6,
    2,
    2,
    6,
    7,
    2,
    7,
    3,
    3,
    7,
    4,
    3,
    4,
    0,
]


def _checked_model(request: Any, catalog: dict[str, Any]) -> tuple[dict, dict]:
    """Bind the request to the catalog. A contradiction is a named error, not a default."""
    model = require(request, "model", "request")
    archetype_id = require(model, "archetype_id", "request.model")
    if archetype_id != ARCHETYPE_ID:
        raise AssetContractError(
            "archetype_id_unexpected", f"{archetype_id} != {ARCHETYPE_ID}"
        )
    entry = catalog_entry(catalog, archetype_id)
    contract_id = require(model, "contract_id", "request.model")
    if contract_id != catalog.get("contractId"):
        raise AssetContractError(
            "contract_id_mismatch", f"{contract_id} != {catalog.get('contractId')}"
        )
    for field in ("footprint_m", "connectors", "lod_triangles"):
        value = require(model, field, "request.model")
        expected = require(entry, field, f"catalog.{archetype_id}")
        if value != expected:
            raise AssetContractError(
                f"{field}_contradicts_catalog", f"{value!r} != {expected!r}"
            )
    roles = connector_roles(catalog)
    for role in model["connectors"]:
        if role not in roles:
            raise AssetContractError("unknown_connector_role", str(role))
    return model, entry


def _box(footprint: Any) -> tuple[list[tuple[float, float, float]], float, float]:
    width = require(footprint, "width", "request.model.footprint_m")
    length = require(footprint, "length", "request.model.footprint_m")
    if not isinstance(width, (int, float)) or not isinstance(length, (int, float)):
        raise AssetContractError("footprint_not_numeric", f"{width!r} x {length!r}")
    if width <= 0 or length <= 0:
        raise AssetContractError("footprint_not_positive", f"{width} x {length}")
    x, z = float(width) / 2, float(length) / 2
    vertices = [
        (-x, 0.0, -z),
        (x, 0.0, -z),
        (x, 0.0, z),
        (-x, 0.0, z),
        (-x, HEIGHT_M, -z),
        (x, HEIGHT_M, -z),
        (x, HEIGHT_M, z),
        (-x, HEIGHT_M, z),
    ]
    return vertices, x, z


def _document(model: dict[str, Any], vertices, x: float, z: float, sizes) -> dict:
    positions_bytes, index_bytes = sizes
    return {
        "asset": {
            "version": "2.0",
            "generator": "Flux military-base archetype builder",
        },
        "extras": {
            "archetype_id": model["archetype_id"],
            "contract_id": model["contract_id"],
            "axis": {"up": "Y", "forward": "-Z"},
            "pivot": "ground_center",
        },
        "buffers": [{"byteLength": positions_bytes + index_bytes}],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": positions_bytes,
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": positions_bytes,
                "byteLength": index_bytes,
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(vertices),
                "type": "VEC3",
                "min": [-x, 0.0, -z],
                "max": [x, HEIGHT_M, z],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": len(FACES),
                "type": "SCALAR",
            },
        ],
        "materials": [
            {
                "name": "MAT_STATUS",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.5, 0.5, 0.5, 1],
                    "metallicFactor": 0,
                    "roughnessFactor": 0.8,
                },
            }
        ],
        "meshes": [
            {
                "name": f"{ARCHETYPE_ID}_lod0",
                "primitives": [
                    {"attributes": {"POSITION": 0}, "indices": 1, "material": 0}
                ],
            }
        ],
        "nodes": [
            {"name": ARCHETYPE_ID, "mesh": 0},
            {
                "name": f"CONN_{model['connectors'][0]}_0",
                "translation": [0, 0, -z],
            },
        ],
        "scenes": [{"nodes": [0, 1]}],
        "scene": 0,
    }


def _preview(size: int) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            inside = size // 6 < x < size * 5 // 6 and size // 4 < y < size * 3 // 4
            row.extend((83, 101, 119) if inside else (230, 235, 240))
        rows.append(bytes(row))
    return png_bytes(size, size, b"".join(rows), 2)


def build(
    output: Path,
    request_path: Path = REQUEST,
    catalog_path: Path = CATALOG_PATH,
) -> dict[str, Any]:
    """Produce the delivery in memory, then write it. A failure leaves nothing behind."""
    catalog = load_catalog(catalog_path)
    request = load_json(request_path, "request")
    model, _entry = _checked_model(request, catalog)

    vertices, x, z = _box(model["footprint_m"])
    positions = b"".join(struct.pack("<fff", *vertex) for vertex in vertices)
    index_data = struct.pack("<" + "H" * len(FACES), *FACES)
    document = _document(model, vertices, x, z, (len(positions), len(index_data)))
    glb = glb_bytes(document, positions + index_data)
    preview = _preview(preview_pixels(catalog))

    triangles = len(FACES) // 3
    metadata = {
        "archetype_id": model["archetype_id"],
        "contract_id": model["contract_id"],
        "triangles_lod0": triangles,
        "triangles_lod1": None,
        "triangles_lod2": None,
        "lod_chain_status": (
            "lod1 and lod2 are not produced by this builder; null means not produced, "
            "not a measured zero. The reducing chain is 2WKG-374's work item."
        ),
        "footprint_m": model["footprint_m"],
        "connectors": model["connectors"],
        "author": "Flux hackathon team",
        "license": "CC0-1.0",
        "source_of_shape": "Original generic rectangular installation silhouette; no real facility geometry or identity.",
        "status_material": "MAT_STATUS",
        "limits": (
            "Generic non-geographic archetype only; it asserts no real facility, "
            "perimeter, or asset disposition."
        ),
    }

    names = _delivery_names(catalog)
    payloads = {
        names["glb"]: glb,
        names["preview"]: preview,
        names["meta"]: _meta_bytes(metadata),
    }
    errors = triangle_budget_errors(
        {
            "lod0": metadata["triangles_lod0"],
            "lod1": metadata["triangles_lod1"],
            "lod2": metadata["triangles_lod2"],
        },
        catalog,
    )
    for name, payload in payloads.items():
        errors.extend(file_size_errors(len(payload), catalog, name))
    errors.extend(_footprint_fit_errors(document, model["footprint_m"], catalog))
    if errors:
        raise AssetContractError("delivery_violates_contract", "; ".join(errors))

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output / name).write_bytes(payload)
    return metadata


def _delivery_names(catalog: dict[str, Any]) -> dict[str, str]:
    """Delivery filenames come from deliverables.required, never from a literal."""
    found: dict[str, str] = {}
    for name in required_filenames(catalog, ARCHETYPE_ID):
        if name.endswith(".preview.png"):
            found["preview"] = name
        elif name.endswith(".meta.json"):
            found["meta"] = name
        elif name.endswith(".glb"):
            found["glb"] = name
    missing = {"glb", "preview", "meta"} - set(found)
    if missing:
        raise AssetContractError(
            "catalog_deliverables_incomplete", ", ".join(sorted(missing))
        )
    return found


def _meta_bytes(metadata: dict[str, Any]) -> bytes:
    return (json.dumps(metadata, indent=2) + "\n").encode("utf-8")


def _footprint_fit_errors(document, footprint, catalog) -> list[str]:
    """The contract's 5% fit tolerance, checked against the emitted accessor."""
    tolerance = 0.05
    accessor = document["accessors"][0]
    extent_x = accessor["max"][0] - accessor["min"][0]
    extent_z = accessor["max"][2] - accessor["min"][2]
    errors = []
    for axis, extent, declared in (
        ("width", extent_x, float(footprint["width"])),
        ("length", extent_z, float(footprint["length"])),
    ):
        if extent > declared * (1 + tolerance):
            errors.append(
                f"geometry {axis} {extent} does not fit the declared {declared}"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--request", type=Path, default=REQUEST)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    args = parser.parse_args(argv)
    try:
        build(args.output, args.request, args.catalog)
    except AssetContractError as exc:
        print(f"{ARCHETYPE_ID} delivery failed: {exc}", file=sys.stderr)
        return 1
    print(f"wrote the {ARCHETYPE_ID} delivery to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

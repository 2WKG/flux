"""Build a neutral, non-site-specific nuclear/SMR archetype delivery."""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / "data/3d/requests/minnesota-nuclear-smr-v1.json"


def _glb(request: dict) -> bytes:
    width, length, height = 100.0, 120.0, 30.0
    x, z = width / 2, length / 2
    vertices = [
        (-x, 0, -z),
        (x, 0, -z),
        (x, 0, z),
        (-x, 0, z),
        (-x, height, -z),
        (x, height, -z),
        (x, height, z),
        (-x, height, z),
    ]
    faces = [
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
    positions = b"".join(struct.pack("<fff", *vertex) for vertex in vertices)
    index_data = struct.pack("<" + "H" * len(faces), *faces)
    binary = positions + index_data
    document = {
        "asset": {"version": "2.0", "generator": "Flux nuclear/SMR archetype builder"},
        "extras": {
            "archetype_id": request["model"]["archetype_id"],
            "contract_id": request["model"]["contract_id"],
            "pivot": "ground_center",
            "axis": {"up": "Y", "forward": "-Z"},
        },
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": len(positions),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": len(positions),
                "byteLength": len(index_data),
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 8,
                "type": "VEC3",
                "min": [-x, 0, -z],
                "max": [x, height, z],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": len(faces),
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
                "name": "nuclear_smr_module_lod0",
                "primitives": [
                    {"attributes": {"POSITION": 0}, "indices": 1, "material": 0}
                ],
            }
        ],
        "nodes": [
            {"name": "nuclear_smr_module", "mesh": 0},
            {"name": "CONN_HV_OUT_0", "translation": [0, 0, z]},
        ],
        "scenes": [{"nodes": [0, 1]}],
        "scene": 0,
    }
    payload = json.dumps(document, separators=(",", ":")).encode()

    def chunk(kind: bytes, value: bytes) -> bytes:
        value += b" " * ((-len(value)) % 4)
        return struct.pack("<I4s", len(value), kind) + value

    body = chunk(b"JSON", payload) + chunk(b"BIN\\x00", binary)
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def _preview(path: Path) -> None:
    size = 512
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            inside = size // 5 < x < size * 4 // 5 and size // 5 < y < size * 4 // 5
            row.extend((100, 110, 122) if inside else (232, 237, 242))
        rows.append(bytes(row))

    def chunk(kind: bytes, value: bytes) -> bytes:
        return (
            struct.pack(">I", len(value))
            + kind
            + value
            + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


def build(output: Path, request_path: Path = REQUEST) -> dict:
    request = json.loads(request_path.read_text())
    model = request["model"]
    output.mkdir(parents=True, exist_ok=True)
    (output / "nuclear_smr_module.glb").write_bytes(_glb(request))
    _preview(output / "nuclear_smr_module.preview.png")
    metadata = {
        "archetype_id": model["archetype_id"],
        "contract_id": model["contract_id"],
        "triangles_lod0": 12,
        "triangles_lod1": 0,
        "triangles_lod2": 0,
        "footprint_m": model["footprint_m"],
        "connectors": model["connectors"],
        "author": "Flux hackathon team",
        "license": "CC0-1.0",
        "source_of_shape": "Original generic module silhouette; not a vendor design, licensed reactor, or sited project.",
        "status_material": "MAT_STATUS",
    }
    (output / "nuclear_smr_module.meta.json").write_text(
        json.dumps(metadata, indent=2) + "\n"
    )
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "build/3d/nuclear_smr_module"
    )
    parser.add_argument("--request", type=Path, default=REQUEST)
    args = parser.parse_args()
    build(args.output, args.request)

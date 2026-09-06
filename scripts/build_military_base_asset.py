"""Build the neutral military-base archetype delivery without committing binaries."""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUEST = ROOT / "data/3d/requests/minnesota-military-base-v1.json"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    payload += b" " * ((-len(payload)) % 4)
    return struct.pack("<I4s", len(payload), kind) + payload


def _png(path: Path, size: int = 512) -> None:
    """Write a neutral 512px RGB preview using only the standard library."""
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            inside = size // 6 < x < size * 5 // 6 and size // 4 < y < size * 3 // 4
            row.extend((83, 101, 119) if inside else (230, 235, 240))
        rows.append(bytes(row))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


def _glb(request: dict) -> bytes:
    # A deliberately generic, ground-centred rectangular installation silhouette.
    width, length, height = 160.0, 200.0, 24.0
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
    indices = [
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
    index_data = struct.pack("<" + "H" * len(indices), *indices)
    binary = positions + index_data
    gltf = {
        "asset": {
            "version": "2.0",
            "generator": "Flux military-base archetype builder",
        },
        "extras": {
            "archetype_id": request["model"]["archetype_id"],
            "contract_id": request["model"]["contract_id"],
            "axis": {"up": "Y", "forward": "-Z"},
            "pivot": "ground_center",
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
                "count": len(indices),
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
                "name": "military_base_lod0",
                "primitives": [
                    {"attributes": {"POSITION": 0}, "indices": 1, "material": 0}
                ],
            }
        ],
        "nodes": [
            {"name": "military_base", "mesh": 0},
            {"name": "CONN_MV_FEED_0", "translation": [0, 0, -z]},
        ],
        "scenes": [{"nodes": [0, 1]}],
        "scene": 0,
    }
    json_data = json.dumps(gltf, separators=(",", ":")).encode()
    return (
        struct.pack(
            "<4sII",
            b"glTF",
            2,
            12 + len(_chunk(b"JSON", json_data)) + len(_chunk(b"BIN\\x00", binary)),
        )
        + _chunk(b"JSON", json_data)
        + _chunk(b"BIN\\x00", binary)
    )


def build(output: Path, request_path: Path = REQUEST) -> dict:
    request = json.loads(request_path.read_text())
    model = request["model"]
    output.mkdir(parents=True, exist_ok=True)
    (output / "military_base.glb").write_bytes(_glb(request))
    _png(output / "military_base.preview.png")
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
        "source_of_shape": "Original generic rectangular installation silhouette; no real facility geometry or identity.",
        "status_material": "MAT_STATUS",
        "limits": "Generic non-geographic archetype only; it asserts no real facility, perimeter, or asset disposition.",
    }
    (output / "military_base.meta.json").write_text(
        json.dumps(metadata, indent=2) + "\n"
    )
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "build/3d/military_base")
    parser.add_argument("--request", type=Path, default=REQUEST)
    args = parser.parse_args()
    build(args.output, args.request)

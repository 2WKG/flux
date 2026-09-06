"""Small independent counterexamples for the load-bearing audit measurements."""

import binascii
import io
import json
import math
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import validate_pack as audit


def encode_glb(doc, payload):
    document = json.dumps(doc).encode()
    document += b" " * (-len(document) % 4)
    payload += b"\0" * (-len(payload) % 4)
    return (
        struct.pack("<4sII", b"glTF", 2, 28 + len(document) + len(payload))
        + struct.pack("<II", len(document), 0x4E4F534A)
        + document
        + struct.pack("<II", len(payload), 0x004E4942)
        + payload
    )


def cube():
    p = [
        (-1, 0, -1),
        (-1, 0, 1),
        (-1, 2, -1),
        (-1, 2, 1),
        (1, 0, -1),
        (1, 0, 1),
        (1, 2, -1),
        (1, 2, 1),
    ]
    # This Y-up fixture's winding is calculated independently from its six planes.
    quads = [
        (0, 4, 5, 1),
        (2, 3, 7, 6),
        (0, 2, 6, 4),
        (1, 5, 7, 3),
        (0, 1, 3, 2),
        (4, 6, 7, 5),
    ]
    triangles = [(q[0], q[1], q[2]) for q in quads] + [
        (q[0], q[2], q[3]) for q in quads
    ]
    return p, triangles


def fixture():
    p, triangles = cube()
    positions = b"".join(struct.pack("<3f", *v) for v in p)
    indices = b"".join(struct.pack("<3H", *t) for t in triangles)
    payload = positions + indices
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0, 1, 2]}],
        "nodes": [
            {"name": "fixture_mesh", "mesh": 0},
            {"name": "CONN_HV_IN_0", "translation": [0, 1, -1]},
            {"name": "CONN_HV_OUT_0", "translation": [0, 1, 1]},
        ],
        "materials": [
            {
                "name": "MAT_STATUS",
                "pbrMetallicRoughness": {"baseColorFactor": [0.5, 0.5, 0.5, 1]},
            }
        ],
        "meshes": [
            {
                "primitives": [
                    {"attributes": {"POSITION": 0}, "indices": 1, "material": 0}
                ]
            }
        ],
        "buffers": [{"byteLength": len(payload)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(p), "type": "VEC3"},
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": len(triangles) * 3,
                "type": "SCALAR",
            },
        ],
    }
    return doc, payload


def png(colors, depth=8):
    def chunk(kind, content):
        return (
            struct.pack(">I", len(content))
            + kind
            + content
            + struct.pack(">I", binascii.crc32(kind + content) & 0xFFFFFFFF)
        )

    samples = b"".join(v.to_bytes(depth // 8, "big") for c in colors for v in c)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", len(colors), 1, depth, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0" + samples))
        + chunk(b"IEND", b"")
    )


class Measurements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = {
            "contractId": "flux:test:asset-archetypes:v1",
            "archetypes": [
                {
                    "id": "fixture",
                    "connectors": ["HV_IN", "HV_OUT"],
                    "footprint_m": {"length": 12, "width": 12},
                }
            ],
            "budgets": {
                "perArchetypeFileBytes": 3 * 1024 * 1024,
                "perArchetypeTrianglesLod0": 40000,
                "textureMaxPixels": 2048,
            },
            "deliverables": {
                "previewPixels": 512,
                "metaFields": [
                    "archetype_id",
                    "contract_id",
                    "triangles_lod0",
                    "triangles_lod1",
                    "triangles_lod2",
                    "footprint_m",
                    "connectors",
                    "author",
                    "license",
                    "source_of_shape",
                ],
            },
            "transform": {
                "lengthUnit": "meter",
                "unitScale": 1.0,
                "upAxis": "Y",
                "forwardAxis": "-Z",
                "handedness": "right",
                "pivot": "ground_center",
            },
        }
        cls.entry = cls.catalog["archetypes"][0]

    def run_fixture(self, doc, payload):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixture.glb"
            path.write_bytes(encode_glb(doc, payload))
            return audit.audit_glb(path, self.entry, self.catalog)

    def test_actual_indices_triangles_bounds_and_connector_positions(self):
        result = self.run_fixture(*fixture())
        self.assertEqual(result["triangles"], 12)
        self.assertEqual(result["extent_xyz_m"], [2, 2, 2])
        self.assertEqual(result["bounds_min_m"], [-1, 0, -1])
        self.assertEqual(result["connectors"]["CONN_HV_IN_0"], [0, 1, -1])

    def test_node_world_scale_is_applied_before_footprint_check(self):
        doc, payload = fixture()
        doc["nodes"][0]["scale"] = [7, 1, 1]
        with self.assertRaisesRegex(ValueError, "footprint"):
            self.run_fixture(doc, payload)

    def test_ground_translation_rejected(self):
        doc, payload = fixture()
        doc["nodes"][0]["translation"] = [0, 1, 0]
        with self.assertRaisesRegex(ValueError, "minimum Y"):
            self.run_fixture(doc, payload)

    def test_mirrored_instance_uses_gltf_reversed_winding(self):
        doc, payload = fixture()
        doc["nodes"][0]["scale"] = [-1, 1, 1]
        result = self.run_fixture(doc, payload)
        self.assertEqual(result["triangles"], 12)

    def test_parent_rotation_and_translation_compose(self):
        parent = audit.node_matrix(
            {
                "translation": [5, 0, 2],
                "rotation": [0, math.sqrt(0.5), 0, math.sqrt(0.5)],
            }
        )
        child = audit.node_matrix({"translation": [0, 0, 3], "scale": [2, 1, 1]})
        result = audit.point(audit.product(parent, child), [1, 0, 0])
        for actual, expected in zip(result, [8, 0, 0]):
            self.assertAlmostEqual(actual, expected)

    def test_matrix_column_major(self):
        m = audit.node_matrix(
            {"matrix": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 4, 5, 6, 1]}
        )
        self.assertEqual(audit.point(m, [1, 2, 3]), [5, 7, 9])

    def test_neutral_status_rejects_baked_color(self):
        doc, payload = fixture()
        doc["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"] = [1, 0, 0, 1]
        with self.assertRaisesRegex(ValueError, "neutral"):
            self.run_fixture(doc, payload)

    def test_status_effective_emission_includes_strength(self):
        doc, payload = fixture()
        doc["materials"][0]["emissiveFactor"] = [1e-8, 0, 0]
        doc["materials"][0]["extensions"] = {
            "KHR_materials_emissive_strength": {"emissiveStrength": 100000000}
        }
        with self.assertRaisesRegex(ValueError, "baked color"):
            self.run_fixture(doc, payload)

    def test_external_buffer_rejected(self):
        doc, payload = fixture()
        doc["buffers"][0]["uri"] = "mesh.bin"
        with self.assertRaisesRegex(ValueError, "embedded buffer"):
            self.run_fixture(doc, payload)

    def test_connector_mesh_rejected(self):
        doc, payload = fixture()
        doc["nodes"][1]["mesh"] = 0
        with self.assertRaisesRegex(ValueError, "empty leaf"):
            self.run_fixture(doc, payload)

    def test_out_of_range_index_rejected(self):
        doc, payload = fixture()
        payload = payload[:96] + struct.pack("<H", 500) + payload[98:]
        with self.assertRaisesRegex(ValueError, "index outside"):
            self.run_fixture(doc, payload)

    def test_nonfinite_position_rejected(self):
        doc, payload = fixture()
        payload = struct.pack("<f", math.nan) + payload[4:]
        with self.assertRaisesRegex(ValueError, "non-finite accessor"):
            self.run_fixture(doc, payload)

    def test_reversed_closed_volume_rejected(self):
        doc, _ = fixture()
        p, triangles = cube()
        payload = b"".join(struct.pack("<3f", *v) for v in p) + b"".join(
            struct.pack("<3H", c, b, a) for a, b, c in triangles
        )
        with self.assertRaisesRegex(ValueError, "inward closed"):
            self.run_fixture(doc, payload)

    def test_open_triangle_not_claimed_closed(self):
        result = audit.topology([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])
        self.assertEqual(result["closed_components"], 0)
        self.assertEqual(result["open_or_nonmanifold_components"], 1)

    def test_corner_touching_shells_do_not_cancel_inward_volume(self):
        p, triangles = cube()
        smaller = [(x * 0.5 + 1.5, y * 0.5 + 2, z * 0.5 + 1.5) for x, y, z in p]
        combined = triangles + [(c + 8, b + 8, a + 8) for a, b, c in triangles]
        result = audit.topology(p + smaller, combined)
        self.assertEqual(result["closed_components"], 2)
        self.assertEqual(len(result["inward_closed_components"]), 1)

    def test_png_pixel_decode_and_empty_preview_rejection(self):
        result = audit.png_info(png([(1, 2, 3, 0), (8, 9, 10, 255)]))
        self.assertEqual(
            (
                result["width"],
                result["height"],
                result["alpha_min"],
                result["alpha_max"],
            ),
            (2, 1, 0, 255),
        )
        with self.assertRaisesRegex(ValueError, "uniform or fully transparent"):
            audit.png_info(png([(1, 2, 3, 0), (1, 2, 3, 0)]))

    def test_png_16bit_low_samples_preserved(self):
        result = audit.png_info(png([(1, 2, 3, 1), (8, 9, 10, 255)], depth=16))
        self.assertEqual(result["unique_rgb_colors"], 2)
        self.assertEqual(
            (result["alpha_min"], result["alpha_max"], result["visible_pixels"]),
            (1, 255, 2),
        )

    def test_empty_directory_is_not_a_complete_pack(self):
        with tempfile.TemporaryDirectory() as folder:
            report = audit.audit_pack(Path(folder), self.catalog)
        self.assertFalse(report["complete_pack"])
        self.assertFalse(report["passed"])

    def test_metadata_bounds_require_three_coordinates(self):
        aid = self.entry["id"]
        meta = {
            "archetype_id": aid,
            "contract_id": self.catalog["contractId"],
            "triangles_lod0": 1000,
            "triangles_lod1": 300,
            "triangles_lod2": 100,
            "footprint_m": self.entry["footprint_m"],
            "connectors": [],
            "author": "test",
            "license": "CC0-1.0",
            "source_of_shape": "Test fixture",
            "transform": self.catalog["transform"],
            "bounds_m": {"min": [-1], "max": [1]},
        }

        def measurement(path, entry, catalog):
            lod = (
                "lod1"
                if ".lod1." in path.name
                else "lod2"
                if ".lod2." in path.name
                else "lod0"
            )
            return {
                "triangles": meta["triangles_" + lod],
                "bytes": 100,
                "connectors": {},
                "bounds_min_m": [-1, 0, -1],
                "bounds_max_m": [1, 2, 1],
            }

        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / "assets" / aid
            directory.mkdir(parents=True)
            (directory / (aid + ".meta.json")).write_text(json.dumps(meta))
            with patch.object(audit, "audit_glb", side_effect=measurement):
                report = audit.audit_pack(Path(folder), self.catalog, [aid])
        self.assertTrue(
            any(
                "metadata bounds must be 3 finite coordinates" in error
                for error in report["errors"]
            )
        )

    def test_cli_requires_explicit_generated_root(self):
        errors = io.StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            audit.main([])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--root", errors.getvalue())

    def test_cli_audits_explicit_root_and_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "generated"
            root.mkdir()
            catalog_path = Path(folder) / "catalog.json"
            catalog_path.write_text(json.dumps(self.catalog))
            report_path = Path(folder) / "reports" / "audit.json"
            with redirect_stdout(io.StringIO()):
                result = audit.main(
                    [
                        "--root",
                        str(root),
                        "--catalog",
                        str(catalog_path),
                        "--output",
                        str(report_path),
                    ]
                )
            report = json.loads(report_path.read_text())
        self.assertEqual(result, 1)
        self.assertEqual(report["asset_root"], str(root))
        self.assertEqual(report["asset_count_expected"], 1)
        self.assertFalse(report["passed"])
        self.assertTrue(any("fixture.glb" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

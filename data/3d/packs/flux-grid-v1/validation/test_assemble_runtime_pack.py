"""Counterexamples for the runtime-pack delivery boundary.

`assemble_runtime_pack.py` is the last program between an audited build and a
package a browser will trust.  These tests exist because the audit it consumes
is a separate JSON file: the load-bearing question is not "does it copy files"
but "can bytes that the audit never saw reach the manifest".
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
CATALOG = PACK.parents[1] / "asset-archetypes-v1.json"

_spec = importlib.util.spec_from_file_location(
    "assemble_runtime_pack", PACK / "source" / "pipeline" / "assemble_runtime_pack.py"
)
assert _spec and _spec.loader
assemble = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(assemble)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path, triangles: int | None = None) -> dict:
    """The shape `validate_pack.audit_glb` writes: a digest plus a size."""
    out = {"sha256": sha(path), "bytes": path.stat().st_size}
    if triangles is not None:
        out["triangles"] = triangles
    return out


class Fixture:
    """A build tree plus the audit that truthfully describes it.

    The bytes are stand-ins, not real GLBs: the assembler hashes and copies, it
    never parses geometry.  `validate_pack.py` owns geometry, and its own tests
    cover it.
    """

    def __init__(self, root: Path, catalog: dict):
        self.root = root
        self.catalog = catalog
        self.build = root / "build"
        self.symbols = root / "symbols"
        self.output = root / "runtime"
        assets = []
        for index, entry in enumerate(catalog["archetypes"]):
            aid = entry["id"]
            folder = self.build / "assets" / aid
            folder.mkdir(parents=True)
            lods = {}
            for lod in range(3):
                suffix = "" if lod == 0 else f".lod{lod}"
                path = folder / f"{aid}{suffix}.glb"
                path.write_bytes(f"glTF-stand-in {aid} lod{lod}".encode() * (lod + 2))
                lods[f"lod{lod}"] = record(
                    path, triangles=1000 * (index + 1) // (lod + 1)
                )
            meta = folder / f"{aid}.meta.json"
            meta.write_text(
                json.dumps(
                    {
                        "archetype_id": aid,
                        "contract_id": catalog["contractId"],
                        "bounds_m": {"min": [0, 0, 0], "max": [1, 1, 1]},
                        "source_of_shape": "procedural",
                        "license": "CC0-1.0",
                    }
                )
                + "\n"
            )
            preview = folder / f"{aid}.preview.png"
            preview.write_bytes(b"\x89PNG stand-in " + aid.encode())
            assets.append(
                {
                    "archetype_id": aid,
                    "lods": lods,
                    "metadata": {"sha256": sha(meta)},
                    "preview": {"sha256": sha(preview)},
                    "errors": [],
                }
            )
        self.audit = {
            "schema_version": 1,
            "contract_id": catalog["contractId"],
            "assets": assets,
            "errors": [],
            "passed": True,
            "complete_pack": True,
            "asset_count_passed": len(assets),
        }
        self.symbols.mkdir()
        for name in assemble.SYMBOL_FILES:
            (self.symbols / name).write_bytes(f"symbol stand-in {name}".encode())
        self.audit_path = root / "independent-audit.json"
        self.write_audit()

    def write_audit(self) -> None:
        self.audit_path.write_text(json.dumps(self.audit, indent=2) + "\n")

    def catalog_path(self) -> Path:
        path = self.root / "catalog.json"
        path.write_text(json.dumps(self.catalog))
        return path

    def run(self) -> dict:
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = assemble.main(
                [
                    "--build",
                    str(self.build),
                    "--audit",
                    str(self.audit_path),
                    "--symbols",
                    str(self.symbols),
                    "--output",
                    str(self.output),
                    "--catalog",
                    str(self.catalog_path()),
                ]
            )
        assert code == 0, code
        return json.loads(stream.getvalue())


class Assembly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full_catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.fixture = Fixture(self.dir, self.full_catalog)

    def test_a_truthful_audit_assembles_the_whole_pack(self):
        summary = self.fixture.run()
        manifest = json.loads((self.fixture.output / "manifest.json").read_text())
        self.assertEqual(len(manifest["assets"]), len(self.full_catalog["archetypes"]))
        self.assertEqual(summary["assets"], 18)
        self.assertEqual(summary["models"], 54)
        inventory = (
            (self.fixture.output / "package.SHA256SUMS").read_text().splitlines()
        )
        self.assertIn("manifest.json", inventory[0])
        # Every pinned digest is the digest of a file that is actually there.
        for line in inventory:
            expected, relative = line.split("  ", 1)
            self.assertEqual(sha(self.fixture.output / relative), expected, relative)

    def test_a_model_replaced_after_the_audit_is_refused_by_name(self):
        """The blocker: `--audit` must not be a detached token.

        Overwriting a model after the audit ran previously produced exit 0, a
        manifest reading `bytes: 16` beside the audit's triangle count, and
        `complete_pack: true`.
        """
        poisoned = self.fixture.build / "assets" / "hospital" / "hospital.glb"
        poisoned.write_bytes(b"not a GLB at all")
        with self.assertRaises(ValueError) as caught:
            self.fixture.run()
        self.assertIn("hospital.glb", str(caught.exception))
        self.assertIn("do not match the audit", str(caught.exception))
        self.assertFalse(
            self.fixture.output.exists(), "refused before writing anything"
        )

    def test_a_model_swapped_for_another_audited_model_is_refused(self):
        """Same size, same shape of file, wrong bytes: only the digest catches it."""
        assets = self.fixture.build / "assets"
        shutil.copyfile(
            assets / "solar_array" / "solar_array.glb",
            assets / "hospital" / "hospital.glb",
        )
        with self.assertRaises(ValueError) as caught:
            self.fixture.run()
        self.assertIn("hospital.glb", str(caught.exception))

    def test_replaced_metadata_is_refused(self):
        meta = self.fixture.build / "assets" / "hospital" / "hospital.meta.json"
        meta.write_text(
            json.dumps({"bounds_m": {}, "source_of_shape": "?", "license": "?"})
        )
        with self.assertRaises(ValueError) as caught:
            self.fixture.run()
        self.assertIn("hospital.meta.json", str(caught.exception))

    def test_replaced_preview_is_refused(self):
        preview = self.fixture.build / "assets" / "hospital" / "hospital.preview.png"
        preview.write_bytes(b"\x89PNG something else entirely")
        with self.assertRaises(ValueError) as caught:
            self.fixture.run()
        self.assertIn("hospital.preview.png", str(caught.exception))

    def test_a_model_deleted_after_the_audit_is_refused_by_name(self):
        (self.fixture.build / "assets" / "hospital" / "hospital.lod2.glb").unlink()
        with self.assertRaises(ValueError) as caught:
            self.fixture.run()
        self.assertIn("hospital.lod2.glb", str(caught.exception))
        self.assertIn("missing from the build", str(caught.exception))

    def test_an_audit_without_digests_is_refused_rather_than_trusted(self):
        for asset in self.fixture.audit["assets"]:
            asset["lods"]["lod0"].pop("sha256")
        self.fixture.write_audit()
        with self.assertRaises(ValueError) as caught:
            self.fixture.run()
        self.assertIn("no usable sha256", str(caught.exception))

    def test_an_audit_of_a_different_contract_is_refused(self):
        self.fixture.audit["contract_id"] = "flux-3d-asset-contract-v0"
        self.fixture.write_audit()
        with self.assertRaises(ValueError) as caught:
            self.fixture.run()
        self.assertIn("different contract", str(caught.exception))

    def test_a_failing_or_partial_audit_is_still_refused(self):
        for key, value in (("passed", False), ("complete_pack", False)):
            with self.subTest(key=key):
                original = self.fixture.audit[key]
                self.fixture.audit[key] = value
                self.fixture.write_audit()
                with self.assertRaises(ValueError) as caught:
                    self.fixture.run()
                self.assertIn("incomplete or failing", str(caught.exception))
                self.fixture.audit[key] = original
                self.fixture.write_audit()

    def test_the_reported_counts_are_measured_not_recited(self):
        """`models: 54` used to be a literal printed beside a 16-byte model."""
        smaller = dict(self.full_catalog)
        smaller["archetypes"] = self.full_catalog["archetypes"][:5]
        fixture = Fixture(self.dir / "five", smaller)
        summary = fixture.run()
        self.assertEqual(summary["assets"], 5)
        self.assertEqual(summary["models"], 15)


if __name__ == "__main__":
    unittest.main()

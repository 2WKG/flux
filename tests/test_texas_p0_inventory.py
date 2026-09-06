from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path("scripts/validate_texas_p0_inventory.py")
SPEC = importlib.util.spec_from_file_location("texas_p0_inventory", MODULE_PATH)
assert SPEC and SPEC.loader
inventory_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory_module)


def _inventory() -> dict:
    return json.loads(
        Path("data/sources/texas-p0-inventory.json").read_text(encoding="utf-8")
    )


def test_checked_in_texas_p0_inventory_validates_and_labels_public_scope(
    tmp_path: Path,
) -> None:
    report = inventory_module.build_report(_inventory(), tmp_path / "missing-raw")

    assert report["validation"] == {"passed": True, "errors": []}
    assert report["summary"] == {
        "excluded": 1,
        "ingested": 0,
        "unavailable": 9,
        "validated": 1,
    }
    assert "synthetic" in report["synthetic_geometry_caveat"].lower()
    assert "not the real ercot" in report["synthetic_geometry_caveat"].lower()
    assert report["records"][0]["checked_in_receipt"] == {
        "path": "data\\sources\\activsg2000.json",
        "passed": True,
        "mismatches": [],
    }
    assert all(
        record["license_access"]["access"] == "public" for record in report["records"]
    )
    assert all(
        not artifact["present_in_requested_raw_root"]
        for record in report["records"]
        for artifact in record["artifacts"]
    )


def test_inventory_rejects_unexplained_or_nonpublic_records() -> None:
    inventory = copy.deepcopy(_inventory())
    inventory["records"][0]["reason"] = ""
    inventory["records"][1]["license_access"]["access"] = "restricted"

    errors = inventory_module.validate_inventory(inventory)

    assert any("reason" in error for error in errors)
    assert any("public-only" in error for error in errors)

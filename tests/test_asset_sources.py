"""One parametrized suite over every committed 3D archetype source kit.

This replaces the per-asset copy-paste test files. Those files drifted: some
looked the catalog row up by the metadata's own `archetype_id` (so the
expectation came from the value under test), some never opened `scene.json` at
all, and none of them compared the geometry to the footprint it claims. Every
property below is mutation-checked by the negative tests at the bottom of this
file, which copy a real asset to a tmp dir and corrupt it.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_asset_source import (
    DEFAULT_ASSET_ROOT,
    FOOTPRINT_TOLERANCE,
    asset_dirs,
    build_report,
    load_catalog,
    node_aabb,
    validate_asset,
)

CATALOG = load_catalog()
ASSET_DIRS = asset_dirs()
ASSET_IDS = [directory.name for directory in ASSET_DIRS]


def _read(asset_dir: Path, suffix: str) -> dict[str, Any]:
    return json.loads(
        (asset_dir / f"{asset_dir.name}{suffix}").read_text(encoding="utf-8")
    )


def _archetype(asset_id: str) -> dict[str, Any]:
    return next(entry for entry in CATALOG["archetypes"] if entry["id"] == asset_id)


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@pytest.fixture()
def asset_copy(tmp_path: Path) -> Path:
    """A byte-copy of the first committed source kit, safe to corrupt."""
    assert ASSET_DIRS, "no committed asset source kits to validate"
    source = ASSET_DIRS[0]
    destination = tmp_path / source.name
    shutil.copytree(source, destination)
    return destination


@pytest.mark.parametrize("asset_dir", ASSET_DIRS, ids=ASSET_IDS)
def test_every_committed_source_kit_conforms_to_the_shared_contract(asset_dir: Path):
    assert validate_asset(asset_dir, CATALOG) == []


@pytest.mark.parametrize("asset_dir", ASSET_DIRS, ids=ASSET_IDS)
def test_geometry_fits_the_declared_footprint_and_sits_on_the_ground(asset_dir: Path):
    """The footprint rectangle is the collision proxy; geometry must fit it."""
    scene = _read(asset_dir, ".scene.json")
    footprint = _archetype(asset_dir.name)["footprint_m"]
    aabb = node_aabb(scene["nodes"])

    assert aabb is not None
    assert aabb["max"][0] - aabb["min"][0] <= footprint["width"] * (
        1 + FOOTPRINT_TOLERANCE
    )
    assert aabb["max"][2] - aabb["min"][2] <= footprint["length"] * (
        1 + FOOTPRINT_TOLERANCE
    )
    assert aabb["min"][1] == 0
    bounds = scene["bounds_m"]
    for axis in range(3):
        assert bounds["min"][axis] <= aabb["min"][axis]
        assert aabb["max"][axis] <= bounds["max"][axis]


@pytest.mark.parametrize("asset_dir", ASSET_DIRS, ids=ASSET_IDS)
def test_no_binary_or_render_is_committed_beside_a_source_kit(asset_dir: Path):
    """Binaries are asset-pipeline outputs; the contract governs shape, not hosting."""
    committed = sorted(path.name for path in asset_dir.iterdir() if path.is_file())
    asset_id = asset_dir.name

    assert committed == [
        f"{asset_id}.meta.json",
        f"{asset_id}.preview.svg",
        f"{asset_id}.scene.json",
    ]


def test_report_covers_every_asset_directory():
    report = build_report(CATALOG, DEFAULT_ASSET_ROOT)

    assert report["validation"] == {"passed": True, "errors": []}
    assert sorted(report["assets"]) == sorted(ASSET_IDS)
    assert report["assetCount"] == len(ASSET_IDS)


def test_identity_comes_from_the_directory_not_from_the_metadata(asset_copy: Path):
    """A coherent meta for another archetype must not pass in this directory."""
    other = next(
        entry for entry in CATALOG["archetypes"] if entry["id"] != asset_copy.name
    )
    meta = _read(asset_copy, ".meta.json")
    imposter = copy.deepcopy(meta)
    imposter["archetype_id"] = other["id"]
    imposter["semantic_name"] = other["semantic_name"]
    imposter["category"] = other["category"]
    imposter["footprint_m"] = other["footprint_m"]
    imposter["triangles"] = other["lod_triangles"]
    for level, value in other["lod_triangles"].items():
        imposter[f"triangles_{level}"] = value
    _write(asset_copy / f"{asset_copy.name}.meta.json", imposter)

    errors = validate_asset(asset_copy, CATALOG)

    assert any("must equal the asset directory name" in error for error in errors)


def test_a_missing_contract_required_meta_field_is_rejected(asset_copy: Path):
    for field in ("author", "license", "source_of_shape", "triangles_lod0"):
        meta = _read(asset_copy, ".meta.json")
        del meta[field]
        _write(asset_copy / f"{asset_copy.name}.meta.json", meta)

        errors = validate_asset(asset_copy, CATALOG)

        assert any(field in error for error in errors), field


def test_an_invented_status_label_is_rejected(asset_copy: Path):
    """ "illustrative" is exactly the label the narrative-IA contract removed."""
    meta = _read(asset_copy, ".meta.json")
    meta["material_slots"][0]["allowed_labels"].append("illustrative")
    _write(asset_copy / f"{asset_copy.name}.meta.json", meta)

    errors = validate_asset(asset_copy, CATALOG)

    assert any("server-asserted labels" in error for error in errors)


def test_geometry_that_overruns_the_footprint_is_rejected(asset_copy: Path):
    scene = _read(asset_copy, ".scene.json")
    for node in scene["nodes"]:
        if "size_m" in node:
            node["size_m"] = [value * 10 for value in node["size_m"]]
    _write(asset_copy / f"{asset_copy.name}.scene.json", scene)

    errors = validate_asset(asset_copy, CATALOG)

    assert any("exceeds the declared" in error for error in errors)


def test_geometry_that_floats_off_the_ground_is_rejected(asset_copy: Path):
    scene = _read(asset_copy, ".scene.json")
    for node in scene["nodes"]:
        node["position_m"][1] += 5
    _write(asset_copy / f"{asset_copy.name}.scene.json", scene)

    errors = validate_asset(asset_copy, CATALOG)

    assert any("not 0" in error for error in errors)


def test_a_scene_that_is_missing_or_disowned_is_rejected(asset_copy: Path):
    scene_path = asset_copy / f"{asset_copy.name}.scene.json"
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    scene["archetype_id"] = "totally_wrong"
    _write(scene_path, scene)
    assert any(
        "scene archetype_id" in error for error in validate_asset(asset_copy, CATALOG)
    )

    scene_path.unlink()
    assert any("scene.json" in error for error in validate_asset(asset_copy, CATALOG))


def test_connector_empties_must_match_the_declared_connectors(asset_copy: Path):
    scene_path = asset_copy / f"{asset_copy.name}.scene.json"
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    scene["nodes"] = [
        node for node in scene["nodes"] if node.get("primitive") != "empty"
    ]
    _write(scene_path, scene)

    errors = validate_asset(asset_copy, CATALOG)

    assert any("connector empties" in error for error in errors)


def test_a_blank_preview_is_rejected(asset_copy: Path):
    preview = asset_copy / f"{asset_copy.name}.preview.svg"
    preview.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512"/>',
        encoding="utf-8",
    )

    errors = validate_asset(asset_copy, CATALOG)

    assert any("is not a preview" in error for error in errors)
    assert any("<title>" in error for error in errors)


def test_a_preview_without_an_accessible_name_is_rejected(asset_copy: Path):
    preview = asset_copy / f"{asset_copy.name}.preview.svg"
    text = preview.read_text(encoding="utf-8").replace(
        ' aria-labelledby="title desc"', ""
    )
    preview.write_text(text, encoding="utf-8")

    errors = validate_asset(asset_copy, CATALOG)

    assert any("aria-labelledby" in error for error in errors)


def test_the_transform_and_status_slot_are_pinned(asset_copy: Path):
    meta_path = asset_copy / f"{asset_copy.name}.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["transform"]["up_axis"] = "Z"
    meta["material_slots"][0]["runtime_tinted"] = False
    _write(meta_path, meta)

    errors = validate_asset(asset_copy, CATALOG)

    assert any("transform.up_axis" in error for error in errors)
    assert any("runtime_tinted" in error for error in errors)


def test_a_committed_binary_or_render_is_rejected(asset_copy: Path):
    (asset_copy / f"{asset_copy.name}.glb").write_bytes(b"glTF")

    errors = validate_asset(asset_copy, CATALOG)

    assert any("must not be committed" in error for error in errors)


def test_an_unknown_asset_directory_is_rejected(tmp_path: Path):
    stray = tmp_path / "not_an_archetype"
    stray.mkdir()

    errors = validate_asset(stray, CATALOG)

    assert any("no catalog archetype" in error for error in errors)

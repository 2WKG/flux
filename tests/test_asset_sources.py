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
    BLENDER_KIT_TIER,
    DEFAULT_ASSET_ROOT,
    FLAT_META_TIER,
    FOOTPRINT_TOLERANCE,
    SOURCE_KIT_TIER,
    UNKNOWN_TIER,
    asset_dirs,
    asset_entries,
    asset_tier,
    build_report,
    entry_id,
    load_catalog,
    node_aabb,
    validate_asset,
)

CATALOG = load_catalog()
ASSET_DIRS = asset_dirs()
ASSET_IDS = [directory.name for directory in ASSET_DIRS]
ASSET_ENTRIES = asset_entries()
ENTRY_IDS = [entry_id(entry) for entry in ASSET_ENTRIES]
SOURCE_KIT_DIRS = [d for d in ASSET_DIRS if asset_tier(d) == SOURCE_KIT_TIER]
SOURCE_KIT_IDS = [d.name for d in SOURCE_KIT_DIRS]
BLENDER_KIT_DIRS = [d for d in ASSET_DIRS if asset_tier(d) == BLENDER_KIT_TIER]
BLENDER_KIT_IDS = [d.name for d in BLENDER_KIT_DIRS]


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
    assert SOURCE_KIT_DIRS, "no committed source kits to validate"
    source = SOURCE_KIT_DIRS[0]
    destination = tmp_path / source.name
    shutil.copytree(source, destination)
    return destination


@pytest.fixture()
def blender_copy(tmp_path: Path) -> Path:
    """A byte-copy of the first committed blender kit, safe to corrupt."""
    assert BLENDER_KIT_DIRS, "no committed blender kits to validate"
    source = BLENDER_KIT_DIRS[0]
    destination = tmp_path / source.name
    shutil.copytree(source, destination)
    return destination


@pytest.mark.parametrize("asset_dir", SOURCE_KIT_DIRS, ids=SOURCE_KIT_IDS)
def test_every_committed_source_kit_conforms_to_the_shared_contract(asset_dir: Path):
    assert validate_asset(asset_dir, CATALOG) == []


@pytest.mark.parametrize("asset_dir", SOURCE_KIT_DIRS, ids=SOURCE_KIT_IDS)
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


@pytest.mark.parametrize("asset_dir", SOURCE_KIT_DIRS, ids=SOURCE_KIT_IDS)
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
    assert sorted(report["assets"]) == sorted(ENTRY_IDS)
    assert report["assetCount"] == len(ENTRY_IDS)
    assert set(ASSET_IDS) <= set(report["assets"])
    assert all(
        entry["tier"] in {SOURCE_KIT_TIER, BLENDER_KIT_TIER, FLAT_META_TIER}
        for entry in report["assets"].values()
    )


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


# --- Delivery tiers -------------------------------------------------------
#
# `data/3d/assets/` carries three tiers at once: source kits (`<id>.scene.json`),
# blender kits (`<id>.blender.py`), and flat `<id>.meta.json` deliveries. The
# tests below prove each tier is checked by its own rules, that the tier is read
# off the directory's contents rather than a name list, and above all that an
# entry matching no tier is refused by name instead of quietly skipped.


def test_each_committed_entry_is_recognised_as_exactly_one_tier():
    assert ASSET_ENTRIES, "no committed asset entries to validate"
    tiers = {entry_id(entry): asset_tier(entry) for entry in ASSET_ENTRIES}

    assert None not in tiers.values(), tiers
    assert set(tiers.values()) == {SOURCE_KIT_TIER, BLENDER_KIT_TIER, FLAT_META_TIER}


@pytest.mark.parametrize("asset_dir", BLENDER_KIT_DIRS, ids=BLENDER_KIT_IDS)
def test_every_committed_blender_kit_conforms_to_its_own_tier(asset_dir: Path):
    assert asset_tier(asset_dir) == BLENDER_KIT_TIER
    assert validate_asset(asset_dir, CATALOG) == []


def test_the_master_transmission_line_blender_kit_passes():
    """The kit that broke the source-kit-only validator when it landed on master."""
    kit = DEFAULT_ASSET_ROOT / "transmission_line_segment"

    assert asset_tier(kit) == BLENDER_KIT_TIER
    assert validate_asset(kit, CATALOG) == []


@pytest.mark.parametrize(
    "meta_path",
    [e for e in ASSET_ENTRIES if e.is_file()],
    ids=[entry_id(e) for e in ASSET_ENTRIES if e.is_file()],
)
def test_every_committed_flat_meta_delivery_conforms_to_its_own_tier(meta_path: Path):
    assert asset_tier(meta_path) == FLAT_META_TIER
    assert validate_asset(meta_path, CATALOG) == []


def test_a_directory_matching_no_tier_is_refused_by_name(tmp_path: Path):
    """Not a skip: a catalog-named directory with neither marker file is an error."""
    known = CATALOG["archetypes"][0]["id"]
    neither = tmp_path / known
    neither.mkdir()
    (neither / f"{known}.meta.json").write_text("{}", encoding="utf-8")

    errors = validate_asset(neither, CATALOG)

    assert asset_tier(neither) is None
    assert any(UNKNOWN_TIER in error for error in errors), errors


def test_a_tier_marker_decides_the_rules_not_the_directory_name(
    asset_copy: Path, blender_copy: Path
):
    """Deleting the source kit's scene file changes its tier, not its pass/fail."""
    assert asset_tier(asset_copy) == SOURCE_KIT_TIER
    assert asset_tier(blender_copy) == BLENDER_KIT_TIER

    (asset_copy / f"{asset_copy.name}.scene.json").unlink()

    assert asset_tier(asset_copy) is None
    assert any(UNKNOWN_TIER in error for error in validate_asset(asset_copy, CATALOG))


def test_a_blender_kit_that_disowns_its_catalog_row_is_rejected(blender_copy: Path):
    meta_path = blender_copy / f"{blender_copy.name}.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["archetype_id"] = "totally_wrong"
    _write(meta_path, meta)

    errors = validate_asset(blender_copy, CATALOG)

    assert any("must equal the asset directory name" in error for error in errors)


def test_a_blender_kit_whose_bounds_overrun_the_footprint_is_rejected(
    blender_copy: Path,
):
    meta_path = blender_copy / f"{blender_copy.name}.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["bounds_m"]["max"] = [value * 10 for value in meta["bounds_m"]["max"]]
    _write(meta_path, meta)

    errors = validate_asset(blender_copy, CATALOG)

    assert any("exceeds the declared" in error for error in errors)


def test_a_blender_kit_that_floats_off_the_ground_is_rejected(blender_copy: Path):
    meta_path = blender_copy / f"{blender_copy.name}.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["bounds_m"]["min"][1] = 5.0
    _write(meta_path, meta)

    errors = validate_asset(blender_copy, CATALOG)

    assert any("not 0" in error for error in errors)


def test_a_blender_kit_with_a_wrong_axis_or_status_slot_is_rejected(
    blender_copy: Path,
):
    meta_path = blender_copy / f"{blender_copy.name}.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["transform"]["up_axis"] = "Z"
    meta["material_slots"][0]["default"] = "source_supported"
    _write(meta_path, meta)

    errors = validate_asset(blender_copy, CATALOG)

    assert any("transform.up_axis" in error for error in errors)
    assert any("material_slots" in error for error in errors)


def test_a_binary_committed_beside_a_blender_kit_is_rejected(blender_copy: Path):
    (blender_copy / f"{blender_copy.name}.glb").write_bytes(b"glTF")

    errors = validate_asset(blender_copy, CATALOG)

    assert any("must not be committed" in error for error in errors)


def test_a_flat_meta_delivery_that_drifts_from_the_catalog_is_rejected(
    tmp_path: Path,
):
    root = DEFAULT_ASSET_ROOT
    original = next(path for path in asset_entries(root) if path.is_file())
    copy_path = tmp_path / original.name
    meta = json.loads(original.read_text(encoding="utf-8"))
    meta["footprint_m"] = {"length": 1, "width": 1}
    _write(copy_path, meta)

    errors = validate_asset(copy_path, CATALOG)

    assert any("footprint_m does not match" in error for error in errors), errors

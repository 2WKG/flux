from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_hospital_kit import (
    CATALOG_PATH,
    KIT_DIR,
    META_PATH,
    SOURCE_PATH,
    load_builder,
    validate_kit,
)

BUILDER = load_builder()


def _kit_copy(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A writable copy of meta, builder source and catalog for negative tests."""
    meta = tmp_path / META_PATH.name
    source = tmp_path / SOURCE_PATH.name
    catalog = tmp_path / CATALOG_PATH.name
    for destination, origin in (
        (meta, META_PATH),
        (source, SOURCE_PATH),
        (catalog, CATALOG_PATH),
    ):
        destination.write_text(origin.read_text(encoding="utf-8"), encoding="utf-8")
    return meta, source, catalog


def test_hospital_kit_matches_the_shared_contract():
    assert validate_kit() == []


def test_hospital_kit_has_no_minnesota_identity_claim():
    metadata = json.loads(META_PATH.read_text(encoding="utf-8"))

    assert "Minnesota location" in metadata["limit"]
    assert metadata["material_slots"][0]["default"] == "neutral"


def test_authoring_frame_round_trips_through_the_gltf_export_mapping():
    """What the builder authors is what ``export_yup=True`` writes out.

    The kit's original defect was authoring contract (Y-up) coordinates straight
    into Blender's Z-up API; this pins the conversion both ways.
    """
    for point in ((0.0, 2.0, 30.0), (-15.0, 9.0, 0.0), (1.0, 2.0, 3.0)):
        assert BUILDER.contract_to_blender(point) == (point[0], -point[2], point[1])
        assert BUILDER.gltf_from_blender(BUILDER.contract_to_blender(point)) == point


def test_built_geometry_stands_on_the_ground_inside_its_footprint():
    manifest = BUILDER.scene_manifest()
    footprint = json.loads(META_PATH.read_text(encoding="utf-8"))["footprint_m"]
    minimum, maximum = manifest["bounds_m"]["min"], manifest["bounds_m"]["max"]

    assert minimum[1] == 0.0
    assert maximum[0] - minimum[0] <= footprint["width"]
    assert maximum[2] - minimum[2] <= footprint["length"]


def test_dry_run_prints_the_manifest_without_blender(capsys):
    assert BUILDER.main(["blender", "--", "--dry-run"]) == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed == BUILDER.scene_manifest()
    assert [connector["name"] for connector in printed["connectors"]] == [
        "CONN_MV_FEED_0"
    ]


# Each case deletes or corrupts exactly one thing the validator is supposed to
# police; if the matching rule is removed from validate_kit(), the case goes red.
@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda meta: meta.update(archetype_id="something_else"),
            "archetype_id must be hospital",
        ),
        (
            lambda meta: meta.update(contract_id="flux:3d-asset-archetypes:v99"),
            "metadata must bind the shared v1 contract",
        ),
        (
            lambda meta: meta["transform"].update(up_axis="Z"),
            "metadata transform must match the import contract",
        ),
        (
            lambda meta: meta.update(footprint_m={"length": 30, "width": 30}),
            "metadata footprint must match the shared archetype",
        ),
        (
            lambda meta: meta.update(triangles_lod0=31000),
            "LOD triangle budgets must match the shared archetype",
        ),
        (
            lambda meta: meta["connectors"][0].update(name="CONN_MV_SIDE_0"),
            "metadata must expose the named MV feeder connector",
        ),
        (
            lambda meta: meta["connectors"][0].update(role="HV_IN"),
            "connector roles must match the shared archetype",
        ),
        (
            lambda meta: meta["material_slots"][0].update(default="green"),
            "a neutral MAT_STATUS slot is required",
        ),
        (
            lambda meta: meta.pop("license"),
            "redistribution license and source_of_shape are required",
        ),
        (
            lambda meta: meta["connectors"][0].update(
                position_m=[999.0, -999.0, 999.0]
            ),
            "metadata connector positions must equal the positions the source builds",
        ),
        (
            lambda meta: meta["bounds_m"].update(max=[30.0, 999.0, 30.0]),
            "metadata bounds_m must equal the bounds the source builds",
        ),
    ],
)
def test_each_metadata_rule_is_enforced(tmp_path, mutate, expected):
    meta_path, source_path, catalog_path = _kit_copy(tmp_path)
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    mutate(metadata)
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")

    assert expected in validate_kit(meta_path, source_path, catalog_path)


def test_catalog_drift_turns_the_kit_red(tmp_path):
    """The kit's whole purpose is to match the catalog: prove it reads it."""
    meta_path, source_path, catalog_path = _kit_copy(tmp_path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    archetype = next(item for item in catalog["archetypes"] if item["id"] == "hospital")
    archetype["footprint_m"] = {"length": 30, "width": 30}
    archetype["lod_triangles"]["lod0"] = 31000
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    errors = validate_kit(meta_path, source_path, catalog_path)

    assert "metadata footprint must match the shared archetype" in errors
    assert "LOD triangle budgets must match the shared archetype" in errors


def test_losing_a_connector_from_the_source_turns_the_kit_red(tmp_path):
    meta_path, source_path, catalog_path = _kit_copy(tmp_path)
    source = source_path.read_text(encoding="utf-8")
    mutated = source.replace(
        '    {"name": "CONN_MV_FEED_0", "position_m": (',
        '    # {"name": "CONN_MV_FEED_0", "position_m": (',
    )
    assert mutated != source
    source_path.write_text(mutated, encoding="utf-8")

    assert (
        "metadata connector positions must equal the positions the source builds"
        in validate_kit(meta_path, source_path, catalog_path)
    )


def test_a_build_that_ignores_the_scene_description_turns_the_kit_red(tmp_path):
    meta_path, source_path, catalog_path = _kit_copy(tmp_path)
    source = source_path.read_text(encoding="utf-8")
    mutated = source.replace(
        "    for connector in CONNECTORS:\n        _add_connector(connector)",
        "    return",
    )
    assert mutated != source
    source_path.write_text(mutated, encoding="utf-8")

    assert (
        "build() must create every SCENE_NODES node and CONNECTORS empty"
        in validate_kit(meta_path, source_path, catalog_path)
    )


def test_no_binary_is_committed_beside_the_source():
    assert not list(KIT_DIR.glob("*.glb"))
    assert not list(KIT_DIR.glob("*.gltf"))


def test_geometry_that_leaves_the_ground_plane_turns_the_kit_red(tmp_path):
    """`pivot: ground_center` means y = 0 is the base, not the bounding-box centre."""
    meta_path, source_path, catalog_path = _kit_copy(tmp_path)
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "\nSCENE_NODES = tuple(\n"
        '    {**node, "position_m": (\n'
        '        node["position_m"][0],\n'
        '        node["position_m"][1] + 5.0,\n'
        '        node["position_m"][2],\n'
        "    )}\n"
        "    for node in SCENE_NODES\n"
        ")\n",
        encoding="utf-8",
    )

    assert "pivot is ground_center: built geometry must start at y = 0" in validate_kit(
        meta_path, source_path, catalog_path
    )


def test_geometry_wider_than_the_declared_footprint_turns_the_kit_red(tmp_path):
    meta_path, source_path, catalog_path = _kit_copy(tmp_path)
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "\nSCENE_NODES = SCENE_NODES + (\n"
        "    {\n"
        '        "name": "oversize_slab",\n'
        '        "primitive": "box",\n'
        '        "position_m": (0.0, 1.0, 0.0),\n'
        '        "half_extents_m": (400.0, 1.0, 400.0),\n'
        "    },\n"
        ")\n",
        encoding="utf-8",
    )

    errors = validate_kit(meta_path, source_path, catalog_path)

    assert "built X extent must fit the declared footprint width" in errors
    assert "built Z extent must fit the declared footprint length" in errors

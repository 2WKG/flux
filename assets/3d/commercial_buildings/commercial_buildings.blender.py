"""Build a neutral reusable commercial-buildings archetype.

Run: blender --background --python commercial_buildings.blender.py -- /tmp/flux-assets

Generated GLB and 512px preview are handoff artifacts, not checked-in binaries.
2WKG-374 owns storage, import, placement, and accepted-artifact binding.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy

ASSET_ID = "commercial_buildings"
STATUS_MATERIAL = "MAT_STATUS"


def _output_dir() -> Path:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(args) != 1:
        raise SystemExit("pass exactly one output directory after --")
    return Path(args[0]).resolve()


def _cube(
    name: str, location: tuple[float, float, float], scale: tuple[float, float, float]
):
    bpy.ops.mesh.primitive_cube_add(location=location)
    object_ = bpy.context.object
    object_.name = name
    object_.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return object_


def _status_material():
    material = bpy.data.materials.new(STATUS_MATERIAL)
    material.diffuse_color = (0.34, 0.36, 0.39, 1.0)
    return material


def _connector(name: str, location: tuple[float, float, float]) -> None:
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=location)
    connector = bpy.context.object
    connector.name = name
    connector.empty_display_size = 1.0


def _building(
    name: str,
    location: tuple[float, float, float],
    scale: tuple[float, float, float],
    material,
) -> None:
    building = _cube(name, location, scale)
    building.data.materials.append(material)


def build() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.length_unit = "METERS"
    bpy.context.scene["asset_id"] = ASSET_ID
    bpy.context.scene["pivot"] = "ground_center"
    bpy.context.scene["forward_axis"] = "-Z"
    material = _status_material()
    # Neutral office, storefront, and everyday-business massing inside 100m X by 120m -Z.
    _building("office_block", (0.0, 16.0, -15.0), (28.0, 16.0, 34.0), material)
    _building("storefront_west", (-35.0, 6.0, 30.0), (14.0, 6.0, 20.0), material)
    _building("storefront_east", (35.0, 6.0, 30.0), (14.0, 6.0, 20.0), material)
    _building("business_annex", (0.0, 4.0, 42.0), (18.0, 4.0, 12.0), material)
    _connector("CONN_MV_FEED_0", (0.0, 0.0, 50.0))


def export(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=str(output_dir / f"{ASSET_ID}.glb"),
        export_format="GLB",
        export_yup=True,
        export_apply=True,
    )
    scene = bpy.context.scene
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(output_dir / f"{ASSET_ID}.preview.png")
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    build()
    export(_output_dir())

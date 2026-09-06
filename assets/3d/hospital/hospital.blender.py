"""Build the neutral reusable hospital asset.

Run: blender --background --python hospital.blender.py -- /tmp/flux-assets
Generated GLB/PNG remain outside Git; 2WKG-374 owns their storage and placement.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy

ASSET_ID = "hospital"
STATUS_MATERIAL = "MAT_STATUS"


def _output_dir() -> Path:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(args) != 1:
        raise SystemExit("pass exactly one output directory after --")
    return Path(args[0]).resolve()


def _box(
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
    material.diffuse_color = (0.35, 0.37, 0.4, 1.0)
    return material


def build() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.length_unit = "METERS"
    bpy.context.scene["asset_id"] = ASSET_ID
    bpy.context.scene["pivot"] = "ground_center"
    bpy.context.scene["forward_axis"] = "-Z"
    material = _status_material()

    for name, location, scale in (
        ("hospital_wing", (-15.0, 9.0, 0.0), (15.0, 9.0, 22.0)),
        ("hospital_wing", (15.0, 9.0, 0.0), (15.0, 9.0, 22.0)),
        ("hospital_core", (0.0, 14.0, -8.0), (12.0, 14.0, 14.0)),
        ("emergency_entry", (0.0, 3.0, 25.0), (9.0, 3.0, 5.0)),
    ):
        object_ = _box(name, location, scale)
        object_.data.materials.append(material)

    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0.0, 2.0, 30.0))
    connector = bpy.context.object
    connector.name = "CONN_MV_FEED_0"
    connector.empty_display_size = 0.5


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
    scene.render.resolution_x = scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(output_dir / f"{ASSET_ID}.preview.png")
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    build()
    export(_output_dir())

"""Build the neutral, reusable transmission tower and conductor asset.

Run with Blender 4.x (or newer):

    blender --background --python transmission_line_segment.blender.py -- /tmp/flux-assets

The generated GLB and 512px preview are deliberately not committed. The shared
asset contract requires binary artifacts to flow through the placement/import
pipeline, while this source and its metadata make the shape reproducible.
"""

from __future__ import annotations

import sys
from pathlib import Path

import bpy

ASSET_ID = "transmission_line_segment"
STATUS_MATERIAL = "MAT_STATUS"


def _output_dir() -> Path:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(args) != 1:
        raise SystemExit("pass exactly one output directory after --")
    return Path(args[0]).resolve()


def _cube(name: str, location: tuple[float, float, float], scale: tuple[float, float, float]):
    bpy.ops.mesh.primitive_cube_add(location=location)
    object_ = bpy.context.object
    object_.name = name
    object_.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return object_


def _cylinder(
    name: str,
    location: tuple[float, float, float],
    radius: float,
    depth: float,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=8, radius=radius, depth=depth, location=location, rotation=rotation
    )
    object_ = bpy.context.object
    object_.name = name
    return object_


def _status_material():
    material = bpy.data.materials.new(STATUS_MATERIAL)
    material.diffuse_color = (0.34, 0.36, 0.39, 1.0)
    return material


def _assign_status_material(object_, material) -> None:
    object_.data.materials.append(material)


def _connector(name: str, location: tuple[float, float, float]) -> None:
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=location)
    connector = bpy.context.object
    connector.name = name
    connector.empty_display_size = 0.5


def build() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.length_unit = "METERS"
    bpy.context.scene["asset_id"] = ASSET_ID
    bpy.context.scene["pivot"] = "ground_center"
    bpy.context.scene["forward_axis"] = "-Z"

    material = _status_material()
    for x in (-4.5, 4.5):
        for z in (-4.5, 4.5):
            leg = _cylinder("tower_leg", (x, 10.0, z), 0.16, 20.0)
            _assign_status_material(leg, material)
    for y in (12.0, 16.0, 18.0):
        arm = _cube("cross_arm", (0.0, y, 0.0), (5.5, 0.18, 0.18))
        _assign_status_material(arm, material)
    for x in (-4.5, 0.0, 4.5):
        conductor = _cylinder(
            "conductor", (x, 18.0, 0.0), 0.07, 12.0, (1.5708, 0.0, 0.0)
        )
        _assign_status_material(conductor, material)

    _connector("CONN_HV_IN_0", (0.0, 18.0, 6.0))
    _connector("CONN_HV_OUT_0", (0.0, 18.0, -6.0))


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

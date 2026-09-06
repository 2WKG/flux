"""Build the neutral, reusable transmission tower and conductor asset.

Run with Blender 4.x (or newer):

    blender --background --python transmission_line_segment.blender.py -- /tmp/flux-assets

Inspect the geometry this file would build, without Blender:

    python transmission_line_segment.blender.py -- --dry-run

Frames
------
``SCENE_NODES`` and ``CONNECTORS`` are authored in the **contract frame** that
``data/3d/asset-archetypes-v1.json`` declares: metres, **Y up**, ``-Z`` forward,
right-handed, origin on the ground plane at the footprint centre
(``pivot: ground_center``).

Blender's world is **Z up**, so every contract coordinate is converted exactly
once, by :func:`contract_to_blender`, on its way into ``bpy``. The glTF exporter
runs with ``export_yup=True``, whose mapping is ``glTF x = blender x``,
``glTF y = blender z``, ``glTF z = -blender y``. The two compose to the identity::

    gltf_from_blender(contract_to_blender(p)) == p

so what this file authors is what the exported GLB contains, in the frame
``transmission_line_segment.meta.json`` declares. That identity, the derived
bounds, and the connector positions are asserted by
``tests/test_transmission_line_kit.py`` and
``scripts/validate_transmission_line_kit.py`` without Blender installed.

``bpy`` is imported inside the build/export functions rather than at module
scope precisely so the manifest can be derived and validated in an environment
that has no Blender.

The generated GLB and 512px preview are deliberately not committed. The shared
asset contract requires binary artifacts to flow through the placement/import
pipeline, while this source and its metadata make the shape reproducible.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ASSET_ID = "transmission_line_segment"
STATUS_MATERIAL = "MAT_STATUS"

# Contract-frame scene description (metres, Y up, -Z forward, ground_center).
# Every node is axis aligned:
#   box      -> half_extents_m (x, y, z)
#   cylinder -> radius_m, length_m and the contract axis it runs along
SCENE_NODES: tuple[dict[str, object], ...] = (
    {
        "name": "tower_leg_nw",
        "primitive": "cylinder",
        "position_m": (-4.5, 10.0, -4.5),
        "radius_m": 0.16,
        "length_m": 20.0,
        "axis": "y",
    },
    {
        "name": "tower_leg_ne",
        "primitive": "cylinder",
        "position_m": (4.5, 10.0, -4.5),
        "radius_m": 0.16,
        "length_m": 20.0,
        "axis": "y",
    },
    {
        "name": "tower_leg_sw",
        "primitive": "cylinder",
        "position_m": (-4.5, 10.0, 4.5),
        "radius_m": 0.16,
        "length_m": 20.0,
        "axis": "y",
    },
    {
        "name": "tower_leg_se",
        "primitive": "cylinder",
        "position_m": (4.5, 10.0, 4.5),
        "radius_m": 0.16,
        "length_m": 20.0,
        "axis": "y",
    },
    {
        "name": "cross_arm_lower",
        "primitive": "box",
        "position_m": (0.0, 12.0, 0.0),
        "half_extents_m": (5.5, 0.18, 0.18),
    },
    {
        "name": "cross_arm_middle",
        "primitive": "box",
        "position_m": (0.0, 16.0, 0.0),
        "half_extents_m": (5.5, 0.18, 0.18),
    },
    {
        "name": "cross_arm_upper",
        "primitive": "box",
        "position_m": (0.0, 18.0, 0.0),
        "half_extents_m": (5.5, 0.18, 0.18),
    },
    {
        "name": "conductor_west",
        "primitive": "cylinder",
        "position_m": (-4.5, 18.0, 0.0),
        "radius_m": 0.07,
        "length_m": 12.0,
        "axis": "z",
    },
    {
        "name": "conductor_centre",
        "primitive": "cylinder",
        "position_m": (0.0, 18.0, 0.0),
        "radius_m": 0.07,
        "length_m": 12.0,
        "axis": "z",
    },
    {
        "name": "conductor_east",
        "primitive": "cylinder",
        "position_m": (4.5, 18.0, 0.0),
        "radius_m": 0.07,
        "length_m": 12.0,
        "axis": "z",
    },
)

# Geometric attachment points only: a connector asserts no circuit, rating, or
# energisation. Positions are contract-frame and are the same numbers the meta
# publishes; the validator compares the two.
CONNECTORS: tuple[dict[str, object], ...] = (
    {"name": "CONN_HV_IN_0", "position_m": (0.0, 18.0, 6.0)},
    {"name": "CONN_HV_OUT_0", "position_m": (0.0, 18.0, -6.0)},
)

_AXES = ("x", "y", "z")


def contract_to_blender(
    point: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Contract frame (Y up, -Z forward) -> Blender world frame (Z up).

    Inverse of the glTF exporter's ``export_yup=True`` mapping, so a point
    authored here exports to exactly the coordinate it was authored at.
    """
    x, y, z = point
    return (x, -z, y)


def gltf_from_blender(
    point: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Blender world frame -> exported glTF frame, per ``export_yup=True``."""
    x, y, z = point
    return (x, z, -y)


def half_extents_m(node: dict[str, object]) -> tuple[float, float, float]:
    """Contract-frame half extents of one node's axis-aligned bounding box."""
    primitive = node["primitive"]
    if primitive == "box":
        extents = node["half_extents_m"]
        return (float(extents[0]), float(extents[1]), float(extents[2]))
    if primitive == "cylinder":
        radius = float(node["radius_m"])
        half_length = float(node["length_m"]) / 2.0
        return tuple(  # type: ignore[return-value]
            half_length if axis == node["axis"] else radius for axis in _AXES
        )
    raise ValueError(f"unsupported primitive: {primitive!r}")


def node_bounds(
    node: dict[str, object],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Contract-frame (min, max) corners of one node."""
    position = node["position_m"]
    extents = half_extents_m(node)
    minimum = tuple(round(float(position[i]) - extents[i], 6) for i in range(3))
    maximum = tuple(round(float(position[i]) + extents[i], 6) for i in range(3))
    return minimum, maximum  # type: ignore[return-value]


def scene_manifest() -> dict[str, object]:
    """Derive what :func:`build` would create, in the contract frame, no bpy.

    Bounds cover the mesh nodes only: connector empties are attachment markers,
    not geometry, and must not inflate the footprint.
    """
    nodes = []
    for node in SCENE_NODES:
        minimum, maximum = node_bounds(node)
        nodes.append(
            {"name": node["name"], "min_m": list(minimum), "max_m": list(maximum)}
        )
    bounds_min = [round(min(node["min_m"][i] for node in nodes), 6) for i in range(3)]
    bounds_max = [round(max(node["max_m"][i] for node in nodes), 6) for i in range(3)]
    return {
        "asset_id": ASSET_ID,
        "frame": "contract: metre, Y up, -Z forward, right-handed, pivot ground_center",
        "bounds_m": {"min": bounds_min, "max": bounds_max},
        "nodes": nodes,
        "connectors": [
            {"name": connector["name"], "position_m": list(connector["position_m"])}
            for connector in CONNECTORS
        ],
    }


def _cylinder_rotation(axis: str) -> tuple[float, float, float]:
    """Euler rotation putting a Blender cylinder (local +Z) on a contract axis.

    contract y -> blender +z (no rotation); contract z -> blender -y (+90 deg
    about X); contract x -> blender +x (+90 deg about Y).
    """
    if axis == "y":
        return (0.0, 0.0, 0.0)
    if axis == "z":
        return (math.pi / 2.0, 0.0, 0.0)
    if axis == "x":
        return (0.0, math.pi / 2.0, 0.0)
    raise ValueError(f"unsupported cylinder axis: {axis!r}")


def _status_material():
    import bpy

    material = bpy.data.materials.new(STATUS_MATERIAL)
    material.diffuse_color = (0.34, 0.36, 0.39, 1.0)
    return material


def _add_node(node: dict[str, object]):
    import bpy

    location = contract_to_blender(node["position_m"])  # type: ignore[arg-type]
    if node["primitive"] == "box":
        extents = half_extents_m(node)
        bpy.ops.mesh.primitive_cube_add(location=location)
        object_ = bpy.context.object
        object_.scale = (extents[0], extents[2], extents[1])
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    elif node["primitive"] == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=8,
            radius=float(node["radius_m"]),
            depth=float(node["length_m"]),
            location=location,
            rotation=_cylinder_rotation(str(node["axis"])),
        )
        object_ = bpy.context.object
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    else:
        raise ValueError(f"unsupported primitive: {node['primitive']!r}")
    object_.name = str(node["name"])
    return object_


def _add_connector(connector: dict[str, object]) -> None:
    import bpy

    bpy.ops.object.empty_add(
        type="PLAIN_AXES",
        location=contract_to_blender(connector["position_m"]),  # type: ignore[arg-type]
    )
    empty = bpy.context.object
    empty.name = str(connector["name"])
    empty.empty_display_size = 0.5


def build() -> None:
    import bpy

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    scene["asset_id"] = ASSET_ID
    scene["pivot"] = "ground_center"
    scene["forward_axis"] = "-Z"

    material = _status_material()
    for node in SCENE_NODES:
        object_ = _add_node(node)
        object_.data.materials.append(material)
    for connector in CONNECTORS:
        _add_connector(connector)


def _add_preview_camera_and_light() -> None:
    """Add the camera and key light the preview render needs.

    ``build()`` deletes the startup scene, camera included, so a render before
    this runs has no camera. Called after the GLB export so neither object ends
    up in the exported asset.
    """
    import bpy

    bounds = scene_manifest()["bounds_m"]
    minimum, maximum = bounds["min"], bounds["max"]  # type: ignore[index]
    centre = tuple((minimum[i] + maximum[i]) / 2.0 for i in range(3))
    span = max(maximum[i] - minimum[i] for i in range(3)) or 1.0

    bpy.ops.object.empty_add(type="PLAIN_AXES", location=contract_to_blender(centre))
    target = bpy.context.object
    target.name = "PREVIEW_TARGET"

    bpy.ops.object.camera_add(
        location=contract_to_blender(
            (
                centre[0] + span * 1.1,
                centre[1] + span * 0.8,
                centre[2] + span * 1.4,
            )
        )
    )
    camera = bpy.context.object
    camera.name = "PREVIEW_CAMERA"
    track = camera.constraints.new(type="TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    bpy.context.scene.camera = camera

    bpy.ops.object.light_add(
        type="SUN",
        location=contract_to_blender(
            (centre[0] + span, centre[1] + span * 2.0, centre[2] + span)
        ),
    )
    bpy.context.object.name = "PREVIEW_KEY_LIGHT"


def export(output_dir: Path) -> None:
    import bpy

    output_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(output_dir / f"{ASSET_ID}.glb"),
        export_format="GLB",
        export_yup=True,
        export_apply=True,
    )
    _add_preview_camera_and_light()
    scene = bpy.context.scene
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(output_dir / f"{ASSET_ID}.preview.png")
    bpy.ops.render.render(write_still=True)


def _args(argv: list[str]) -> list[str]:
    return argv[argv.index("--") + 1 :] if "--" in argv else []


def main(argv: list[str] | None = None) -> int:
    args = _args(list(sys.argv) if argv is None else list(argv))
    if args == ["--dry-run"]:
        print(json.dumps(scene_manifest(), indent=2))
        return 0
    if len(args) != 1:
        raise SystemExit(
            "pass exactly one output directory after -- (or --dry-run to print "
            "the derived scene manifest without Blender)"
        )
    build()
    export(Path(args[0]).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

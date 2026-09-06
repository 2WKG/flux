"""Build the neutral reusable hospital asset.

Run with Blender 4.x (or newer):

    blender --background --python hospital.blender.py -- /tmp/flux-assets

Inspect the geometry this file would build, without Blender:

    python hospital.blender.py -- --dry-run

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
``hospital.meta.json`` declares. That identity, the derived bounds, and the
connector positions are asserted by ``tests/test_hospital_kit.py`` and
``scripts/validate_hospital_kit.py`` without Blender installed.

``bpy`` is imported inside the build/export functions rather than at module
scope precisely so the manifest can be derived and validated in an environment
that has no Blender.

Generated GLB/PNG remain outside Git; 2WKG-374 owns their storage and placement.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ASSET_ID = "hospital"
STATUS_MATERIAL = "MAT_STATUS"

# Contract-frame scene description (metres, Y up, -Z forward, ground_center).
# Every node is an axis-aligned box given by its centre and half extents.
SCENE_NODES: tuple[dict[str, object], ...] = (
    {
        "name": "hospital_wing_west",
        "primitive": "box",
        "position_m": (-15.0, 9.0, 0.0),
        "half_extents_m": (15.0, 9.0, 22.0),
    },
    {
        "name": "hospital_wing_east",
        "primitive": "box",
        "position_m": (15.0, 9.0, 0.0),
        "half_extents_m": (15.0, 9.0, 22.0),
    },
    {
        "name": "hospital_core",
        "primitive": "box",
        "position_m": (0.0, 14.0, -8.0),
        "half_extents_m": (12.0, 14.0, 14.0),
    },
    {
        "name": "emergency_entry",
        "primitive": "box",
        "position_m": (0.0, 3.0, 25.0),
        "half_extents_m": (9.0, 3.0, 5.0),
    },
)

# Geometric attachment points only: a connector asserts no feeder, capacity, or
# energisation. Positions are contract-frame and are the same numbers the meta
# publishes; the validator compares the two.
CONNECTORS: tuple[dict[str, object], ...] = (
    {"name": "CONN_MV_FEED_0", "position_m": (0.0, 2.0, 30.0)},
)


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


def _status_material():
    import bpy

    material = bpy.data.materials.new(STATUS_MATERIAL)
    material.diffuse_color = (0.35, 0.37, 0.4, 1.0)
    return material


def _add_node(node: dict[str, object]):
    import bpy

    location = contract_to_blender(node["position_m"])  # type: ignore[arg-type]
    if node["primitive"] != "box":
        raise ValueError(f"unsupported primitive: {node['primitive']!r}")
    extents = half_extents_m(node)
    bpy.ops.mesh.primitive_cube_add(location=location)
    object_ = bpy.context.object
    object_.scale = (extents[0], extents[2], extents[1])
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
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

"""Run with Blender --background --factory-startup --python build_pack.py -- --output DIR.

Builds geometry into one editable scene per archetype/LOD, exports GLB, measures
metadata, and optionally renders 512px alpha thumbnails. No user scene touched.
"""

import argparse
import importlib
import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

SOURCE = Path(__file__).resolve().parents[1]
CATALOG = SOURCE / "asset-archetypes-v1.json"
# Blender executes this script directly; the sibling generators are source modules.
for folder in (
    "pipeline",
    "transmission",
    "grid",
    "generation",
    "critical",
    "district",
):
    sys.path.insert(0, str(SOURCE / folder))
sys.path.insert(0, str(SOURCE))

MODULES = {
    "transmission_line_segment": "transmission_assets",
    "substation_transformer_yard": "grid_assets",
    "wind_turbine": "grid_assets",
    "solar_array": "grid_assets",
    "battery_storage": "grid_assets",
    "coal_plant_retiring_site": "generation_models",
    "nuclear_smr_module": "generation_models",
    "natural_gas_plant": "generation_models",
    "military_base": "critical_assets",
    "hospital": "critical_assets",
    "water_treatment_plant": "critical_assets",
    "school_emergency_services": "critical_assets",
    "data_center_campus": "district.geometry",
    "residential_neighborhood": "district.geometry",
    "commercial_buildings": "district.geometry",
    "factory_industrial_facility": "district.geometry",
    "warehouse_logistics_center": "district.geometry",
    "ev_charging_station": "district.geometry",
}


def triangle_count(objects):
    return sum(
        sum(len(p.vertices) - 2 for p in o.data.polygons)
        for o in objects
        if o.type == "MESH"
    )


def bounds(objects):
    coords = [
        o.matrix_world @ v.co
        for o in objects
        if o.type == "MESH"
        for v in o.data.vertices
    ]
    low = [min(v[i] for v in coords) for i in range(3)]
    high = [max(v[i] for v in coords) for i in range(3)]
    return {"min": low, "max": high, "size": [high[i] - low[i] for i in range(3)]}


def scene_new(name):
    scene = bpy.data.scenes.new(name)
    bpy.context.window.scene = scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1
    return scene


def normalize_meshes(objects):
    for o in objects:
        if o.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        remaining = set(bm.faces)
        while remaining:
            seed = remaining.pop()
            component = {seed}
            pending = [seed]
            while pending:
                face = pending.pop()
                for edge in face.edges:
                    for neighbor in edge.link_faces:
                        if neighbor in remaining:
                            remaining.remove(neighbor)
                            component.add(neighbor)
                            pending.append(neighbor)
            if not all(len(e.link_faces) == 2 for f in component for e in f.edges):
                continue
            volume = 0.0
            for face in component:
                points = [v.co for v in face.verts]
                for k in range(1, len(points) - 1):
                    volume += points[0].dot(points[k].cross(points[k + 1])) / 6
            if volume < -1e-8:
                bmesh.ops.reverse_faces(bm, faces=list(component))
        bm.to_mesh(o.data)
        bm.free()
        o.data.update()


def export(objects, path):
    for obj in bpy.data.objects:
        if obj.name.startswith("CONN_"):
            obj.name = "STORED_" + obj.name
    for obj in objects:
        if obj.type == "EMPTY":
            obj.name = obj.get(
                "connector_name", obj.name.removeprefix("STORED_").split(".")[0]
            )
    bpy.ops.object.select_all(action="DESELECT")
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = next(o for o in objects if o.type == "MESH")
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        use_active_scene=True,
        export_yup=True,
        export_apply=True,
        export_materials="EXPORT",
        export_cameras=False,
        export_lights=False,
        export_extras=True,
        export_animations=False,
    )


def studio(scene, box, resolution=(512, 512), alpha=True):
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 8
    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = alpha
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.world = bpy.data.worlds.new(scene.name + "_world")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs[0].default_value = (
        0.08,
        0.12,
        0.16,
        1,
    )
    scene.world.node_tree.nodes["Background"].inputs[1].default_value = 0.55
    center = Vector([(box["min"][i] + box["max"][i]) / 2 for i in range(3)])
    extent = max(box["size"])
    cam_data = bpy.data.cameras.new(scene.name + "_camera")
    cam = bpy.data.objects.new("StudioCamera", cam_data)
    scene.collection.objects.link(cam)
    cam.location = center + Vector((1.15, 1.5, 1.05)) * extent
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = extent * 1.60
    scene.camera = cam
    for name, offset, energy, color, size in [
        ("Key", (-0.6, 1, 2), 1800, (0.72, 0.9, 1), 1.4),
        ("Fill", (1, 0.2, 1), 1200, (0.25, 0.75, 1), 1),
        ("Rim", (0, -1.2, 1.6), 2000, (0.7, 0.94, 1), 1.1),
    ]:
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy * (extent / 10) ** 2
        data.color = color
        data.shape = "DISK"
        data.size = extent * size
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
        obj.location = center + Vector(offset) * extent
        obj.rotation_euler = (center - obj.location).to_track_quat("-Z", "Y").to_euler()
    return cam


def preview(asset_id, objects, box, path):
    scene = scene_new("Preview_" + asset_id)
    for obj in objects:
        scene.collection.objects.link(obj)
    studio(scene, box)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Generated pack directory; contains assets/, source/ and validation/.",
    )
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--save-name", default="flux_grid_assets.blend")
    args = parser.parse_args(
        sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    )
    output = args.output.expanduser().resolve()
    if output == SOURCE.parent or output.is_relative_to(SOURCE):
        parser.error(
            "--output must be separate from the tracked pack and source directory"
        )
    if Path(args.save_name).name != args.save_name or not args.save_name.endswith(
        ".blend"
    ):
        parser.error("--save-name must be a .blend filename without a directory")
    catalog = json.loads(args.catalog.expanduser().read_text())
    available = {entry["id"] for entry in catalog["archetypes"]}
    if args.ids and (unknown := set(args.ids) - available):
        parser.error("unknown archetype ids: " + ", ".join(sorted(unknown)))
    for directory in ("assets", "source", "validation"):
        (output / directory).mkdir(parents=True, exist_ok=True)
    reports = []
    for entry in catalog["archetypes"]:
        aid = entry["id"]
        if args.ids and aid not in args.ids:
            continue
        for old in list(bpy.data.scenes):
            if old.name.startswith(aid + "_LOD") or old.name == "Preview_" + aid:
                bpy.data.scenes.remove(old)
        for old in list(bpy.data.objects):
            if old.users == 0:
                bpy.data.objects.remove(old)
        module = importlib.import_module(MODULES[aid])
        counts = []
        lod_boxes = []
        lod0_objects = None
        connectors = None
        target = output / "assets" / aid
        target.mkdir(parents=True, exist_ok=True)
        for lod in (0, 1, 2):
            scene_new(aid + "_LOD" + str(lod))
            builder = module.build(aid, lod)
            objects = builder.finish()
            normalize_meshes(objects)
            bpy.context.view_layer.update()
            count = triangle_count(objects)
            box = bounds(objects)
            counts.append(count)
            lod_boxes.append(box)
            filename = aid + ("" if lod == 0 else ".lod" + str(lod)) + ".glb"
            export(objects, target / filename)
            if lod == 0:
                lod0_objects = objects
                connectors = [
                    {
                        "name": n,
                        "role": n.split("_")[1] + "_" + n.split("_")[2],
                        "position": [float(p[0]), float(p[2]), -float(p[1])],
                    }
                    for n, p in builder.sockets.items()
                ]
                custom = builder.metadata
            print(
                "FLUX_EXPORT "
                + json.dumps(
                    {
                        "id": aid,
                        "lod": lod,
                        "triangles": count,
                        "bounds_blender": box,
                        "file": str(target / filename),
                    }
                ),
                flush=True,
            )
        meta = {
            "archetype_id": aid,
            "contract_id": catalog["contractId"],
            "triangles_lod0": counts[0],
            "triangles_lod1": counts[1],
            "triangles_lod2": counts[2],
            "footprint_m": entry["footprint_m"],
            "connectors": connectors,
            "author": "OpenAI Codex for Joshua",
            "license": "CC0-1.0",
            "source_of_shape": custom.get(
                "source_of_shape",
                "Original procedural geometry authored for this Flux asset pack; no external meshes or textures.",
            ),
            "transform": catalog["transform"],
            "bounds_m": {
                "min": [
                    lod_boxes[0]["min"][0],
                    lod_boxes[0]["min"][2],
                    -lod_boxes[0]["max"][1],
                ],
                "max": [
                    lod_boxes[0]["max"][0],
                    lod_boxes[0]["max"][2],
                    -lod_boxes[0]["min"][1],
                ],
            },
            "bounds_blender_m": lod_boxes[0],
            "lod_bounds_blender_m": lod_boxes,
            "geometry_limit": entry["limit"],
            "materials": {
                "status": "MAT_STATUS",
                "decorative_accent": "MAT_ACCENT",
                "status_tint_baked": False,
            },
            "preview": aid + ".preview.png",
            "lod_files": {
                "lod0": aid + ".glb",
                "lod1": aid + ".lod1.glb",
                "lod2": aid + ".lod2.glb",
            },
        }
        for key in ("shape_reference_urls", "shape_revision", "shape_note"):
            if key in custom:
                meta[key] = custom[key]
        (target / (aid + ".meta.json")).write_text(json.dumps(meta, indent=2) + "\n")
        reports.append(meta)
        if not args.no_render:
            preview(aid, lod0_objects, lod_boxes[0], target / (aid + ".preview.png"))
        if counts[1] > counts[0] * 0.4 or counts[2] > counts[0] * 0.12:
            print("FLUX_LOD_RATIO_FAIL " + aid + " " + str(counts), flush=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output / "source" / args.save_name))
    (output / "validation" / ("build-report-" + args.save_name + ".json")).write_text(
        json.dumps(reports, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()

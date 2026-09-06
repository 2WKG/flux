"""Flux procedural geometry helper. No scene changes until Builder.finish().

Workers expose build(asset_id: str, lod: int) -> Builder. Meters, Z-up, +Y front.
LOD0 close; LOD1 map. All functions append batched geometry by material.
"""

import math
from collections import defaultdict

import bpy
from mathutils import Vector

PALETTE = {
    "graphite": ((0.048, 0.082, 0.105, 1), 0.36, 0.52, 0),
    "graphite_light": ((0.13, 0.21, 0.25, 1), 0.30, 0.46, 0),
    "glass": ((0.14, 0.66, 0.75, 0.20), 0.04, 0.28, 0.15),
    "edge": ((0.08, 0.80, 0.91, 1), 0.12, 0.35, 1.7),
    "white": ((0.62, 0.89, 0.93, 1), 0.12, 0.38, 0.40),
    "amber": ((1.0, 0.46, 0.12, 1), 0.10, 0.42, 1.0),
    "status": ((0.55, 0.55, 0.55, 1), 0.10, 0.50, 0),
}


def material(key):
    name = {"status": "MAT_STATUS", "edge": "MAT_ACCENT"}.get(key, "MAT_" + key.upper())
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    rgba, metallic, roughness, emission = PALETTE[key]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = rgba
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = rgba
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Alpha"].default_value = rgba[3]
    shader.inputs["Emission Color"].default_value = rgba
    shader.inputs["Emission Strength"].default_value = emission
    if key == "glass":
        mat.surface_render_method = "BLENDED"
        mat.use_transparency_overlap = False
        mat.use_backface_culling = False
    return mat


class Builder:
    def __init__(self, asset_id, lod):
        self.asset_id, self.lod = asset_id, lod
        self.parts = defaultdict(lambda: [[], []])
        self.sockets = {}
        self.metadata = {}

    def mesh(self, name, vertices, faces, material="graphite"):
        verts, polys = self.parts[material]
        offset = len(verts)
        verts.extend(tuple(float(c) for c in v) for v in vertices)
        polys.extend(tuple(offset + i for i in face) for face in faces)
        return self

    def connector(self, role, index, point):
        self.sockets[f"CONN_{role}_{index}"] = tuple(point)
        return self

    def box(self, name, center, size, material="graphite", bevel=0, rotation=None):
        x, y, z = (s / 2 for s in size)
        verts = [
            (-x, -y, -z),
            (-x, -y, z),
            (-x, y, -z),
            (-x, y, z),
            (x, -y, -z),
            (x, -y, z),
            (x, y, -z),
            (x, y, z),
        ]
        if rotation is not None:
            from mathutils import Euler

            mat = Euler(rotation).to_matrix()
            verts = [mat @ Vector(v) for v in verts]
        verts = [Vector(v) + Vector(center) for v in verts]
        faces = [
            (0, 4, 6, 2),
            (1, 3, 7, 5),
            (0, 1, 5, 4),
            (2, 6, 7, 3),
            (0, 2, 3, 1),
            (4, 5, 7, 6),
        ]
        # Bevel is intentionally a hint: clean box topology survives low LOD.
        return self.mesh(name, verts, [tuple(reversed(f)) for f in faces], material)

    def beam(self, name, start, end, width, material="edge"):
        a, b = Vector(start), Vector(end)
        delta = b - a
        if delta.length < 1e-8:
            return self
        q = delta.to_track_quat("Z", "Y")
        w = width / 2
        length = delta.length / 2
        verts = [
            (sx * w, sy * w, sz * length)
            for sx in (-1, 1)
            for sy in (-1, 1)
            for sz in (-1, 1)
        ]
        verts = [q @ Vector(v) + (a + b) / 2 for v in verts]
        faces = [
            (0, 4, 6, 2),
            (1, 3, 7, 5),
            (0, 1, 5, 4),
            (2, 6, 7, 3),
            (0, 2, 3, 1),
            (4, 5, 7, 6),
        ]
        return self.mesh(name, verts, [tuple(reversed(f)) for f in faces], material)

    def cylinder(
        self,
        name,
        center,
        radius,
        depth,
        material="graphite",
        vertices=None,
        radius_top=None,
        rotation=None,
    ):
        n = vertices or (24 if self.lod == 0 else 12 if self.lod == 1 else 6)
        top = radius if radius_top is None else radius_top
        verts = []
        for z, r in ((-depth / 2, radius), (depth / 2, top)):
            verts.extend(
                (r * math.cos(i * math.tau / n), r * math.sin(i * math.tau / n), z)
                for i in range(n)
            )
        if rotation is not None:
            from mathutils import Euler

            mat = Euler(rotation).to_matrix()
            verts = [mat @ Vector(v) for v in verts]
        verts = [Vector(v) + Vector(center) for v in verts]
        faces = [tuple(reversed(range(n))), tuple(range(n, n * 2))]
        faces.extend((i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n))
        return self.mesh(name, verts, faces, material)

    def ring(self, name, center, radius, tube, material="edge", segments=None):
        n = segments or (32 if self.lod == 0 else 16 if self.lod == 1 else 8)
        pts = [
            (
                center[0] + radius * math.cos(i * math.tau / n),
                center[1] + radius * math.sin(i * math.tau / n),
                center[2],
            )
            for i in range(n + 1)
        ]
        return self.polyline(name, pts, tube, material)

    def polyline(self, name, points, radius, material="edge", sides=None):
        n = sides or (6 if self.lod == 0 else 4)
        verts = []
        for i, pt in enumerate(points):
            a = Vector(points[max(0, i - 1)])
            b = Vector(points[min(len(points) - 1, i + 1)])
            q = (b - a).to_track_quat("Z", "Y")
            verts.extend(
                q
                @ Vector(
                    (
                        radius * math.cos(j * math.tau / n),
                        radius * math.sin(j * math.tau / n),
                        0,
                    )
                )
                + Vector(pt)
                for j in range(n)
            )
        faces = [
            tuple(reversed(range(n))),
            tuple(range((len(points) - 1) * n, len(points) * n)),
        ]
        for k in range(len(points) - 1):
            faces.extend(
                (
                    k * n + j,
                    k * n + (j + 1) % n,
                    (k + 1) * n + (j + 1) % n,
                    (k + 1) * n + j,
                )
                for j in range(n)
            )
        return self.mesh(name, verts, faces, material)

    def ellipsoid(
        self, name, center, scale, material="glass", segments=None, rings=None
    ):
        n = segments or (24 if self.lod == 0 else 12 if self.lod == 1 else 6)
        m = rings or (12 if self.lod == 0 else 6 if self.lod == 1 else 3)
        verts = [(center[0], center[1], center[2] - scale[2])]
        for j in range(1, m):
            phi = -math.pi / 2 + j * math.pi / m
            verts.extend(
                (
                    center[0] + scale[0] * math.cos(phi) * math.cos(i * math.tau / n),
                    center[1] + scale[1] * math.cos(phi) * math.sin(i * math.tau / n),
                    center[2] + scale[2] * math.sin(phi),
                )
                for i in range(n)
            )
        top = len(verts)
        verts.append((center[0], center[1], center[2] + scale[2]))
        faces = [(0, 1 + (i + 1) % n, 1 + i) for i in range(n)]
        for j in range(m - 2):
            a = 1 + j * n
            b = a + n
            faces.extend(
                (a + i, a + (i + 1) % n, b + (i + 1) % n, b + i) for i in range(n)
            )
        a = 1 + (m - 2) * n
        faces.extend((a + i, a + (i + 1) % n, top) for i in range(n))
        return self.mesh(name, verts, faces, material)

    def outline_box(
        self, name, center, size, width=0.12, material="edge", vertical=True
    ):
        x, y, z = (s / 2 for s in size)
        cx, cy, cz = center
        for h in (-z, z):
            self.polyline(
                name,
                [
                    (cx - x, cy - y, cz + h),
                    (cx + x, cy - y, cz + h),
                    (cx + x, cy + y, cz + h),
                    (cx - x, cy + y, cz + h),
                    (cx - x, cy - y, cz + h),
                ],
                width / 2,
                material,
            )
        if vertical:
            for dx, dy in ((-x, -y), (-x, y), (x, -y), (x, y)):
                self.beam(
                    name,
                    (cx + dx, cy + dy, cz - z),
                    (cx + dx, cy + dy, cz + z),
                    width,
                    material,
                )
        return self

    def finish(self, collection=None):
        collection = collection or bpy.context.scene.collection
        objects = []
        for key, (verts, faces) in self.parts.items():
            if not verts:
                continue
            mesh = bpy.data.meshes.new(self.asset_id + "_" + key)
            mesh.from_pydata(verts, [], faces)
            mesh.update()
            obj = bpy.data.objects.new(self.asset_id + "_" + key, mesh)
            collection.objects.link(obj)
            obj.data.materials.append(material(key))
            obj["asset_id"] = self.asset_id
            obj["lod"] = self.lod
            objects.append(obj)
        for name, point in self.sockets.items():
            obj = bpy.data.objects.new(name, None)
            obj["connector_name"] = name
            obj.location = point
            obj.empty_display_size = 0.3
            collection.objects.link(obj)
            objects.append(obj)
        return objects

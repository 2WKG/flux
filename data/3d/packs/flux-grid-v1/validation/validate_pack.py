"""Independent Flux GLB audit; standard library only, no Blender or GPU needed.

This measures default-scene triangles and transformed referenced positions.
It is a focused pack audit, not a replacement for the Khronos glTF validator.
Unsupported compressed, sparse, skinned, morphing or instanced geometry fails
explicitly instead of pretending its bounds were checked.

Pass --root as the generated pack directory containing assets/. The default
catalog is the tracked source catalog beside this validation directory.
"""

from __future__ import annotations

import argparse
import binascii
import collections
import datetime
import hashlib
import json
import math
import re
import struct
import sys
import zlib
from pathlib import Path

DEFAULT_CATALOG = (
    Path(__file__).resolve().parents[1] / "source/asset-archetypes-v1.json"
)
COMPONENTS = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
IDENTITY = [[float(i == j) for j in range(4)] for i in range(4)]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    if isinstance(value, float):
        require(math.isfinite(value), "non-finite JSON number")
    elif isinstance(value, dict):
        for item in value.values():
            finite(item)
    elif isinstance(value, list):
        for item in value:
            finite(item)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def product(a, b):
    return [
        [sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)
    ]


def point(matrix, xyz):
    v = (*xyz, 1)
    result = [sum(matrix[i][j] * v[j] for j in range(4)) for i in range(4)]
    require(abs(result[3] - 1) < 1e-6, "non-affine node matrix")
    require(all(math.isfinite(x) for x in result), "non-finite world position")
    return result[:3]


def node_matrix(node):
    if "matrix" in node:
        require(
            not any(k in node for k in ("translation", "rotation", "scale")),
            "matrix and TRS coexist",
        )
        m = node["matrix"]
        require(len(m) == 16, "matrix must have 16 entries")
        return [[m[j * 4 + i] for j in range(4)] for i in range(4)]
    t, q, s = (
        node.get("translation", [0, 0, 0]),
        node.get("rotation", [0, 0, 0, 1]),
        node.get("scale", [1, 1, 1]),
    )
    require(len(t) == len(s) == 3 and len(q) == 4, "invalid TRS size")
    require(abs(sum(v * v for v in q) - 1) < 1e-4, "non-unit rotation quaternion")
    x, y, z, w = q
    r = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    return [[r[i][j] * s[j] for j in range(3)] + [t[i]] for i in range(3)] + [
        [0, 0, 0, 1]
    ]


class GLB:
    def __init__(self, raw):
        require(len(raw) >= 20, "truncated GLB")
        magic, version, length = struct.unpack_from("<4sII", raw)
        require(
            magic == b"glTF" and version == 2 and length == len(raw),
            "invalid GLB header or byte length",
        )
        chunks, offset = [], 12
        while offset < length:
            require(offset + 8 <= length, "truncated chunk header")
            size, kind = struct.unpack_from("<II", raw, offset)
            require(
                size % 4 == 0 and offset + 8 + size <= length,
                "invalid chunk size/alignment",
            )
            chunks.append((kind, raw[offset + 8 : offset + 8 + size]))
            offset += 8 + size
        require(chunks[0][0] == 0x4E4F534A, "first chunk is not JSON")
        require(
            len(chunks) == 2 and chunks[1][0] == 0x004E4942,
            "expected JSON plus one embedded BIN chunk",
        )
        self.doc = json.loads(chunks[0][1])
        finite(self.doc)
        self.bin = chunks[1][1]
        self.cache = {}
        require(
            self.doc.get("asset", {}).get("version") == "2.0",
            "asset.version is not 2.0",
        )
        buffers = self.doc.get("buffers", [])
        require(
            len(buffers) == 1 and "uri" not in buffers[0],
            "expected one embedded buffer and no buffer URI",
        )
        require(
            0 <= len(self.bin) - buffers[0]["byteLength"] <= 3,
            "BIN byteLength/padding mismatch",
        )
        for view in self.doc.get("bufferViews", []):
            require(view.get("buffer") == 0, "bufferView uses non-embedded buffer")
            require(
                view.get("byteOffset", 0) >= 0 and view["byteLength"] >= 0,
                "negative bufferView extent",
            )
            require(
                view.get("byteOffset", 0) + view["byteLength"]
                <= buffers[0]["byteLength"],
                "bufferView outside buffer",
            )
            require(
                "EXT_meshopt_compression" not in view.get("extensions", {}),
                "meshopt bounds unverified",
            )
        for image in self.doc.get("images", []):
            require(
                "uri" not in image,
                "image URI present; single-file embedded images required",
            )
        require(
            not self.doc.get("skins") and not self.doc.get("animations"),
            "skinned/animated world bounds unsupported",
        )
        require(not self.doc.get("cameras"), "camera leaked into asset")
        require(
            "KHR_lights_punctual" not in self.doc.get("extensions", {}),
            "lights leaked into asset",
        )

    def accessor(self, index):
        if index in self.cache:
            return self.cache[index]
        accessors = self.doc.get("accessors", [])
        require(
            isinstance(index, int) and 0 <= index < len(accessors),
            "invalid accessor index",
        )
        a = accessors[index]
        require(
            "sparse" not in a, "sparse accessor requires independent decode support"
        )
        require(
            a.get("type") in WIDTHS and a.get("componentType") in COMPONENTS,
            "unsupported accessor type",
        )
        require("bufferView" in a, "accessor has no bufferView")
        vi = a["bufferView"]
        require(
            isinstance(vi, int) and 0 <= vi < len(self.doc.get("bufferViews", [])),
            "invalid bufferView index",
        )
        v = self.doc["bufferViews"][vi]
        code, width = COMPONENTS[a["componentType"]]
        count, arity = a["count"], WIDTHS[a["type"]]
        require(
            isinstance(count, int) and 0 < count <= 5_000_000,
            "invalid or excessive accessor count",
        )
        stride = v.get("byteStride", width * arity)
        local = a.get("byteOffset", 0)
        start = v.get("byteOffset", 0) + local
        require(
            stride >= width * arity and stride % width == 0 and start % width == 0,
            "accessor alignment/stride invalid",
        )
        require(
            local >= 0
            and local + (count - 1) * stride + width * arity <= v["byteLength"],
            "accessor exceeds bufferView",
        )
        values = [
            struct.unpack_from("<" + code * arity, self.bin, start + i * stride)
            for i in range(count)
        ]
        require(
            all(math.isfinite(v) for row in values for v in row),
            "non-finite accessor value",
        )
        if a.get("normalized"):
            c = a["componentType"]
            require(c in (5120, 5121, 5122, 5123), "invalid normalized component type")
            divisor = {5120: 127, 5121: 255, 5122: 32767, 5123: 65535}[c]
            values = [tuple(max(-1, x / divisor) for x in row) for row in values]
        self.cache[index] = values
        return values


def topology(positions, triangles, winding_sign=1):
    """Weld exact rounded position seams; check closed connected components.

    Signed volume is an orientation diagnostic only for closed components.
    Open/nonmanifold components are counted, never reported as proven outward.
    """
    key_ids, remap = {}, []
    for p in positions:
        key = tuple(round(v, 7) for v in p)
        if key not in key_ids:
            key_ids[key] = len(key_ids)
        remap.append(key_ids[key])
    parent = list(range(len(triangles)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edge_faces = collections.defaultdict(list)
    for i, (a, b, c) in enumerate(triangles):
        for x, y in ((a, b), (b, c), (c, a)):
            edge_faces[tuple(sorted((remap[x], remap[y])))].append(i)
    # Surfaces touching at only one point remain separate closed components.
    for faces in edge_faces.values():
        for i in faces[1:]:
            parent[root(i)] = root(faces[0])
    groups = collections.defaultdict(list)
    for i, triangle in enumerate(triangles):
        groups[root(i)].append(triangle)
    closed, inward, open_count, degenerate = 0, [], 0, 0
    for tris in groups.values():
        edges = collections.Counter()
        volume6 = 0.0
        for ia, ib, ic in tris:
            a, b, c = positions[ia], positions[ib], positions[ic]
            u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
            cross = (
                u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0],
            )
            degenerate += sum(x * x for x in cross) < 1e-18
            volume6 += (
                a[0] * (b[1] * c[2] - b[2] * c[1])
                + a[1] * (b[2] * c[0] - b[0] * c[2])
                + a[2] * (b[0] * c[1] - b[1] * c[0])
            )
            for x, y in ((ia, ib), (ib, ic), (ic, ia)):
                edges[(remap[x], remap[y])] += 1
        is_closed = all(
            x != y and n == 1 and edges.get((y, x)) == 1 for (x, y), n in edges.items()
        )
        if is_closed:
            closed += 1
            if volume6 * winding_sign < -1e-8:
                coords = [positions[i] for t in tris for i in t]
                inward.append(
                    {
                        "triangles": len(tris),
                        "signed_volume_m3": volume6 / 6,
                        "bounds_min_m": [min(p[i] for p in coords) for i in range(3)],
                        "bounds_max_m": [max(p[i] for p in coords) for i in range(3)],
                    }
                )
        else:
            open_count += 1
    return {
        "closed_components": closed,
        "inward_closed_components": inward,
        "open_or_nonmanifold_components": open_count,
        "degenerate_triangles": degenerate,
    }


def png_info(raw, require_nonempty=True):
    require(raw[:8] == b"\x89PNG\r\n\x1a\n", "not PNG")
    offset, compressed, header, ended = 8, [], None, False
    while offset < len(raw):
        require(offset + 12 <= len(raw), "truncated PNG chunk")
        size = struct.unpack_from(">I", raw, offset)[0]
        kind, data = raw[offset + 4 : offset + 8], raw[offset + 8 : offset + 8 + size]
        require(offset + size + 12 <= len(raw), "PNG chunk outside file")
        crc = struct.unpack_from(">I", raw, offset + size + 8)[0]
        require(binascii.crc32(kind + data) & 0xFFFFFFFF == crc, "PNG CRC mismatch")
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            compressed.append(data)
        elif kind == b"IEND":
            ended = True
        offset += size + 12
    require(header is not None and ended, "PNG header/end missing")
    w, h, depth, color, compression, filt, interlace = header
    require(
        w > 0 and h > 0 and w * h <= 2048 * 2048, "PNG dimensions exceed audit bound"
    )
    require(
        depth in (8, 16)
        and color in (2, 6)
        and (compression, filt, interlace) == (0, 0, 0),
        "unsupported PNG encoding for pixel audit",
    )
    channels, byte_depth = (4 if color == 6 else 3), depth // 8
    bpp, row_size = channels * byte_depth, w * channels * byte_depth
    pixels = zlib.decompress(b"".join(compressed))
    require(len(pixels) == h * (row_size + 1), "PNG decompressed size mismatch")
    previous, values, alphas = bytearray(row_size), [], []
    for y in range(h):
        filter_type = pixels[y * (row_size + 1)]
        require(filter_type <= 4, "invalid PNG row filter")
        row = bytearray(pixels[y * (row_size + 1) + 1 : (y + 1) * (row_size + 1)])
        for x in range(row_size):
            a, b, c = (
                row[x - bpp] if x >= bpp else 0,
                previous[x],
                previous[x - bpp] if x >= bpp else 0,
            )
            if filter_type == 1:
                predictor = a
            elif filter_type == 2:
                predictor = b
            elif filter_type == 3:
                predictor = (a + b) // 2
            elif filter_type == 4:
                p = a + b - c
                distances = (abs(p - a), abs(p - b), abs(p - c))
                predictor = (a, b, c)[distances.index(min(distances))]
            else:
                predictor = 0
            row[x] = (row[x] + predictor) & 255
        for x in range(w):
            p = tuple(
                int.from_bytes(
                    row[x * bpp + c * byte_depth : x * bpp + (c + 1) * byte_depth],
                    "big",
                )
                for c in range(channels)
            )
            values.append(p[:3])
            alphas.append(p[3] if channels == 4 else (1 << depth) - 1)
        previous = row
    histogram = collections.Counter(values)
    nonuniform = len(histogram) > 1
    if require_nonempty:
        require(
            nonuniform and max(alphas) > 0, "preview is uniform or fully transparent"
        )
    return {
        "width": w,
        "height": h,
        "bit_depth": depth,
        "color_type": color,
        "alpha_channel": channels == 4,
        "alpha_min": min(alphas),
        "alpha_max": max(alphas),
        "visible_pixels": sum(a > 0 for a in alphas),
        "unique_rgb_colors": len(histogram),
        "most_common_rgb_share": max(histogram.values()) / (w * h),
    }


def audit_glb(path, entry, catalog):
    result = {
        "path": str(path),
        "sha256": sha(path),
        "bytes": path.stat().st_size,
        "errors": [],
        "warnings": [],
    }
    require(
        result["bytes"] <= catalog["budgets"]["perArchetypeFileBytes"],
        "GLB exceeds 3 MiB",
    )
    glb = GLB(path.read_bytes())
    doc, materials, nodes = (
        glb.doc,
        glb.doc.get("materials", []),
        glb.doc.get("nodes", []),
    )
    for ai in range(len(doc.get("accessors", []))):
        glb.accessor(ai)
    status = [i for i, m in enumerate(materials) if m.get("name") == "MAT_STATUS"]
    require(len(status) == 1, "exactly one MAT_STATUS required")
    result["materials"] = []
    for i, material in enumerate(materials):
        pbr = material.get("pbrMetallicRoughness", {})
        rgba = pbr.get("baseColorFactor", [1, 1, 1, 1])
        mode = material.get("alphaMode", "OPAQUE")
        require(
            len(rgba) == 4 and all(0 <= v <= 1 for v in rgba),
            "invalid material baseColorFactor",
        )
        require(mode in ("OPAQUE", "MASK", "BLEND"), "invalid alphaMode")
        if i == status[0]:
            require(
                max(rgba[:3]) - min(rgba[:3]) <= 1e-6
                and rgba[3] == 1
                and mode == "OPAQUE",
                "MAT_STATUS must be neutral, opaque gray",
            )
            require(
                "baseColorTexture" not in pbr and "emissiveTexture" not in material,
                "MAT_STATUS texture can bake a state",
            )
            extensions = material.get("extensions", {})
            require(
                set(extensions) <= {"KHR_materials_emissive_strength"},
                "MAT_STATUS shading extension neutrality unverified",
            )
            strength = extensions.get("KHR_materials_emissive_strength", {}).get(
                "emissiveStrength", 1
            )
            require(
                isinstance(strength, (int, float)) and strength >= 0,
                "invalid emissive strength",
            )
            require(
                max(material.get("emissiveFactor", [0, 0, 0])) * strength <= 1e-7,
                "MAT_STATUS emits a baked color",
            )
        result["materials"].append(
            {
                "name": material.get("name"),
                "rgba": rgba,
                "alpha_mode": mode,
                "double_sided": material.get("doubleSided", False),
                "emissive": material.get("emissiveFactor", [0, 0, 0]),
            }
        )
    for image in doc.get("images", []):
        require(
            "bufferView" in image and image.get("mimeType") == "image/png",
            "embedded non-PNG texture dimensions unverified",
        )
        view = doc["bufferViews"][image["bufferView"]]
        image_info = png_info(
            glb.bin[
                view.get("byteOffset", 0) : view.get("byteOffset", 0)
                + view["byteLength"]
            ],
            require_nonempty=False,
        )
        require(
            max(image_info["width"], image_info["height"])
            <= catalog["budgets"]["textureMaxPixels"],
            "texture exceeds 2048px",
        )
    require(doc.get("scenes") and "scene" in doc, "default scene required")
    require(0 <= doc["scene"] < len(doc["scenes"]), "invalid default scene")
    bounds_min, bounds_max = [math.inf] * 3, [-math.inf] * 3
    visited, connectors, used_materials, topology_rows = set(), {}, set(), []
    triangle_count, primitive_count = 0, 0

    def visit(index, parent, ancestors):
        nonlocal triangle_count, primitive_count
        require(
            isinstance(index, int) and 0 <= index < len(nodes), "invalid node index"
        )
        require(index not in ancestors, "node cycle")
        require(index not in visited, "multiple node parents or duplicate roots")
        visited.add(index)
        node = nodes[index]
        name = node.get("name", "")
        require(
            "camera" not in node
            and "KHR_lights_punctual" not in node.get("extensions", {}),
            "camera/light node contamination",
        )
        require(
            not re.search(
                r"^(preview|camera|light|backdrop)([._]|$)", name, re.IGNORECASE
            ),
            "preview-scene object leaked: " + name,
        )
        require(
            "EXT_mesh_gpu_instancing" not in node.get("extensions", {}),
            "GPU instance transforms unverified",
        )
        matrix = product(parent, node_matrix(node))
        if name.startswith("CONN_"):
            require(
                re.fullmatch(r"CONN_(HV_IN|HV_OUT|MV_FEED)_\d+", name),
                "invalid connector name " + name,
            )
            require(name not in connectors, "duplicate connector " + name)
            require(
                not any(k in node for k in ("mesh", "camera", "skin", "children")),
                "connector must be an empty leaf " + name,
            )
            connectors[name] = point(matrix, [0, 0, 0])
        if "mesh" in node:
            mesh_index = node["mesh"]
            require(
                isinstance(mesh_index, int)
                and 0 <= mesh_index < len(doc.get("meshes", [])),
                "invalid mesh index",
            )
            mesh = doc["meshes"][mesh_index]
            require(not mesh.get("weights"), "morph weights unsupported")
            for primitive in mesh.get("primitives", []):
                require(not primitive.get("targets"), "morph target bounds unsupported")
                require(
                    "KHR_draco_mesh_compression" not in primitive.get("extensions", {}),
                    "Draco bounds unverified",
                )
                require(
                    primitive.get("mode", 4) == 4,
                    "non-triangle primitive unsupported by this pack",
                )
                ai = primitive.get("attributes", {}).get("POSITION")
                require(ai is not None, "primitive without POSITION")
                require(
                    doc["accessors"][ai]["type"] == "VEC3"
                    and doc["accessors"][ai]["componentType"] == 5126,
                    "POSITION must be float VEC3",
                )
                positions = [point(matrix, p) for p in glb.accessor(ai)]
                if "indices" in primitive:
                    ia = primitive["indices"]
                    require(
                        doc["accessors"][ia]["type"] == "SCALAR"
                        and doc["accessors"][ia]["componentType"] in (5121, 5123, 5125),
                        "indices must be unsigned SCALAR",
                    )
                    indices = [row[0] for row in glb.accessor(ia)]
                else:
                    indices = list(range(len(positions)))
                require(
                    len(indices) % 3 == 0 and len(indices) > 0,
                    "triangle index count must be positive and divisible by 3",
                )
                require(
                    min(indices) >= 0 and max(indices) < len(positions),
                    "index outside POSITION accessor",
                )
                material_index = primitive.get("material")
                require(
                    isinstance(material_index, int)
                    and 0 <= material_index < len(materials),
                    "primitive material missing/invalid",
                )
                used_materials.add(material_index)
                if material_index == status[0]:
                    require(
                        "COLOR_0" not in primitive["attributes"],
                        "MAT_STATUS vertex colors can bake status",
                    )
                for i in set(indices):
                    for axis in range(3):
                        bounds_min[axis] = min(bounds_min[axis], positions[i][axis])
                        bounds_max[axis] = max(bounds_max[axis], positions[i][axis])
                tris = list(zip(indices[::3], indices[1::3], indices[2::3]))
                # glTF requires clockwise faces for a negative global determinant.
                # Correct mirrored instances retain their source mesh orientation.
                det = (
                    matrix[0][0]
                    * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
                    - matrix[0][1]
                    * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
                    + matrix[0][2]
                    * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
                )
                require(abs(det) > 1e-12, "singular mesh transform")
                topo = topology(positions, tris, -1 if det < 0 else 1)
                topology_rows.append(
                    {
                        "node": name,
                        "material": materials[material_index].get("name"),
                        **topo,
                    }
                )
                require(
                    not topo["inward_closed_components"],
                    "inward closed component in " + name,
                )
                triangle_count += len(tris)
                primitive_count += 1
        for child in node.get("children", []):
            visit(child, matrix, ancestors | {index})

    for root in doc["scenes"][doc["scene"]].get("nodes", []):
        visit(root, IDENTITY, set())
    require(triangle_count > 0, "empty default scene")
    require(len(visited) == len(nodes), "nodes exist outside default scene")
    require(
        status[0] in used_materials,
        "MAT_STATUS exists but no rendered primitive uses it",
    )
    expected_roles = set(entry["connectors"]) - {"NONE"}
    actual_roles = {
        re.fullmatch(r"CONN_(HV_IN|HV_OUT|MV_FEED)_\d+", name)[1] for name in connectors
    }
    require(
        actual_roles == expected_roles,
        "connector roles mismatch: " + str(sorted(actual_roles)),
    )
    footprint = entry["footprint_m"]
    limits = (footprint["width"] * 0.525, footprint["length"] * 0.525)
    for axis, limit in ((0, limits[0]), (2, limits[1])):
        require(
            bounds_min[axis] >= -limit - 1e-4 and bounds_max[axis] <= limit + 1e-4,
            "geometry exceeds centered nominal footprint by >5%",
        )
    ground_tolerance = max(0.001, max(footprint.values()) * 1e-5)
    require(
        abs(bounds_min[1]) <= ground_tolerance,
        "ground_center fails: minimum Y is " + str(bounds_min[1]),
    )
    require(bounds_max[1] > 0, "model has no positive Y height")
    require(
        bounds_min[0] <= 0 <= bounds_max[0] and bounds_min[2] <= 0 <= bounds_max[2],
        "footprint origin is outside rendered bounds",
    )
    extent = [bounds_max[i] - bounds_min[i] for i in range(3)]
    result.update(
        {
            "triangles": triangle_count,
            "primitives": primitive_count,
            "nodes": len(nodes),
            "bounds_min_m": bounds_min,
            "bounds_max_m": bounds_max,
            "extent_xyz_m": extent,
            "connectors": connectors,
            "topology": topology_rows,
            "embedded_images": len(doc.get("images", [])),
            "extensions_used": doc.get("extensionsUsed", []),
        }
    )
    return result


def audit_pack(root, catalog, only=()):
    entries = catalog["archetypes"]
    if only:
        require(set(only) <= {e["id"] for e in entries}, "unknown requested archetype")
        entries = [e for e in entries if e["id"] in only]
    report = {
        "schema_version": 1,
        "audit": "independent GLB content audit",
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "contract_id": catalog["contractId"],
        "asset_root": str(root),
        "asset_count_expected": len(entries),
        "assets": [],
        "errors": [],
        "limits": [
            "Focused binary and contract audit; not the complete Khronos glTF schema validator.",
            "Bounds are measured from rendered referenced vertices in the default static scene, with node transforms applied.",
            "Y height, centered X/Z containment and ground contact are measurable; semantic front-facing -Z requires source/visual review.",
            "Neutral means MAT_STATUS RGB channels agree within 1e-6 and no texture, vertex-color or emission state is baked there.",
            "Topology audit detects inward closed connected components after position welding; open/nonmanifold components need visual review.",
            "Preview pixel variation rules out a uniform/transparent image, but does not by itself prove a useful silhouette.",
            "Licence and shape-source fields are checked for presence; ownership/provenance declarations require source review.",
            "Default ground-contact tolerance is max(1 mm, 0.001% of footprint extent), to tolerate float export noise.",
            "Scene-level 4M triangle budgets, runtime labels, GPU rendering and interaction are separate integration checks.",
        ],
    }
    for entry in entries:
        aid, out = entry["id"], {"archetype_id": entry["id"], "lods": {}, "errors": []}
        directory = root / "assets" / aid
        for lod in range(3):
            filename = aid + ("" if lod == 0 else f".lod{lod}") + ".glb"
            try:
                out["lods"][f"lod{lod}"] = audit_glb(
                    directory / filename, entry, catalog
                )
            except (
                OSError,
                ValueError,
                KeyError,
                IndexError,
                TypeError,
                struct.error,
                zlib.error,
            ) as error:
                out["errors"].append(f"{filename}: {type(error).__name__}: {error}")
        try:
            meta_path = directory / (aid + ".meta.json")
            meta = json.loads(meta_path.read_text())
            finite(meta)
            require(
                all(field in meta for field in catalog["deliverables"]["metaFields"]),
                "required metadata fields missing",
            )
            require(
                meta["archetype_id"] == aid
                and meta["contract_id"] == catalog["contractId"],
                "metadata identity mismatch",
            )
            require(
                meta["footprint_m"] == entry["footprint_m"],
                "metadata nominal footprint differs from catalog",
            )
            require(
                isinstance(meta["connectors"], list),
                "metadata connectors must be a list",
            )
            meta_connectors = {}
            for connector in meta["connectors"]:
                require(
                    isinstance(connector, dict),
                    "metadata connector must carry name, role and position",
                )
                name = connector.get("name", "")
                match = re.fullmatch(r"CONN_(HV_IN|HV_OUT|MV_FEED)_\d+", name)
                require(
                    match and match[1] == connector.get("role"),
                    "metadata connector name/role mismatch",
                )
                require(name not in meta_connectors, "duplicate metadata connector")
                require(
                    isinstance(connector.get("position"), list)
                    and len(connector["position"]) == 3,
                    "metadata connector position missing",
                )
                meta_connectors[name] = connector["position"]
            for key in (
                "lengthUnit",
                "unitScale",
                "upAxis",
                "forwardAxis",
                "handedness",
                "pivot",
            ):
                require(
                    meta.get("transform", {}).get(key) == catalog["transform"][key],
                    "metadata transform mismatch: " + key,
                )
            forbidden_identity_keys = {
                "latitude",
                "longitude",
                "lat",
                "lon",
                "owner",
                "operator",
                "capacity_mw",
                "site_id",
                "plant_id",
                "status_label",
            }
            require(
                not forbidden_identity_keys.intersection(meta),
                "shape metadata carries placement identity/value",
            )
            for field in ("author", "license", "source_of_shape"):
                require(
                    isinstance(meta[field], (str, dict)) and bool(meta[field]),
                    "empty metadata " + field,
                )
            for lod, measured in out["lods"].items():
                require(
                    meta["triangles_" + lod] == measured["triangles"],
                    "metadata triangle count mismatch for " + lod,
                )
                require(
                    set(measured["connectors"]) == set(meta_connectors),
                    "metadata connector names mismatch for " + lod,
                )
                for name, position in measured["connectors"].items():
                    require(
                        max(abs(a - b) for a, b in zip(position, meta_connectors[name]))
                        <= 1e-4,
                        "metadata connector position mismatch for " + lod + ": " + name,
                    )
            if "lod0" in out["lods"] and "bounds_m" in meta:
                for side in ("min", "max"):
                    require(
                        isinstance(meta["bounds_m"].get(side), list)
                        and len(meta["bounds_m"][side]) == 3
                        and all(
                            isinstance(v, (int, float))
                            and not isinstance(v, bool)
                            and math.isfinite(v)
                            for v in meta["bounds_m"][side]
                        ),
                        "metadata bounds must be 3 finite coordinates: " + side,
                    )
                    require(
                        max(
                            abs(a - b)
                            for a, b in zip(
                                meta["bounds_m"][side],
                                out["lods"]["lod0"]["bounds_" + side + "_m"],
                            )
                        )
                        <= 1e-3,
                        "metadata bounds mismatch: " + side,
                    )
            out["metadata"] = {
                "sha256": sha(meta_path),
                "author": meta["author"],
                "license": meta["license"],
                "source_of_shape": meta["source_of_shape"],
                "connectors": meta["connectors"],
            }
        except (OSError, ValueError, KeyError, TypeError) as error:
            out["errors"].append(f"metadata: {type(error).__name__}: {error}")
        try:
            preview_path = directory / (aid + ".preview.png")
            preview = png_info(preview_path.read_bytes())
            require(
                preview["width"]
                == preview["height"]
                == catalog["deliverables"]["previewPixels"],
                "preview must be 512x512",
            )
            out["preview"] = {"sha256": sha(preview_path), **preview}
        except (OSError, ValueError, KeyError, struct.error, zlib.error) as error:
            out["errors"].append(f"preview: {type(error).__name__}: {error}")
        if len(out["lods"]) == 3:
            counts = {key: value["triangles"] for key, value in out["lods"].items()}
            if counts["lod0"] > catalog["budgets"]["perArchetypeTrianglesLod0"]:
                out["errors"].append("LOD0 triangle count exceeds 40000")
            for lod, share in (("lod1", 0.40), ("lod2", 0.12)):
                if counts[lod] > counts["lod0"] * share:
                    out["errors"].append(
                        f"{lod} triangle share {counts[lod] / counts['lod0']:.4f} exceeds {share}"
                    )
            out["lod_shares"] = {
                lod: counts[lod] / counts["lod0"] for lod in ("lod1", "lod2")
            }
            out["total_glb_bytes"] = sum(row["bytes"] for row in out["lods"].values())
        report["assets"].append(out)
        report["errors"].extend(aid + ": " + error for error in out["errors"])
    report["passed"] = (
        not report["errors"] and len(report["assets"]) == report["asset_count_expected"]
    )
    report["complete_pack"] = (
        not only
        and len(report["assets"]) == 18
        and all(
            len(a["lods"]) == 3 and "metadata" in a and "preview" in a
            for a in report["assets"]
        )
    )
    report["asset_count_passed"] = sum(not a["errors"] for a in report["assets"])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Generated pack directory containing assets/.",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help="Archetype catalog; defaults to the tracked source catalog.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args(argv)
    report = audit_pack(args.root, json.loads(args.catalog.read_text()), args.only)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "complete_pack": report["complete_pack"],
                "asset_count_passed": report["asset_count_passed"],
                "errors": report["errors"],
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

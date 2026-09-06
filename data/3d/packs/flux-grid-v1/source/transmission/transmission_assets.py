"""Generic, compact transmission archetype. No circuit/rating claims.

Art direction informed by the supplied tower; all geometry below newly authored.
"""

import math

from asset_builder import Builder
from mathutils import Vector


def angle_beam(b, name, a, z, width, edge=False):
    if b.lod > 0:
        return b.beam(name, a, z, width, "edge" if edge else "graphite_light")
    start, end = Vector(a), Vector(z)
    q = (end - start).to_track_quat("Z", "Y")
    p = [
        (-0.5, -0.5),
        (0.5, -0.5),
        (0.5, -0.22),
        (-0.22, -0.22),
        (-0.22, 0.5),
        (-0.5, 0.5),
    ]
    verts = [
        q @ Vector((x * width, y * width, k * (end - start).length)) + start
        for k in (0, 1)
        for x, y in p
    ]
    faces = [tuple(reversed(range(6))), tuple(range(6, 12))] + [
        (i, (i + 1) % 6, (i + 1) % 6 + 6, i + 6) for i in range(6)
    ]
    b.mesh(name, verts, faces, "graphite_light")
    if edge:
        off = q @ Vector((width * 0.50, -width * 0.50, 0))
        b.beam(name + "_glint", start + off, end + off, width * 0.22, "edge")


def build(asset_id, lod):
    if asset_id != "transmission_line_segment":
        raise ValueError(asset_id)
    b = Builder(asset_id, lod)
    heights = [0.35, 6.5, 13, 20, 27, 33, 38, 42]
    widths = [4.5, 3.9, 3.0, 2.2, 1.6, 1.25, 0.85, 0.3]
    if lod == 2:
        heights = [0.35, 13, 27, 42]
        widths = [4.5, 3, 1.6, 0.3]
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.box("footing", (sx * 4.5, sy * 4.5, 0.18), (1.15, 1.15, 0.36), "graphite")
            if lod < 2:
                b.outline_box(
                    "footing-rim",
                    (sx * 4.5, sy * 4.5, 0.30),
                    (1.12, 1.12, 0.05),
                    0.065,
                    "status",
                    False,
                )
            for i in range(len(heights) - 1):
                a = (sx * widths[i], sy * widths[i], heights[i])
                c = (sx * widths[i + 1], sy * widths[i + 1], heights[i + 1])
                angle_beam(b, "leg", a, c, 0.32, lod == 0)
                if lod > 0:
                    b.beam("leg-edge", a, c, 0.10 if lod == 1 else 0.14, "edge")
    for k, (h, w) in enumerate(zip(heights, widths)):
        if k == 0:
            continue
        pts = [(-w, -w, h), (w, -w, h), (w, w, h), (-w, w, h), (-w, -w, h)]
        if lod < 2:
            b.polyline("waist", pts, 0.095, "graphite_light", sides=4)
        if k in (2, 4) or lod == 0:
            b.polyline("waist-edge", pts, 0.035 if lod == 0 else 0.06, "edge", sides=4)
    for i in range(len(heights) - 1):
        lo, hi = heights[i], heights[i + 1]
        a, c = widths[i], widths[i + 1]
        for axis in (0, 1):
            for side in (-1, 1):

                def pt(v, w, z, side=side, axis=axis):
                    return (v, side * w, z) if axis == 0 else (side * w, v, z)

                angle_beam(
                    b, "cross-brace", pt(-a, a, lo), pt(c, c, hi), 0.15, lod == 0
                )
                if lod == 0 or (lod == 1 and i % 2 == 0):
                    angle_beam(
                        b, "cross-brace", pt(a, a, lo), pt(-c, c, hi), 0.15, False
                    )
                if lod == 0:
                    mid = (lo + hi) / 2
                    m = (a + c) / 2
                    angle_beam(b, "k-brace", pt(-a, a, lo), pt(0, m, mid), 0.12)
                    angle_beam(b, "k-brace", pt(a, a, lo), pt(0, m, mid), 0.12)
                    for j in (0, 1):
                        at = pt((-1 if j == 0 else 1) * c, c, hi)
                        b.cylinder(
                            "gusset",
                            at,
                            0.22,
                            0.08,
                            "graphite",
                            vertices=12,
                            rotation=(math.pi / 2, 0, 0),
                        )
    for j, z in enumerate((26, 32, 38)):
        span = 5.6 - j * 0.45
        for side in (-1, 1):
            tip = (side * span, 0, z)
            angle_beam(b, "crossarm-lower", (0, 0, z), tip, 0.27, lod == 0)
            angle_beam(b, "crossarm-upper", (0, 0, z + 2.2), tip, 0.20, lod == 0)
            if lod < 2:
                for p in range(1, 5 if lod == 0 else 3):
                    f = p / (5 if lod == 0 else 3)
                    angle_beam(
                        b,
                        "crossarm-diagonal",
                        (side * span * f, 0, z),
                        (side * span * min(1, f + 0.20), 0, z + 2.2 * (1 - f)),
                        0.12,
                    )
            b.cylinder(
                "insulator-core",
                (side * span, 0, z - 1.3),
                0.10,
                2.6,
                "graphite_light",
                vertices=8,
            )
            sheds = 24 if lod == 0 else 9 if lod == 1 else 0
            for s in range(sheds):
                b.cylinder(
                    "insulator-shed",
                    (side * span, 0, z - 2.45 + s * 2.3 / max(1, sheds - 1)),
                    0.29,
                    0.09,
                    "white",
                    vertices=20 if lod == 0 else 8,
                    radius_top=0.16,
                )
            if lod == 2:
                b.cylinder(
                    "insulator-symbol",
                    (side * span, 0, z - 1.3),
                    0.18,
                    2.6,
                    "white",
                    vertices=6,
                )
            b.beam(
                "socket",
                (side * span, -0.42, z - 2.6),
                (side * span, 0.42, z - 2.6),
                0.12,
                "status",
            )
    for side in (-1, 1):
        b.beam("shield-peak", (0, 0, 40), (side * 1.2, 0, 44), 0.19, "graphite_light")
        b.beam("peak-glow", (0, 0.08, 40), (side * 1.2, 0.08, 44), 0.065, "edge")
    if lod == 0:
        for z in range(1, 38):
            b.beam("ladder-rung", (-0.28, 1.45, z), (0.28, 1.45, z), 0.075, "white")
        b.beam(
            "ladder-rail", (-0.29, 1.45, 0.7), (-0.29, 1.45, 38), 0.09, "graphite_light"
        )
        b.beam(
            "ladder-rail", (0.29, 1.45, 0.7), (0.29, 1.45, 38), 0.09, "graphite_light"
        )
    b.connector("HV_IN", 0, (5.6, -0.42, 23.4))
    b.connector("HV_OUT", 0, (5.6, 0.42, 23.4))
    b.metadata = {
        "source_of_shape": "Original procedural compact lattice geometry; visual art direction informed by user-supplied tx_345kv_codex_handoff. Not a copy of its 345 kV dimensions or a rated design.",
        "nominal_height_m": 44,
    }
    return b

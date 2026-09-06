"""Original, identity-free hospital massing; meters, Z up, +Y forward.

Only build() appends geometry. Export, materials, and scene state belong to the
shared pipeline. There is no bed-count, service-level, or backup-power claim.
"""

from asset_builder import Builder


def _cornice(b, name, x, y, z, w, d, width=0.11):
    """Thin architectural edge at an actual roof perimeter."""
    pts = [
        (x - w / 2, y - d / 2, z),
        (x + w / 2, y - d / 2, z),
        (x + w / 2, y + d / 2, z),
        (x - w / 2, y + d / 2, z),
        (x - w / 2, y - d / 2, z),
    ]
    b.polyline(name, pts, width / 2, "edge")


def _facade(b, name, x, y, z, w, d, h, rows, columns):
    """Setback clear panels, opaque jambs, and substantial floor reveals."""
    for side in (-1, 1):
        yy = y + side * (d / 2 + 0.03)
        b.box(name + "_glazing", (x, yy, z), (w - 0.6, 0.09, h - 0.65), "glass")
        for r in range(rows):
            zz = z - h / 2 + (r + 0.5) * h / rows
            for c in range(columns):
                xx = x - w / 2 + (c + 0.5) * w / columns
                b.box(
                    name + "_window",
                    (xx, yy + side * 0.065, zz),
                    (w / columns - 0.46, 0.10, h / rows - 1.02),
                    "graphite_light",
                )
            b.box(
                name + "_spandrel",
                (x, yy + side * 0.10, zz - h / (2 * rows) + 0.16),
                (w, 0.19, 0.32),
                "graphite",
            )
        for c in range(columns + 1):
            xx = x - w / 2 + c * w / columns
            b.box(
                name + "_jamb", (xx, yy + side * 0.11, z), (0.17, 0.23, h), "graphite"
            )
    # End elevations contain opaque cores and slender translucent reveal strips.
    for side in (-1, 1):
        xx = x + side * (w / 2 + 0.05)
        b.box(name + "_end_glass", (xx, y, z), (0.10, d - 0.4, h - 0.4), "glass")
        for r in range(rows):
            zz = z - h / 2 + (r + 0.5) * h / rows
            for c in range(max(2, columns // 2)):
                yy = y - d / 2 + (c + 0.5) * d / max(2, columns // 2)
                b.box(
                    name + "_end_panel",
                    (xx + side * 0.07, yy, zz),
                    (0.12, d / max(2, columns // 2) - 0.65, h / rows - 1.05),
                    "graphite_light",
                )


def _air_handler(b, name, x, y, z, w=4.5, d=5.5):
    b.box(name + "_curb", (x, y, z + 0.2), (w + 0.6, d + 0.6, 0.4), "graphite")
    b.box(name + "_case", (x, y, z + 1.15), (w, d, 1.5), "graphite_light")
    for yy in (y - d * 0.23, y + d * 0.23):
        b.cylinder(
            name + "_fan_well",
            (x, yy, z + 1.97),
            w * 0.27,
            0.14,
            "graphite",
            vertices=20,
        )
        b.ring(
            name + "_fan_grille",
            (x, yy, z + 2.06),
            w * 0.22,
            0.045,
            "white",
            segments=20,
        )
        for angle in (0, 0.785398, 1.570796, 2.356194):
            import math

            dx, dy = w * 0.22 * math.cos(angle), w * 0.22 * math.sin(angle)
            b.beam(
                name + "_fan_grille",
                (x - dx, yy - dy, z + 2.075),
                (x + dx, yy + dy, z + 2.075),
                0.065,
                "graphite_light",
            )
    for i in range(7):
        b.box(
            name + "_louvre",
            (x + w / 2 + 0.045, y, z + 0.55 + i * 0.17),
            (0.11, d - 0.35, 0.06),
            "graphite",
        )


def _medical_cross(b, name, center, span, stroke, depth, plane):
    """One closed raised plus sign, with no overlapping coplanar bar faces.

    This white category symbol has no status meaning and is not a helipad.
    Roof signs lie in XY; front signs lie in XZ and project toward +Y.
    """
    r, a = span / 2, stroke / 2
    outline = [
        (-a, -r),
        (a, -r),
        (a, -a),
        (r, -a),
        (r, a),
        (a, a),
        (a, r),
        (-a, r),
        (-a, a),
        (-r, a),
        (-r, -a),
        (-a, -a),
    ]
    cx, cy, cz = center
    vertices = []
    for normal in (-depth / 2, depth / 2):
        for u, v in outline:
            vertices.append(
                (cx + u, cy + v, cz + normal)
                if plane == "roof"
                else (cx + u, cy + normal, cz + v)
            )
    count = len(outline)
    faces = [tuple(reversed(range(count))), tuple(range(count, count * 2))]
    faces.extend(
        (i, (i + 1) % count, (i + 1) % count + count, i + count) for i in range(count)
    )
    if plane == "front":
        faces = [tuple(reversed(face)) for face in faces]
    b.mesh(name, vertices, faces, "white")


def _medical_signs(b):
    # Rooftop plaque clears the ducts, sits inside the parapet, and has roof mounts.
    for x in (-4.0, 2.0):
        b.box("roof_sign_mount", (x, 7.1, 39.745), (0.35, 7.5, 1.53), "graphite")
    b.box("roof_medical_sign_backing", (-1, 7.1, 40.72), (12.2, 12.2, 0.42), "graphite")
    _medical_cross(b, "roof_medical_cross", (-1, 7.1, 41.10), 10.4, 3.2, 0.28, "roof")
    # Entrance plaque sits above the ambulance canopy and ahead of every mullion.
    b.box("entrance_medical_sign_backing", (0, 27.4, 8.9), (6.8, 0.32, 6.8), "graphite")
    _medical_cross(
        b, "entrance_medical_cross", (0, 27.71, 8.9), 5.6, 1.7, 0.24, "front"
    )


def build(asset_id, lod):
    if asset_id != "hospital":
        raise ValueError("hospital.py builds hospital only")
    if lod not in (0, 1, 2):
        raise ValueError("lod must be 0, 1, or 2")
    b = Builder(asset_id, lod)
    b.box("ground_plinth", (0, 0, 0.50), (56, 84, 1.0), "graphite")
    b.box("podium", (0, -7, 5.2), (47, 50, 8.4), "graphite")
    b.box("main_tower", (-1, -2, 24.2), (21, 35, 29.6), "graphite")
    b.box("west_wing", (-18, -8, 18.4), (13, 30, 18.0), "graphite")
    b.box("east_wing", (18, -10, 16.8), (13, 25, 14.8), "graphite")
    b.box("entry_atrium", (0, 21, 6.7), (18, 12, 11.4), "glass")
    b.box("entry_core", (0, 18.4, 5.3), (9, 4.5, 8.6), "graphite_light")
    b.box("ambulance_canopy", (0, 30, 5.0), (28, 13, 0.65), "graphite_light")
    b.box("service_volume", (18, -29, 7.0), (12, 11, 12), "graphite")
    b.box("neutral_status_inlay", (0, 36.52, 4.94), (4.0, 0.09, 0.32), "status")
    b.connector("MV_FEED", 0, (26, -33, 2.6))
    _medical_signs(b)
    if lod == 2:
        # Keep the varied tower heights and horizontal arrival canopy only.
        b.box("tower_crown_glass", (-1, -2, 39.05), (21.05, 35.05, 0.16), "glass")
        b.box("tower_roof_edge", (-1, 15.54, 39.18), (21.1, 0.12, 0.12), "edge")
        b.box("roof_machinery", (-1, -8, 40.1), (10, 10, 2.0), "graphite_light")
        return b

    _cornice(b, "podium_cornice", 0, -7, 9.45, 47.2, 50.2, 0.12)
    _cornice(b, "tower_crown", -1, -2, 39.69, 21.62, 35.62, 0.13)
    _cornice(b, "west_cornice", -18, -8, 28.14, 13.62, 30.62, 0.11)
    _cornice(b, "east_cornice", 18, -10, 24.94, 13.62, 25.62, 0.11)
    _cornice(b, "canopy_edge", 0, 30, 5.34, 28, 13, 0.12)
    # Selective skins are only the facade planes, keeping most roofs physical.
    b.box("tower_front_frosted_skin", (-1, 15.57, 24.2), (20.8, 0.13, 29.3), "glass")
    b.box("tower_west_frosted_skin", (-11.57, -2, 24.2), (0.13, 34.7, 29.3), "glass")
    b.box("wing_reveal_glass", (-24.57, -8, 18.4), (0.13, 29.5, 17.5), "glass")
    for x in (-11.7, 11.7):
        for y in (25, 35):
            b.box("canopy_pier", (x, y, 2.85), (0.42, 0.42, 3.7), "graphite_light")
    for z in (12.5, 20.5, 28.5, 36.5):
        b.box("tower_floor_reveal", (-1, 15.70, z), (21, 0.14, 0.22), "graphite_light")
    for x in (-7, 0, 7):
        b.box("ambulance_bay_recess", (x, 26.98, 2.6), (5.8, 0.18, 3.0), "graphite")
        b.box("ambulance_bay_glass", (x, 27.1, 2.7), (5.2, 0.10, 2.2), "glass")
    b.box("roof_machinery_screen", (-1, -9, 40.5), (12, 11, 2.8), "graphite_light")
    if lod == 1:
        return b

    # Close inspection reveals distinct fenestration rhythms on every mass.
    _facade(b, "tower", -1, -2, 24.0, 21.05, 35.05, 28.2, 8, 7)
    _facade(b, "west", -18, -8, 18.3, 13.05, 30.05, 17.0, 5, 4)
    _facade(b, "east", 18, -10, 16.8, 13.05, 25.05, 14.0, 4, 4)
    _facade(b, "podium", 0, -7, 5.1, 47.05, 50.05, 7.6, 2, 13)
    # Structural top slabs give the building clean, legible silhouette planes.
    for name, x, y, z, w, d in (
        ("tower", -1, -2, 39.05, 21.6, 35.6),
        ("west", -18, -8, 27.5, 13.6, 30.6),
        ("east", 18, -10, 24.3, 13.6, 25.6),
    ):
        b.box(name + "_roof_slab", (x, y, z), (w, d, 0.23), "graphite_light")
        for dx in (-w / 2 + 0.16, w / 2 - 0.16):
            b.box(name + "_parapet", (x + dx, y, z + 0.34), (0.18, d, 0.5), "graphite")
        for dy in (-d / 2 + 0.16, d / 2 - 0.16):
            b.box(name + "_parapet", (x, y + dy, z + 0.34), (w, 0.18, 0.5), "graphite")
    for x, y, z in (
        (-4, -10, 41.9),
        (3, -10, 41.9),
        (-18, -13, 27.65),
        (18, -12, 24.45),
    ):
        _air_handler(b, "ahu", x, y, z)
    # Plant risers and roofs stay opaque; only a few glass clerestories reveal depth.
    for x in (-6, 4):
        b.box("roof_duct", (x, 5, 39.9), (2.4, 9, 0.9), "graphite_light")
        for y in (1, 4, 7):
            b.box("duct_seam", (x, y, 40.37), (2.45, 0.10, 0.10), "graphite")
    for x in (-8.7, 0, 8.7):
        b.box("atrium_mullion", (x, 27.08, 6.7), (0.15, 0.2, 11.4), "graphite_light")
    for z in (4.2, 8.2, 12.35):
        b.box("atrium_transom", (0, 27.09, z), (18.1, 0.18, 0.16), "graphite_light")
    for x in (-5, 0, 5):
        b.box("entry_door", (x, 27.18, 2.6), (3.2, 0.12, 3.2), "graphite_light")
        b.box("entry_door_glass", (x, 27.25, 2.6), (2.9, 0.08, 2.9), "glass")
    # Canopy roof has a sparse glass lightwell and long structural ribs below it.
    b.box("canopy_lightwell", (0, 30, 5.37), (20, 4.5, 0.14), "glass")
    for x in (-10.5, -3.5, 3.5, 10.5):
        b.box("canopy_rib", (x, 30, 4.54), (0.16, 12, 0.38), "graphite")
    for x in (-7, 0, 7):
        b.box("bay_light", (x, 27.25, 4.32), (4.8, 0.12, 0.09), "white")
        b.box("bay_threshold", (x, 27.9, 1.04), (5.8, 1.5, 0.08), "graphite_light")
    # Quiet paving joints, ramps, and entry steps explain scale without markings.
    for y in (38, 40):
        b.box(
            "arrival_paving_joint", (0, y, 1.012), (32, 0.06, 0.025), "graphite_light"
        )
    for x in (-19, 19):
        for y in (23, 30, 37):
            b.box("paving_joint", (x, y, 1.013), (0.045, 6, 0.026), "graphite_light")
    for i in range(4):
        b.box(
            "entry_step",
            (0, 39 - i * 0.7, 1.08 + i * 0.06),
            (17, 1.0, 0.14 + i * 0.12),
            "graphite_light",
        )
    b.box("feeder_plinth", (26, -33, 1.25), (2.5, 3, 0.5), "graphite_light")
    b.box("feeder_cabinet", (26, -33, 2.1), (1.7, 2.2, 1.2), "graphite")
    return b

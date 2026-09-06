"""Original support-campus archetype; no real installation or tactical layout.

Builder coordinates are metres, Z-up, +Y-forward with a ground-centred pivot.
The export owner performs the common glTF axis conversion. Importing this module
does not modify a Blender scene; build() only fills the shared geometry builder.
"""

from asset_builder import Builder

GROUND = 0.45


def _gable(b, name, x, y, width, length, eave, rise, material="graphite"):
    """A closed triangular roof prism with correctly oriented outer faces."""
    left, right = x - width / 2, x + width / 2
    back, front = y - length / 2, y + length / 2
    b.mesh(
        name,
        [
            (left, back, eave),
            (right, back, eave),
            (x, back, eave + rise),
            (left, front, eave),
            (right, front, eave),
            (x, front, eave + rise),
        ],
        [(0, 1, 2), (3, 5, 4), (0, 3, 4, 1), (0, 2, 5, 3), (1, 4, 5, 2)],
        material,
    )


def _roof_edges(b, name, x, y, width, length, eave, rise, fine):
    """Accents follow actual roof junctions; no freestanding decoration."""
    for side in (-1, 1):
        b.beam(
            name + "_eave",
            (x + side * width / 2, y - length / 2, eave),
            (x + side * width / 2, y + length / 2, eave),
            0.16,
            "edge",
        )
    b.beam(
        name + "_ridge",
        (x, y - length / 2, eave + rise),
        (x, y + length / 2, eave + rise),
        0.20,
        "white",
    )
    if fine:
        for end in (-1, 1):
            yy = y + end * length / 2
            b.beam(
                name + "_rake",
                (x - width / 2, yy, eave),
                (x, yy, eave + rise),
                0.20,
                "graphite_light",
            )
            b.beam(
                name + "_rake",
                (x, yy, eave + rise),
                (x + width / 2, yy, eave),
                0.20,
                "graphite_light",
            )


def _low_wing(b, index, x, y, lod):
    name = f"support_wing_{index}"
    width, length, height = 31.0, 33.0, 9.2
    top = GROUND + height
    b.box(name + "_core", (x, y, GROUND + height / 2), (width, length, height))
    _gable(b, name + "_roof", x, y, width + 1.0, length + 1.0, top, 2.8)
    if lod == 2:
        b.box(
            name + "_front_glazing",
            (x, y + length / 2 + 0.08, 6.9),
            (26.0, 0.12, 2.2),
            "glass",
        )
        return

    b.box(
        name + "_foundation",
        (x, y, 0.7),
        (width + 1.2, length + 1.2, 0.5),
        "graphite_light",
    )
    _roof_edges(b, name, x, y, width + 1.0, length + 1.0, top, 2.8, lod == 0)
    count = 7 if lod == 0 else 3
    for side in (-1, 1):
        xx = x + side * (width / 2 + 0.10)
        if lod == 1:
            b.box(
                name + "_window_band", (xx, y, 6.4), (0.12, length - 5.0, 2.1), "glass"
            )
        for k in range(count):
            yy = y - length * 0.39 + (k + 0.5) * (length * 0.78 / count)
            b.box(name + "_window", (xx, yy, 6.4), (0.14, 2.65, 2.25), "glass")
            if lod == 0:
                b.box(
                    name + "_reveal",
                    (xx + side * 0.12, yy, 7.62),
                    (0.38, 3.1, 0.19),
                    "graphite_light",
                )
                b.box(
                    name + "_sill",
                    (xx + side * 0.12, yy, 5.16),
                    (0.38, 3.1, 0.16),
                    "white",
                )
                b.box(
                    name + "_mullion",
                    (xx + side * 0.09, yy, 6.4),
                    (0.13, 0.13, 2.25),
                    "graphite_light",
                )
                b.box(
                    name + "_lower_window", (xx, yy, 2.95), (0.14, 2.65, 1.65), "glass"
                )
        b.box(
            name + "_floor_band", (xx, y, 4.35), (0.25, length, 0.32), "graphite_light"
        )

    front = y + length / 2
    b.box(name + "_entry_recess", (x, front + 0.08, 2.5), (4.2, 0.15, 4.1), "glass")
    b.box(
        name + "_entry_canopy",
        (x, front + 1.5, 4.6),
        (6.0, 3.0, 0.25),
        "graphite_light",
    )
    b.beam(
        name + "_entry_lip",
        (x - 3.0, front + 3.0, 4.61),
        (x + 3.0, front + 3.0, 4.61),
        0.13,
        "white",
    )
    if lod == 0:
        for k in range(8):
            yy = y - length / 2 + k * length / 7
            b.beam(
                name + "_roof_seam",
                (x - 16.0, yy, top + 0.08),
                (x, yy, top + 2.88),
                0.13,
                "graphite_light",
            )
            b.beam(
                name + "_roof_seam",
                (x, yy, top + 2.88),
                (x + 16.0, yy, top + 0.08),
                0.13,
                "graphite_light",
            )
        for dx in (-5.4, 5.4):
            b.box(
                name + "_roof_vent",
                (x + dx, y - 5.0, top + 2.4),
                (2.0, 3.6, 1.2),
                "graphite_light",
            )
            b.box(
                name + "_vent_cap",
                (x + dx, y - 5.0, top + 3.03),
                (2.3, 3.9, 0.18),
                "white",
            )
        for step in range(3):
            b.box(
                name + "_entry_step",
                (x, front + 2.5 + 0.45 * step, 0.57 - 0.04 * step),
                (6.4, 0.55, 0.18),
                "graphite_light",
            )


def _maintenance_hall(b, lod):
    x, y, width, length = 30.0, -51.0, 72.0, 56.0
    eave, ridge = 14.8, 21.1
    b.box("hall_core", (x, y, GROUND + 6.6), (width, length, 13.2))
    _gable(b, "hall_pitched_roof", x, y, width + 1.6, length + 1.6, eave, ridge - eave)
    b.box(
        "hall_clerestory_front",
        (x, y + length / 2 + 0.08, 14.12),
        (width - 2.0, 0.16, 1.3),
        "glass",
    )
    if lod == 2:
        b.box(
            "hall_bay_band",
            (x, y + length / 2 + 0.11, 6.4),
            (width - 8.0, 0.18, 10.0),
            "glass",
        )
        return

    _roof_edges(
        b, "hall", x, y, width + 1.6, length + 1.6, eave, ridge - eave, lod == 0
    )
    b.box(
        "hall_plinth", (x, y, 0.69), (width + 2.0, length + 2.0, 0.48), "graphite_light"
    )
    for side in (-1, 1):
        xx = x + side * (width / 2 + 0.1)
        b.box(
            "hall_side_clerestory", (xx, y, 13.78), (0.16, length - 1.5, 1.78), "glass"
        )
        for k in range(9 if lod == 0 else 4):
            count = 9 if lod == 0 else 4
            yy = y - length / 2 + 1.5 + k * (length - 3.0) / (count - 1)
            b.box(
                "hall_side_column",
                (xx + side * 0.16, yy, 7.45),
                (0.65, 0.68, 13.95),
                "graphite_light",
            )
            if lod == 0:
                b.box(
                    "hall_side_window",
                    (xx + side * 0.04, yy + 1.55, 9.65),
                    (0.18, 2.35, 2.0),
                    "glass",
                )
                b.box(
                    "hall_side_vent",
                    (xx + side * 0.12, yy + 1.55, 3.0),
                    (0.32, 2.35, 1.75),
                    "graphite_light",
                )
                for z in (2.46, 2.84, 3.22, 3.60):
                    b.box(
                        "hall_vent_louvre",
                        (xx + side * 0.32, yy + 1.55, z),
                        (0.14, 2.10, 0.10),
                        "graphite",
                    )

    front = y + length / 2
    for k in range(3):
        xx = x - 23.0 + 23.0 * k
        b.box(
            "hall_bay_reveal",
            (xx, front + 0.12, 6.5),
            (21.8, 0.32, 11.9),
            "graphite_light",
        )
        b.box("hall_bay_door", (xx, front + 0.31, 6.45), (20.3, 0.18, 11.2), "graphite")
        b.box(
            "hall_bay_high_glass", (xx, front + 0.43, 9.65), (19.7, 0.10, 2.3), "glass"
        )
        b.beam(
            "hall_bay_lintel",
            (xx - 10.2, front + 0.50, 12.5),
            (xx + 10.2, front + 0.50, 12.5),
            0.18,
            "white",
        )
        if lod == 0:
            for z in (1.3, 2.4, 3.5, 4.6, 5.7, 6.8, 7.9, 10.95):
                b.box(
                    "hall_door_joint",
                    (xx, front + 0.44, z),
                    (19.85, 0.11, 0.12),
                    "graphite_light",
                )
            for dx in (-6.5, 0, 6.5):
                b.box(
                    "hall_door_glass_mullion",
                    (xx + dx, front + 0.50, 9.65),
                    (0.16, 0.15, 2.3),
                    "graphite_light",
                )
            for dx in (-10.7, 10.7):
                b.box(
                    "hall_door_jamb",
                    (xx + dx, front + 0.5, 6.4),
                    (0.48, 0.6, 11.5),
                    "graphite_light",
                )

    if lod == 0:
        for k in range(13):
            yy = y - length / 2 + k * length / 12
            b.beam(
                "hall_roof_seam",
                (x - 36.8, yy, eave + 0.06),
                (x, yy, ridge + 0.06),
                0.14,
                "graphite_light",
            )
            b.beam(
                "hall_roof_seam",
                (x, yy, ridge + 0.06),
                (x + 36.8, yy, eave + 0.06),
                0.14,
                "graphite_light",
            )
        # Short front roof overhang exposes original structural truss members.
        truss_y = front + 0.65
        b.beam(
            "hall_front_tie",
            (x - 35.5, truss_y, eave + 0.18),
            (x + 35.5, truss_y, eave + 0.18),
            0.32,
            "graphite_light",
        )
        for k in range(8):
            xx = x - 31.5 + k * 9.0
            roof_z = ridge - abs(xx - x) * (ridge - eave) / 36.8
            b.beam(
                "hall_truss_web",
                (xx, truss_y, eave + 0.24),
                (xx, truss_y, roof_z - 0.1),
                0.22,
                "graphite_light",
            )
        for dx in (-18.0, 18.0):
            b.box(
                "hall_roof_monitor",
                (x + dx, y - 4.0, 18.05),
                (5.4, 26.0, 2.1),
                "graphite_light",
            )
            b.box(
                "hall_monitor_glazing",
                (x + dx, y - 4.0, 19.18),
                (4.5, 24.8, 0.10),
                "glass",
            )


def _administration(b, lod):
    x, y, width, length = 22.0, 46.0, 72.0, 30.0
    b.box("admin_core", (x, y, 7.65), (width, length, 14.4))
    b.box(
        "admin_roof", (x, y, 15.15), (width + 1.2, length + 1.2, 0.65), "graphite_light"
    )
    b.box("admin_lobby_core", (x + 3.0, y + 18.8, 4.5), (21.0, 8.0, 8.1))
    b.box("admin_lobby_glass", (x + 3.0, y + 23.05, 4.65), (20.7, 0.20, 7.6), "glass")
    if lod == 2:
        b.box(
            "admin_front_glazing",
            (x, y + length / 2 + 0.1, 10.1),
            (width - 4.0, 0.15, 4.0),
            "glass",
        )
        return

    b.box(
        "admin_plinth",
        (x, y, 0.72),
        (width + 1.8, length + 1.8, 0.54),
        "graphite_light",
    )
    for side in (-1, 1):
        front = y + side * (length / 2 + 0.11)
        for level in (0, 1):
            zz = 4.4 + 6.2 * level
            b.box(
                "admin_continuous_glazing",
                (x, front, zz),
                (width - 2.0, 0.18, 4.2),
                "glass",
            )
            b.box(
                "admin_spandrel",
                (x, front + side * 0.15, zz - 2.25),
                (width - 0.8, 0.25, 0.42),
                "graphite_light",
            )
        count = 14 if lod == 0 else 5
        for k in range(count):
            xx = x - width / 2 + 1.6 + k * (width - 3.2) / (count - 1)
            b.box(
                "admin_facade_fin",
                (xx, front + side * 0.36, 8.3),
                (0.28, 0.75, 12.2),
                "graphite_light",
            )
            if lod == 0:
                for level in (0, 1):
                    b.box(
                        "admin_glass_transom",
                        (xx + 1.3, front + side * 0.18, 4.45 + level * 6.2),
                        (2.2, 0.18, 0.14),
                        "white",
                    )
        b.beam(
            "admin_eave_edge",
            (x - width / 2, front, 15.53),
            (x + width / 2, front, 15.53),
            0.15,
            "edge",
        )

    for side in (-1, 1):
        xx = x + side * (width / 2 + 0.12)
        b.box("admin_side_glass", (xx, y, 10.6), (0.16, length - 3.2, 4.2), "glass")
        if lod == 0:
            for k in range(7):
                b.box(
                    "admin_side_fin",
                    (xx + side * 0.25, y - 12.0 + k * 4.0, 9.8),
                    (0.55, 0.24, 9.6),
                    "graphite_light",
                )

    b.box(
        "admin_lobby_canopy",
        (x + 3.0, y + 23.9, 8.85),
        (27.0, 12.5, 0.48),
        "graphite_light",
    )
    b.beam(
        "admin_lobby_fascia",
        (x - 10.5, y + 30.15, 8.93),
        (x + 16.5, y + 30.15, 8.93),
        0.18,
        "white",
    )
    for xx in (x - 8.5, x + 14.5):
        b.box(
            "admin_canopy_post",
            (xx, y + 27.8, 4.62),
            (0.35, 0.35, 8.35),
            "graphite_light",
        )
    b.box("admin_status_inset", (x + 3.0, y + 30.17, 8.75), (8.0, 0.11, 0.48), "status")

    if lod == 0:
        for dx in (-6.0, 0.0, 6.0):
            b.box(
                "admin_lobby_mullion",
                (x + 3.0 + dx, y + 23.2, 4.6),
                (0.18, 0.20, 7.65),
                "graphite_light",
            )
        for k in range(5):
            b.box(
                "admin_entry_tread",
                (x + 3.0, y + 29.8 + k * 0.68, 0.64 - k * 0.025),
                (21.0, 0.68, 0.16),
                "graphite_light",
            )
        for xx in (x - 22.0, x + 21.0):
            b.box(
                "admin_rooftop_equipment",
                (xx, y - 4.0, 16.65),
                (9.5, 8.2, 2.4),
                "graphite_light",
            )
            b.box(
                "admin_equipment_top", (xx, y - 4.0, 17.91), (10.0, 8.7, 0.18), "white"
            )
            for dy in (-2.25, 2.25):
                b.cylinder(
                    "admin_fan_collar",
                    (xx, y - 4.0 + dy, 18.16),
                    1.45,
                    0.34,
                    "graphite",
                    vertices=20,
                )
                b.cylinder(
                    "admin_fan_hub",
                    (xx, y - 4.0 + dy, 18.36),
                    0.42,
                    0.12,
                    "graphite_light",
                    vertices=12,
                )
                for off in (-0.6, 0, 0.6):
                    b.box(
                        "admin_fan_grille",
                        (xx + off, y - 4.0 + dy, 18.43),
                        (0.09, 2.5, 0.10),
                        "graphite_light",
                    )
        for k in range(9):
            b.box(
                "admin_roof_plant_screen",
                (x - 22.0 + k * 5.5, y - 10.4, 16.45),
                (0.16, 0.28, 2.5),
                "graphite_light",
            )
        b.box(
            "admin_screen_rail",
            (x, y - 10.4, 17.65),
            (45.0, 0.28, 0.16),
            "graphite_light",
        )


def _site_details(b, lod):
    b.box("campus_ground", (0, 0, GROUND / 2), (160.0, 200.0, GROUND))
    b.box(
        "hall_apron", (30.0, -7.0, GROUND + 0.04), (76.0, 28.0, 0.08), "graphite_light"
    )
    b.box(
        "entry_paving",
        (25.0, 81.5, GROUND + 0.04),
        (40.0, 15.0, 0.08),
        "graphite_light",
    )
    if lod == 2:
        b.box("campus_status_inset", (25.0, 75.0, 0.57), (8.0, 0.7, 0.16), "status")
        return

    b.box(
        "campus_walk", (-23.0, 7.0, GROUND + 0.05), (4.5, 151.0, 0.10), "graphite_light"
    )
    b.box("admin_walk", (0, 69.7, GROUND + 0.05), (49.0, 4.0, 0.10), "graphite_light")
    b.box("service_annex", (-47.0, 77.0, 3.95), (26.0, 18.0, 7.0))
    b.box(
        "service_annex_roof", (-47.0, 77.0, 7.65), (27.0, 19.0, 0.40), "graphite_light"
    )
    b.box("service_annex_glazing", (-47.0, 86.08, 4.55), (20.0, 0.15, 2.1), "glass")
    b.box("feeder_cabinet", (-68.5, 78.0, 2.05), (3.4, 3.0, 3.2), "graphite_light")
    b.box("feeder_cabinet_inset", (-68.5, 79.56, 2.12), (2.8, 0.13, 2.5))
    if lod == 0:
        for x, y in ((-26, -47), (-26, -3), (-26, 42), (54, 79)):
            b.cylinder(
                "walk_light_post",
                (x, y, 3.35),
                0.14,
                5.8,
                "graphite_light",
                vertices=10,
            )
            b.box(
                "walk_light_head",
                (x, y + 0.45, 6.3),
                (1.15, 1.8, 0.28),
                "graphite_light",
            )
            b.box("walk_light_lens", (x, y + 0.45, 6.14), (0.85, 1.40, 0.06), "white")
        for x in (-5.0, 56.0):
            b.box("entry_planter", (x, 80.0, 1.05), (8.2, 4.0, 1.2), "graphite_light")
            b.box("entry_planter_infill", (x, 80.0, 1.7), (7.35, 3.2, 0.16))
        for y in (21.0, 27.0):
            b.box("walk_bench", (-17.4, y, 1.15), (1.5, 4.2, 0.18), "graphite_light")
            for dy in (-1.3, 1.3):
                b.box("walk_bench_support", (-17.4, y + dy, 0.85), (1.2, 0.25, 0.6))


def build(asset_id, lod):
    """Return one original generic installation geometry at a requested LOD."""
    if lod not in (0, 1, 2):
        raise ValueError("lod must be 0, 1, or 2")
    b = Builder(asset_id, lod)
    _site_details(b, lod)
    _maintenance_hall(b, lod)
    for index, y in enumerate((-56.0, -12.0, 32.0)):
        _low_wing(b, index, -48.0, y, lod)
    _administration(b, lod)
    b.connector("MV_FEED", 0, (-70.2, 78.0, 2.2))
    b.metadata["source_of_shape"] = (
        "Original procedural support-campus architecture; no third-party source."
    )
    b.metadata["shape_limit"] = (
        "Generic installation silhouette; no real facility, perimeter, or asset disposition."
    )
    return b

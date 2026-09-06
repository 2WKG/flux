"""Original procedural solar and storage archetypes for Flux.

Only append geometry to the supplied Builder; importing this module does not
touch Blender, create a scene, export files, or attach placement identity.
Author coordinates are metres, Z up, +Y forward. The pipeline owns glTF axis
conversion and canonical connectors. Panel/cabinet repetition has no capacity
or output meaning. All detail is functional geometry rather than triangle fill.
"""

import math

__all__ = ["build_battery", "build_solar"]


def _check_lod(lod):
    if lod not in (0, 1, 2):
        raise ValueError("Expected lod 0, 1, or 2")


def _corners(b, name, width, length, size, z=0.28):
    """Sparse registration brackets leave the ground plate visually quiet."""
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * (width / 2 - 1), sy * (length / 2 - 1)
            b.beam(name, (x, y, z), (x - sx * size, y, z), 0.13, "white")
            b.beam(name, (x, y, z), (x, y - sy * size, z), 0.13, "white")


def _solar_point(cx, cy, x, y, z=0):
    tilt = math.radians(20)
    return (
        cx + x,
        cy + y * math.cos(tilt) - z * math.sin(tilt),
        4.8 + y * math.sin(tilt) + z * math.cos(tilt),
    )


def _solar_border(b, name, cx, cy, width, depth, z=0.16):
    p = lambda x, y: _solar_point(cx, cy, x, y, z)
    # The leading cyan rail and remaining white frame are actual thin solids.
    b.beam(
        name + "_leading",
        p(-width / 2, -depth / 2),
        p(width / 2, -depth / 2),
        0.105,
        "edge",
    )
    b.beam(
        name + "_trailing",
        p(-width / 2, depth / 2),
        p(width / 2, depth / 2),
        0.085,
        "white",
    )
    for side in (-1, 1):
        b.beam(
            name + "_side",
            p(side * width / 2, -depth / 2),
            p(side * width / 2, depth / 2),
            0.075,
            "white",
        )


def _solar_rack(b, name, cx, cy, stations, detailed):
    for i, x in enumerate(stations):
        for y in (-3.45, 3.45):
            top = _solar_point(cx, cy, x, y, -0.23)
            b.beam(
                name + "_leg",
                (top[0], top[1], 0.24),
                top,
                0.23 if detailed else 0.32,
                "graphite_light",
            )
            if detailed:
                b.box(
                    name + "_foot",
                    (top[0], top[1], 0.38),
                    (1.05, 0.9, 0.28),
                    "graphite_light",
                )
        low = _solar_point(cx, cy, x, -3.8, -0.23)
        high = _solar_point(cx, cy, x, 3.8, -0.23)
        b.beam(name + "_crossrail", low, high, 0.23, "graphite_light")
        if detailed:
            b.beam(
                name + "_brace", (low[0], low[1], 0.64), high, 0.13, "graphite_light"
            )
    if detailed:
        # Pair of longitudinal purlins joins the shared row support stations.
        for y in (-2.7, 2.7):
            b.beam(
                name + "_purlin",
                _solar_point(cx, cy, -21.7, y, -0.3),
                _solar_point(cx, cy, 21.7, y, -0.3),
                0.2,
                "graphite_light",
            )


def _inverter(b, name, x, y, lod, large=False):
    width, depth, height = (7.8, 4.2, 4.8) if large else (5.5, 3.8, 4.1)
    b.box(
        name + "_plinth", (x, y, 0.5), (width + 1.1, depth + 1, 0.5), "graphite_light"
    )
    b.box(name + "_body", (x, y, height / 2 + 0.75), (width, depth, height), "graphite")
    b.box(
        name + "_cap",
        (x, y, height + 0.86),
        (width + 0.25, depth + 0.25, 0.25),
        "graphite_light",
    )
    b.beam(
        name + "_lip",
        (x - width / 2, y + depth / 2, height + 1.01),
        (x + width / 2, y + depth / 2, height + 1.01),
        0.12,
        "edge",
    )
    if lod == 2:
        return
    for dx in (-width / 4, width / 4):
        b.box(
            name + "_door",
            (x + dx, y + depth / 2 + 0.06, height / 2 + 0.7),
            (width / 2 - 0.24, 0.10, height - 0.5),
            "graphite_light",
        )
        b.box(
            name + "_handle",
            (x + dx + 0.45, y + depth / 2 + 0.18, 2.7),
            (0.10, 0.12, 0.65),
            "white",
        )
        if lod == 0:
            for j in range(6):
                b.box(
                    name + "_vent",
                    (x + dx, y + depth / 2 + 0.135, 1.3 + j * 0.22),
                    (width / 2 - 0.68, 0.08, 0.075),
                    "graphite",
                )
    if lod == 0:
        b.box(
            name + "_frosted_window",
            (x - width / 4, y + depth / 2 + 0.13, height + 0.1),
            (width / 3, 0.055, 0.48),
            "glass",
        )
        for dx in (-width / 2 - 0.32, width / 2 + 0.32):
            b.polyline(
                name + "_conduit",
                [(x + dx, y, 0.33), (x + dx, y - 0.7, 0.8), (x + dx, y - 0.7, 2.5)],
                0.075,
                "white",
                sides=6,
            )


def build_solar(b, lod):
    """Append a 120 X 150 m solar row field and return the supplied Builder."""
    _check_lod(lod)
    b.box("solar_ground", (0, 0, 0.12), (120, 150, 0.24), "graphite")
    _corners(b, "solar_registration", 120, 150, 7)
    tilt = (math.radians(20), 0, 0)
    for row in range(8):
        cy = -59.5 + row * 15.2
        for bank, cx in enumerate((-28, 28)):
            name = f"solar_r{row:02d}_b{bank}"
            if lod == 0:
                for module in range(7):
                    mx = cx + (module - 3) * 6.2
                    panel = name + f"_module{module}"
                    b.box(
                        panel + "_cassette",
                        _solar_point(mx, cy, 0, 0),
                        (6.02, 8.8, 0.26),
                        "graphite",
                        rotation=tilt,
                    )
                    b.box(
                        panel + "_laminate",
                        _solar_point(mx, cy, 0, 0, 0.145),
                        (5.79, 8.55, 0.025),
                        "graphite_light",
                        rotation=tilt,
                    )
                    _solar_border(b, panel, mx, cy, 6.02, 8.8)
                    # One cross seam suggests cell construction without a dense grid.
                    b.beam(
                        panel + "_seam",
                        _solar_point(mx, cy, -2.9, 0, 0.18),
                        _solar_point(mx, cy, 2.9, 0, 0.18),
                        0.055,
                        "white",
                    )
                    if module in (1, 5):
                        b.box(
                            panel + "_frosted_laminate",
                            _solar_point(mx, cy, 0, 0, 0.19),
                            (5.7, 8.45, 0.025),
                            "glass",
                            rotation=tilt,
                        )
                _solar_rack(
                    b, name, cx, cy, [-21.5 + i * 43 / 7 for i in range(8)], True
                )
                # A single covered tray per row terminates toward the middle aisle.
                b.box(
                    name + "_cable_tray",
                    (cx, cy, 0.37),
                    (44, 0.48, 0.26),
                    "graphite_light",
                )
            else:
                b.box(
                    name + "_row",
                    _solar_point(cx, cy, 0, 0),
                    (43.2, 8.8, 0.28),
                    "graphite_light",
                    rotation=tilt,
                )
                if lod == 1:
                    _solar_border(b, name, cx, cy, 43.2, 8.8)
                    for x in (-10.8, 0, 10.8):
                        b.beam(
                            name + "_module_seam",
                            _solar_point(cx, cy, x, -4.3, 0.18),
                            _solar_point(cx, cy, x, 4.3, 0.18),
                            0.08,
                            "white",
                        )
                    _solar_rack(b, name, cx, cy, (-17, 0, 17), False)
                else:
                    b.beam(
                        name + "_leading",
                        _solar_point(cx, cy, -21.6, -4.4, 0.18),
                        _solar_point(cx, cy, 21.6, -4.4, 0.18),
                        0.18,
                        "edge",
                    )
    # Shared service area is outside the repeated field, in the +Y foreground.
    _inverter(b, "solar_inverter", -8, 65.5, lod, large=True)
    b.box("solar_transformer", (9, 65.5, 2.15), (6, 4.7, 3.8), "graphite_light")
    b.box("solar_transformer_cowl", (9, 65.5, 4.2), (6.4, 5, 0.3), "graphite")
    b.cylinder(
        "solar_feeder_port",
        (9, 67.86, 2.1),
        0.22,
        0.28,
        "white",
        vertices=12 if lod == 0 else 6,
        rotation=(math.pi / 2, 0, 0),
    )
    b.box("solar_status", (-8, 67.67, 4.1), (1.2, 0.11, 0.32), "status")
    if lod < 2:
        b.box("solar_trench", (0, 3, 0.31), (0.65, 125, 0.14), "graphite_light")
        for x in (7.6, 9, 10.4):
            b.cylinder(
                "solar_bushing",
                (x, 65.5, 4.63),
                0.2,
                0.7,
                "white",
                vertices=12 if lod == 0 else 6,
            )
        if lod == 0:
            for side in (-1, 1):
                for i in range(9):
                    b.box(
                        "solar_cooling_fin",
                        (9 + side * 3.1, 63.8 + i * 0.42, 2.4),
                        (0.14, 0.13, 2.8),
                        "graphite",
                    )
            b.polyline(
                "solar_service_link",
                [
                    (-4.15, 65.5, 2.1),
                    (-1, 65.5, 2.1),
                    (-1, 65.5, 0.5),
                    (3.5, 65.5, 0.5),
                    (3.5, 65.5, 2.1),
                    (6, 65.5, 2.1),
                ],
                0.10,
                "white",
            )
    return b


def _fan(b, name, x, y, z, lod):
    """Horizontal fan with a real annular rim and restrained blade geometry."""
    if lod == 2:
        return
    n = 20 if lod == 0 else 8
    b.cylinder(name + "_housing", (x, y, z), 1.28, 0.28, "graphite", vertices=n)
    if lod == 1:
        return
    # A planar, upward-facing annulus has no invisible tube tessellation.
    verts = []
    for radius in (1.1, 1.23):
        verts.extend(
            (
                x + radius * math.cos(i * math.tau / n),
                y + radius * math.sin(i * math.tau / n),
                z + 0.15,
            )
            for i in range(n)
        )
    faces = [(i, i + n, (i + 1) % n + n, (i + 1) % n) for i in range(n)]
    b.mesh(name + "_rim", verts, faces, "white")
    b.cylinder(
        name + "_hub", (x, y, z + 0.19), 0.21, 0.13, "graphite_light", vertices=12
    )
    for blade in range(5):
        a = blade * math.tau / 5
        shape = [(0.19, -0.08), (0.94, 0.10), (0.80, 0.33), (0.25, 0.13)]
        points = [
            (
                x + u * math.cos(a) - v * math.sin(a),
                y + u * math.sin(a) + v * math.cos(a),
                z + 0.155,
            )
            for u, v in shape
        ]
        b.mesh(name + "_blade", points, [(0, 1, 2, 3)], "graphite_light")
    for dy in (-0.58, 0.0, 0.58):
        half = math.sqrt(1.20**2 - dy**2)
        b.beam(
            name + "_guard",
            (x - half, y + dy, z + 0.24),
            (x + half, y + dy, z + 0.24),
            0.055,
            "white",
        )
        for dx in (-half, half):
            b.beam(
                name + "_guard_mount",
                (x + dx, y + dy, z + 0.15),
                (x + dx, y + dy, z + 0.24),
                0.07,
                "white",
            )


def _battery_cabinet(b, name, x, y, lod):
    if lod == 2:
        b.box(name + "_mass", (x, y, 3.15), (6, 12, 5.82), "graphite_light")
        b.box(name + "_cooling_rail", (x, y, 6.27), (3.1, 9.3, 0.42), "graphite")
        b.beam(
            name + "_front_lip",
            (x - 3, y + 6, 6.09),
            (x + 3, y + 6, 6.09),
            0.16,
            "edge",
        )
        return
    b.box(name + "_pad", (x, y, 0.4), (6.8, 12.8, 0.34), "graphite_light")
    if lod == 1:
        b.box(name + "_body", (x, y, 3.23), (6, 12, 5.36), "graphite_light")
        b.box(name + "_roof", (x, y, 6.02), (6.2, 12.2, 0.22), "graphite")
        b.beam(
            name + "_door_seam",
            (x, y + 6.04, 0.9),
            (x, y + 6.04, 5.74),
            0.11,
            "graphite",
        )
    else:
        # Open front shell reveals internal battery shelves through a frosted door.
        b.box(name + "_floor", (x, y, 0.73), (6, 12, 0.32), "graphite")
        b.box(name + "_rear", (x, y - 5.93, 3.36), (6, 0.14, 5.1), "graphite_light")
        for dx in (-2.92, 2.92):
            b.box(
                name + "_side", (x + dx, y, 3.36), (0.16, 11.9, 5.1), "graphite_light"
            )
        b.box(name + "_roof", (x, y, 6.02), (6.2, 12.2, 0.22), "graphite")
        for dx in (-3, 3):
            for dy in (-6, 6):
                b.beam(
                    name + "_corner_post",
                    (x + dx, y + dy, 0.65),
                    (x + dx, y + dy, 6.02),
                    0.16,
                    "white",
                )
            for z in (0.8, 5.86):
                b.beam(
                    name + "_side_rail",
                    (x + dx, y - 6, z),
                    (x + dx, y + 6, z),
                    0.105,
                    "white",
                )
            for dy in (-3, 0, 3):
                b.beam(
                    name + "_side_joint",
                    (x + dx * 1.005, y + dy, 1.0),
                    (x + dx * 1.005, y + dy, 5.64),
                    0.065,
                    "graphite",
                )
        b.box(
            name + "_rack_backplane",
            (x, y + 4.87, 3.22),
            (5.4, 0.16, 4.9),
            "graphite_light",
        )
        for column in range(3):
            dx = (column - 1) * 1.72
            for level in range(4):
                z = 1.32 + level * 1.1
                b.box(
                    name + "_rack_module",
                    (x + dx, y + 5.3, z),
                    (1.45, 0.9, 0.83),
                    "graphite",
                )
                b.box(
                    name + "_rack_pull",
                    (x + dx, y + 5.77, z),
                    (0.6, 0.07, 0.09),
                    "graphite_light",
                )
        b.box(name + "_frosted_front", (x, y + 6.02, 3.3), (5.68, 0.06, 4.74), "glass")
        for dx in (-0.93, 0.93):
            b.beam(
                name + "_door_stile",
                (x + dx, y + 6.1, 0.92),
                (x + dx, y + 6.1, 5.72),
                0.095,
                "white",
            )
        for dx in (-1.07, 1.07):
            b.box(
                name + "_handle", (x + dx, y + 6.17, 3.22), (0.09, 0.38, 0.8), "white"
            )
        b.box(name + "_hvac", (x, y - 6.32, 3.1), (3.5, 0.68, 3.3), "graphite")
        for level in range(7):
            b.box(
                name + "_hvac_louvre",
                (x, y - 6.685, 1.95 + 0.33 * level),
                (3.1, 0.08, 0.1),
                "graphite_light",
            )
        for dx in (-2.35, 2.35):
            b.polyline(
                name + "_coolant",
                [
                    (x + dx, y - 5.95, 1.1),
                    (x + dx, y - 6.55, 1.1),
                    (x + dx, y - 6.55, 4.75),
                    (x + dx, y - 5.95, 4.75),
                ],
                0.07,
                "white",
                sides=6,
            )
    b.beam(
        name + "_front_lip", (x - 3, y + 6, 6.15), (x + 3, y + 6, 6.15), 0.13, "edge"
    )
    for i, dy in enumerate((-3.15, 3.15)):
        _fan(b, name + f"_fan{i}", x, y + dy, 6.27, lod)


def build_battery(b, lod):
    """Append a 50 X 80 m cabinet storage yard and return the supplied Builder."""
    _check_lod(lod)
    b.box("battery_ground", (0, 0, 0.12), (50, 80, 0.24), "graphite")
    _corners(b, "battery_registration", 50, 80, 3.5)
    for column, x in enumerate((-15.6, 0, 15.6)):
        for row, y in enumerate((-25.2, -9.2, 6.8, 22.8)):
            _battery_cabinet(b, f"battery_c{column}_r{row}", x, y, lod)
    _inverter(b, "battery_inverter", -7, 35, lod)
    b.box("battery_switchgear", (7, 35, 2.32), (6.4, 3.8, 4.14), "graphite_light")
    b.box("battery_switchgear_cap", (7, 35, 4.51), (6.65, 4, 0.24), "graphite")
    b.cylinder(
        "battery_feeder_port",
        (7, 36.9, 2.32),
        0.22,
        0.30,
        "white",
        vertices=12 if lod == 0 else 6,
        rotation=(math.pi / 2, 0, 0),
    )
    b.box("battery_status", (-7, 36.96, 3.5), (1.14, 0.11, 0.28), "status")
    if lod < 2:
        for x in (-7.8, 7.8):
            b.box(
                "battery_service_trench",
                (x, -0.5, 0.30),
                (0.45, 64, 0.12),
                "graphite_light",
            )
        for dx in (-1.65, 0, 1.65):
            b.beam(
                "battery_switchgear_seam",
                (7 + dx, 36.94, 0.8),
                (7 + dx, 36.94, 4.2),
                0.085,
                "graphite",
            )
    if lod == 0:
        for x in (-10.8, -3.2, 3.2, 10.8):
            b.cylinder(
                "battery_service_bollard",
                (x, 38.1, 0.98),
                0.16,
                1.5,
                "white",
                vertices=12,
            )
        b.polyline(
            "battery_service_link",
            [(-4.30, 35, 1), (0, 35, 1), (0, 35, 2.2), (3.85, 35, 2.2)],
            0.11,
            "white",
        )
    return b

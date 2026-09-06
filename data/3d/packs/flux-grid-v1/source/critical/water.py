"""Original water-treatment archetype with neutral, generic process geometry.

Tank and filter repetition conveys type only. It encodes no process design,
treatment capacity, throughput, population, or actual utility configuration.
"""

import math

from asset_builder import Builder


def _tank_wall(b, name, x, y, z, radius, depth, lod):
    """A real open annular tank wall, with no coincident full glass bubble."""
    n = (64, 24, 12)[lod]
    inner = radius - 0.72
    verts = []
    for r, zz in (
        (radius, z),
        (radius, z + depth),
        (inner, z + depth),
        (inner, z + 0.4),
    ):
        verts.extend(
            (x + r * math.cos(i * math.tau / n), y + r * math.sin(i * math.tau / n), zz)
            for i in range(n)
        )
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.extend(
            (
                (i, j, n + j, n + i),
                (n + i, n + j, 2 * n + j, 2 * n + i),
                (2 * n + i, 2 * n + j, 3 * n + j, 3 * n + i),
                (3 * n + i, 3 * n + j, j, i),
            )
        )
    b.mesh(name, verts, faces, "graphite_light")
    b.cylinder(name + "_floor", (x, y, z + 0.35), inner, 0.7, "graphite", vertices=n)
    b.cylinder(
        name + "_water",
        (x, y, z + depth - 0.72),
        inner - 0.08,
        0.08,
        "glass",
        vertices=n,
    )


def _clarifier(b, name, x, y, r, lod):
    _tank_wall(b, name, x, y, 1.0, r, 4.2, lod)
    b.cylinder(
        name + "_hub", (x, y, 4.2), 1.3, 4.3, "graphite", vertices=(24, 12, 8)[lod]
    )
    b.box(name + "_bridge", (x, y, 5.6), (r * 1.91, 1.5, 0.50), "graphite_light")
    if lod == 2:
        return
    b.ring(name + "_rim", (x, y, 5.21), r - 0.34, 0.065, "edge", segments=(64, 24)[lod])
    b.box(name + "_drive", (x, y, 6.45), (2.9, 2.4, 1.15), "graphite")
    # Railings and radial support make the ring unequivocally physical equipment.
    for side in (-1, 1):
        yy = y + side * 0.76
        b.beam(
            name + "_bridge_rail",
            (x - r * 0.93, yy, 6.73),
            (x + r * 0.93, yy, 6.73),
            0.085,
            "white",
        )
        if lod == 0:
            for i in range(13):
                xx = x - r * 0.91 + i * r * 1.82 / 12
                b.box(
                    name + "_rail_stanchion",
                    (xx, yy, 6.14),
                    (0.07, 0.07, 1.18),
                    "graphite_light",
                )
    if lod == 0:
        for i in range(32):
            a = i * math.tau / 32
            b.cylinder(
                name + "_rim_post",
                (x + (r - 0.36) * math.cos(a), y + (r - 0.36) * math.sin(a), 5.82),
                0.047,
                1.2,
                "graphite_light",
                vertices=8,
            )
        b.ring(
            name + "_guardrail",
            (x, y, 6.40),
            r - 0.36,
            0.04,
            "graphite_light",
            segments=64,
        )
        for side in (-1, 1):
            b.beam(
                name + "_bridge_truss",
                (x - r * 0.87, y + side * 0.58, 5.25),
                (x, y + side * 0.58, 4.25),
                0.16,
                "graphite",
            )
            b.beam(
                name + "_bridge_truss",
                (x, y + side * 0.58, 4.25),
                (x + r * 0.87, y + side * 0.58, 5.25),
                0.16,
                "graphite",
            )
        # Eccentric outlet channel and ladder are small but modeled physically.
        for i in range(9):
            zz = 1.5 + i * 0.46
            b.beam(
                name + "_ladder_rung",
                (x + r + 0.04, y - 0.42, zz),
                (x + r + 0.04, y + 0.42, zz),
                0.07,
                "white",
            )
        for yy in (y - 0.46, y + 0.46):
            b.beam(
                name + "_ladder_side",
                (x + r + 0.08, yy, 1.2),
                (x + r + 0.08, yy, 5.9),
                0.10,
                "graphite_light",
            )


def _filter(b, name, x, y, w, d, lod):
    b.box(name + "_base", (x, y, 1.7), (w, d, 1.4), "graphite_light")
    b.box(name + "_interior", (x, y, 2.44), (w - 0.8, d - 0.8, 0.15), "graphite")
    b.box(name + "_water", (x, y, 2.53), (w - 1.2, d - 1.2, 0.06), "glass")
    if lod == 2:
        return
    for side in (-1, 1):
        b.box(
            name + "_sidewall",
            (x + side * (w / 2 - 0.2), y, 2.6),
            (0.4, d, 1.0),
            "graphite_light",
        )
        b.box(
            name + "_endwall",
            (x, y + side * (d / 2 - 0.2), 2.6),
            (w, 0.4, 1.0),
            "graphite_light",
        )
    b.box(name + "_lip", (x, y + d / 2 - 0.14, 3.14), (w - 0.3, 0.12, 0.1), "edge")
    if lod == 0:
        for i in range(1, 7):
            b.box(
                name + "_baffle",
                (x - w / 2 + i * w / 7, y, 2.78),
                (0.18, d - 0.8, 0.35),
                "graphite_light",
            )
        for i in range(13):
            yy = y - d / 2 + 0.6 + i * (d - 1.2) / 12
            b.box(
                name + "_surface_grille",
                (x, yy, 2.62),
                (w - 1.0, 0.055, 0.055),
                "graphite_light",
            )


def build(asset_id, lod):
    if asset_id != "water_treatment_plant":
        raise ValueError("water.py builds water_treatment_plant only")
    if lod not in (0, 1, 2):
        raise ValueError("lod must be 0, 1, or 2")
    b = Builder(asset_id, lod)
    b.box("ground_plinth", (0, 0, 0.5), (94, 134, 1.0), "graphite")
    _clarifier(b, "primary_tank", -23, -27, 18.4, lod)
    _clarifier(b, "secondary_tank", 23, -27, 18.4, lod)
    _tank_wall(b, "balancing_tank", -24, 18, 1.0, 14.5, 5.0, lod)
    b.box("process_hall", (23, 18, 7.0), (32, 32, 12), "graphite")
    b.box("hall_roof", (23, 18, 13.1), (32.5, 32.5, 0.35), "graphite_light")
    b.box("pumping_gallery", (0, -55, 4.2), (66, 12, 6.4), "graphite")
    for x in (-29, 0, 29):
        _filter(b, "filter_bed", x, 50, 23, 20, lod)
    b.box("status_inlay", (23, 34.04, 8.8), (4.2, 0.08, 0.38), "status")
    b.connector("MV_FEED", 0, (43, 19, 2.4))
    if lod == 2:
        b.box("hall_glass_front", (23, 34.08, 8.1), (29, 0.10, 5.8), "glass")
        return b

    b.box("hall_frosted_shell_front", (23, 34.08, 8.0), (31, 0.15, 8.7), "glass")
    b.box("hall_frosted_shell_side", (39.08, 18, 8.0), (0.15, 31, 8.7), "glass")
    b.box("hall_roof_edge", (23, 34.29, 13.34), (32.6, 0.10, 0.10), "edge")
    b.box("hall_roof_edge", (39.29, 18, 13.34), (0.10, 32.6, 0.10), "edge")
    b.ring(
        "balancing_tank_rim",
        (-24, 18, 6.01),
        14.17,
        0.065,
        "edge",
        segments=(64, 24)[lod],
    )
    b.box("balance_bridge", (-24, 18, 6.2), (27, 1.2, 0.45), "graphite_light")
    # Smooth pipe runs join physical process objects; they are not UI traces.
    pipe_runs = [
        ((-23, -46, 2.1), (-23, -50, 2.1), (-23, -50, 4.4), (-23, -49, 4.4)),
        ((23, -46, 2.1), (23, -50, 2.1), (23, -50, 4.4), (23, -49, 4.4)),
        ((-4, -27, 2.2), (0, -27, 2.2), (0, 18, 2.2), (-9, 18, 2.2)),
        ((-24, 33, 2.1), (-24, 36, 2.1), (23, 36, 2.1), (23, 35, 5.0)),
        ((23, 35, 2.0), (23, 38, 2.0), (0, 38, 2.0), (0, 40, 2.0)),
    ]
    for i, pts in enumerate(pipe_runs):
        b.polyline(f"process_pipe_{i}", pts, 0.42, "graphite_light", sides=(10, 6)[lod])
    if lod == 1:
        return b

    # Large hall receives human-scale structural bays and modest service equipment.
    for x in (9, 16, 23, 30, 37):
        b.box(
            "hall_front_mullion", (x, 34.22, 7.4), (0.19, 0.24, 10.7), "graphite_light"
        )
    for y in (4, 11, 18, 25, 32):
        b.box(
            "hall_side_mullion", (39.22, y, 7.4), (0.24, 0.19, 10.7), "graphite_light"
        )
    for z in (4.0, 7.5, 11.0):
        b.box("hall_front_transom", (23, 34.24, z), (31.7, 0.21, 0.20), "graphite")
        b.box("hall_side_transom", (39.24, 18, z), (0.21, 31.7, 0.20), "graphite")
    for x in (14, 23, 32):
        b.box("hall_roof_vent", (x, 16, 14), (4.4, 8.0, 1.5), "graphite")
        for y in (13.3, 15.1, 16.9, 18.7):
            b.box(
                "hall_vent_louvre", (x, y, 14.83), (4.0, 0.14, 0.13), "graphite_light"
            )
        b.box("hall_clerestory", (x, 7, 13.40), (4.0, 4.5, 0.15), "glass")
    for x in (-27, -18, -9, 0, 9, 18, 27):
        b.box("gallery_door", (x, -48.94, 3.4), (5.3, 0.11, 4.1), "graphite_light")
        b.box("gallery_clerestory", (x, -48.86, 6.1), (5.1, 0.07, 0.85), "glass")
        for z in (2.0, 3.0, 4.0):
            b.box("gallery_door_reveal", (x, -48.85, z), (5.2, 0.09, 0.045), "graphite")
    b.box("gallery_roof_lip", (0, -48.94, 7.47), (66.3, 0.12, 0.11), "edge")
    # Tank skimmer arm is physical, supported by the central hub.
    b.cylinder("balance_hub", (-24, 18, 4.8), 1.0, 4.8, "graphite_light", vertices=24)
    for side in (-1, 1):
        b.beam(
            "balance_bridge_rail",
            (-37, 18 + side * 0.59, 7.4),
            (-11, 18 + side * 0.59, 7.4),
            0.065,
            "white",
        )
        for x in (-36, -32, -28, -24, -20, -16, -12):
            b.box(
                "balance_rail_post",
                (x, 18 + side * 0.59, 6.82),
                (0.08, 0.08, 1.2),
                "graphite_light",
            )
    # Pump housings, pipe collars, and supports add readable manufacturing detail.
    for x in (-12, 0, 12):
        b.box("pump_skid", (x, -41, 1.2), (4.5, 3.5, 0.4), "graphite_light")
        b.cylinder(
            "pump_motor",
            (x, -41, 2.0),
            0.77,
            2.4,
            "graphite",
            vertices=24,
            rotation=(0, math.pi / 2, 0),
        )
        for dx in (-0.8, -0.4, 0, 0.4, 0.8):
            b.cylinder(
                "motor_fin",
                (x + dx, -41, 2.0),
                0.86,
                0.08,
                "graphite_light",
                vertices=16,
                rotation=(0, math.pi / 2, 0),
            )
        b.box("pump_casing", (x + 1.5, -41, 1.9), (1.0, 1.5, 1.5), "graphite_light")
    for y in (-18, -9, 0, 9):
        b.box("pipe_support", (0, y, 1.50), (1.4, 0.4, 1.0), "graphite")
        b.cylinder(
            "pipe_collar",
            (0, y, 2.2),
            0.50,
            0.13,
            "graphite",
            vertices=16,
            rotation=(math.pi / 2, 0, 0),
        )
    for x in (-29, 0, 29):
        b.polyline(
            "filter_drop",
            [(x, 38, 2.0), (x, 39.3, 2.0), (x, 39.3, 3.5), (x, 40.5, 3.5)],
            0.28,
            "graphite_light",
            sides=10,
        )
        b.box("filter_walkway", (x, 61.5, 1.8), (23, 1.3, 0.40), "graphite_light")
        for xx in (x - 10, x - 5, x, x + 5, x + 10):
            b.box(
                "filter_walkway_post",
                (xx, 62, 2.6),
                (0.08, 0.08, 1.2),
                "graphite_light",
            )
        b.beam(
            "filter_walkway_rail", (x - 11, 62, 3.2), (x + 11, 62, 3.2), 0.075, "white"
        )
    b.box("feeder_pad", (43, 19, 1.18), (2.5, 3.4, 0.36), "graphite_light")
    b.box("feeder_cabinet", (43, 19, 2.0), (1.7, 2.6, 1.3), "graphite")
    return b

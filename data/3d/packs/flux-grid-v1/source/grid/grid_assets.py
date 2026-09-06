"""Original reusable Flux grid equipment archetypes.

No scene mutation occurs here: build() returns the pipeline's batched Builder.
Authored in metres, Z up and +Y forward, with ground-centred catalog footprints.
The forms are original generic equipment geometry and encode no facility identity,
electrical rating, measured output, storage capacity, or operational status.
"""

import math

from asset_builder import Builder

ASSET_IDS = (
    "substation_transformer_yard",
    "wind_turbine",
    "solar_array",
    "battery_storage",
)


def _rect_edge(b, name, x, y, z, width, length, line=0.10, material="edge"):
    b.polyline(
        name,
        [
            (x - width / 2, y - length / 2, z),
            (x + width / 2, y - length / 2, z),
            (x + width / 2, y + length / 2, z),
            (x - width / 2, y + length / 2, z),
            (x - width / 2, y - length / 2, z),
        ],
        line / 2,
        material,
    )


def _chamfer_box(b, name, center, size, chamfer, material="graphite"):
    """Eight-corner solid: bevels are actual silhouette geometry."""
    x, y, z = (a / 2 for a in size)
    cx, cy, cz = center
    c = min(chamfer, x * 0.6, y * 0.6)
    outline = [
        (-x + c, -y),
        (x - c, -y),
        (x, -y + c),
        (x, y - c),
        (x - c, y),
        (-x + c, y),
        (-x, y - c),
        (-x, -y + c),
    ]
    verts = [(cx + px, cy + py, cz + zz) for zz in (-z, z) for px, py in outline]
    faces = [tuple(reversed(range(8))), tuple(range(8, 16))]
    faces += [(i, (i + 1) % 8, (i + 1) % 8 + 8, i + 8) for i in range(8)]
    b.mesh(name, verts, faces, material)


def _ring_y(b, name, center, radius, tube, material, n=24, m=6):
    """Ring about a shaft parallel to Y; actual nacelle bearing geometry."""
    x, y, z = center
    verts = []
    for i in range(n):
        a = math.tau * i / n
        for j in range(m):
            q = math.tau * j / m
            r = radius + tube * math.cos(q)
            verts.append(
                (x + r * math.cos(a), y + tube * math.sin(q), z + r * math.sin(a))
            )
    faces = [
        (
            i * m + j,
            i * m + (j + 1) % m,
            ((i + 1) % n) * m + (j + 1) % m,
            ((i + 1) % n) * m + j,
        )
        for i in range(n)
        for j in range(m)
    ]
    b.mesh(name, verts, faces, material)


def _bushing(b, name, x, y, z, height, lod, radius=0.55):
    n = (18, 10, 6)[lod]
    b.cylinder(
        name + "_stem",
        (x, y, z + height / 2),
        radius * 0.52,
        height,
        "graphite_light",
        vertices=n,
        radius_top=radius * 0.35,
    )
    if lod < 2:
        count = 7 if lod == 0 else 3
        for k in range(count):
            zz = z + 0.25 + (height - 0.55) * k / max(1, count - 1)
            b.cylinder(
                name + "_shed",
                (x, y, zz),
                radius * (1 - 0.22 * k / max(1, count - 1)),
                0.12 if lod == 0 else 0.18,
                "white",
                vertices=n,
                radius_top=radius * 0.74,
            )
    b.cylinder(
        name + "_terminal",
        (x, y, z + height),
        radius * 0.24,
        0.4,
        "edge" if lod < 2 else "graphite_light",
        vertices=n,
    )


def _gantry(b, name, y, lod):
    """Paired open steel masts carrying one transverse high-voltage crossarm."""
    for x in (-36, 36):
        b.box(name + "_pier", (x, y, 0.7), (3.8, 3.8, 0.55), "graphite_light")
        if lod == 2:
            b.beam(name + "_mast", (x, y, 0.95), (x, y, 15), 0.7, "graphite_light")
        else:
            for dx in (-0.65, 0.65):
                for dy in (-0.65, 0.65):
                    b.beam(
                        name + "_mast_leg",
                        (x + dx, y + dy, 0.95),
                        (x + dx * 0.7, y + dy * 0.7, 15),
                        0.24,
                        "graphite_light",
                    )
            steps = 6 if lod == 0 else 3
            for k in range(steps):
                za = 1.0 + k * 14 / steps
                zb = 1.0 + (k + 1) * 14 / steps
                for dy in (-0.65, 0.65):
                    b.beam(
                        name + "_lattice",
                        (x - 0.65, y + dy, za),
                        (x + 0.65, y + dy, zb),
                        0.12,
                        "white" if lod == 0 else "graphite_light",
                    )
                    if lod == 0:
                        b.beam(
                            name + "_lattice_return",
                            (x + 0.65, y + dy, za),
                            (x - 0.65, y + dy, zb),
                            0.10,
                            "graphite_light",
                        )
            if lod == 0:
                for k in range(11):
                    b.beam(
                        name + "_ladder",
                        (x - 0.30, y - 0.9, 1.5 + k * 1.15),
                        (x + 0.3, y - 0.9, 1.5 + k * 1.15),
                        0.08,
                        "graphite_light",
                    )
        b.beam(name + "_mast_cap", (x, y, 15), (x, y, 16.7), 0.15, "white")
    b.beam(name + "_crossarm", (-37, y, 14.65), (37, y, 14.65), 0.5, "graphite_light")
    if lod < 2:
        b.beam(name + "_crossarm_lower", (-36, y, 13.4), (36, y, 13.4), 0.25, "white")
        if lod == 0:
            for k in range(18):
                x = -36 + k * 4
                b.beam(
                    name + "_truss",
                    (x, y, 13.4),
                    (x + 2, y, 14.65),
                    0.12,
                    "graphite_light",
                )
                b.beam(
                    name + "_truss",
                    (x + 2, y, 14.65),
                    (x + 4, y, 13.4),
                    0.12,
                    "graphite_light",
                )


def _transformer(b, name, x, y, lod):
    b.box(name + "_foundation", (x, y, 0.83), (19, 17, 0.8), "graphite_light")
    _chamfer_box(b, name + "_tank", (x, y, 4.55), (9.2, 9.4, 6.55), 0.48, "graphite")
    b.box(name + "_top_cover", (x, y, 7.96), (9.75, 9.95, 0.32), "graphite_light")
    if lod < 2:
        _rect_edge(b, name + "_cover_seam", x, y, 8.14, 9.45, 9.6, 0.12, "white")
    # Both cooler assemblies have real separated vertical radiator fins.
    for side in (-1, 1):
        rx = x + side * 7.08
        if lod == 2:
            b.box(name + "_cooler", (rx, y, 4.2), (3.2, 7.9, 4.3), "graphite_light")
        else:
            fins = 17 if lod == 0 else 5
            for k in range(fins):
                yy = y - 3.8 + 7.6 * k / max(1, fins - 1)
                b.box(
                    name + "_radiator_fin",
                    (rx, yy, 4.2),
                    (3.1, 0.17 if lod == 0 else 0.55, 4.25),
                    "graphite_light",
                )
                if lod == 0:
                    b.beam(
                        name + "_fin_edge",
                        (rx + side * 1.55, yy, 2.2),
                        (rx + side * 1.55, yy, 6.2),
                        0.06,
                        "white",
                    )
            for zz in (2.0, 6.42):
                b.polyline(
                    name + "_cooler_header",
                    [
                        (x + side * 4.7, y - 3.8, zz),
                        (rx, y - 3.8, zz),
                        (rx, y + 3.8, zz),
                        (x + side * 4.7, y + 3.8, zz),
                    ],
                    0.23,
                    "graphite_light",
                    sides=8 if lod == 0 else 4,
                )
    # Neutral status is a slim replaceable strip on the front mechanical panel.
    b.box(name + "_status_strip", (x, y + 4.72, 5.0), (3.6, 0.08, 0.28), "status")
    for phase in (-1, 0, 1):
        _bushing(b, name + "_hv", x + phase * 2.75, y + 1.45, 8.14, 3.5, lod, 0.58)
        if lod < 2:
            _bushing(b, name + "_lv", x + phase * 2.75, y - 2.7, 8.14, 1.9, lod, 0.40)
    if lod == 0:
        # Oil conservator across the rear, small gauges and cable cubicle.
        b.cylinder(
            name + "_conservator",
            (x, y - 3.5, 10.0),
            0.78,
            7.6,
            "graphite_light",
            vertices=24,
            rotation=(0, math.pi / 2, 0),
        )
        for dx in (-2.65, 2.65):
            b.beam(
                name + "_conservator_bracket",
                (x + dx, y - 3.5, 8.12),
                (x + dx, y - 3.5, 9.5),
                0.20,
                "white",
            )
        b.box(
            name + "_control_cubicle",
            (x - 3.3, y + 5.3, 2.65),
            (2.1, 1.0, 2.3),
            "graphite_light",
        )
        b.box(
            name + "_control_glass",
            (x - 3.3, y + 5.82, 3.0),
            (1.45, 0.07, 1.2),
            "glass",
        )
        for zz in (1.9, 2.3, 2.7):
            b.box(
                name + "_cubicle_louvre",
                (x - 3.3, y + 5.84, zz),
                (1.55, 0.1, 0.06),
                "white",
            )
        for dx in (-3.9, 3.9):
            for dy in (-4.0, 4.0):
                b.cylinder(
                    name + "_mount_bolt",
                    (x + dx, y + dy, 1.4),
                    0.18,
                    0.24,
                    "white",
                    vertices=6,
                )
        # Front radiator fans: rings stand on the cooler sides, not floating UI marks.
        for side in (-1, 1):
            rx = x + side * 7.1
            for zz in (3.0, 5.15):
                _ring_y(
                    b,
                    name + "_fan_rim",
                    (rx, y - 4.0, zz),
                    0.83,
                    0.07,
                    "graphite_light",
                    20,
                    5,
                )
                b.cylinder(
                    name + "_fan_hub",
                    (rx, y - 4.0, zz),
                    0.20,
                    0.18,
                    "white",
                    vertices=12,
                    rotation=(math.pi / 2, 0, 0),
                )
                for angle in (0, math.tau / 3, 2 * math.tau / 3):
                    b.beam(
                        name + "_fan_blade",
                        (rx, y - 4.02, zz),
                        (
                            rx + 0.67 * math.cos(angle),
                            y - 4.02,
                            zz + 0.67 * math.sin(angle),
                        ),
                        0.18,
                        "graphite_light",
                    )


def _substation(b, lod):
    # Nominal 90 x 120 m catalog proxy, centred at the origin.
    _chamfer_box(b, "yard_foundation", (0, 0, 0.22), (88, 118, 0.44), 1.4, "graphite")
    if lod < 2:
        _rect_edge(b, "foundation_rim", 0, 0, 0.46, 87.4, 117.4, 0.20, "graphite_light")
    for x in (-26, 0, 26):
        _transformer(b, "transformer", x, -5, lod)
    for y in (41, -31):
        _gantry(b, "gantry", y, lod)
    # Rigid three-run buswork, raised on mechanical insulator columns.
    for phase in (-1, 0, 1):
        x = phase * 26
        b.polyline(
            "longitudinal_bus",
            [
                (x, -30.8, 12.6),
                (x, -17, 12.6),
                (x, -5 + 1.45, 11.65),
                (x, 18, 12.6),
                (x, 41, 12.6),
            ],
            0.15 if lod < 2 else 0.22,
            "white",
            sides=6 if lod == 0 else 4,
        )
        if lod < 2:
            for y in (21, -21):
                b.box(
                    "bus_support_base", (x, y, 0.78), (3.0, 3.0, 0.65), "graphite_light"
                )
                b.cylinder(
                    "bus_support_post",
                    (x, y, 4.7),
                    0.48,
                    7.1,
                    "graphite_light",
                    vertices=12 if lod == 0 else 6,
                )
                _bushing(b, "post_insulator", x, y, 8.1, 4.3, lod, 0.65)
        if lod == 0:
            # Disconnector blades branch off the main bus atop a second bank.
            for yy in (29, -25):
                for dx in (-3.5, 3.5):
                    _bushing(b, "disconnect_insulator", x + dx, yy, 1.0, 4.8, lod, 0.66)
                b.beam(
                    "disconnector_crossrail",
                    (x - 4.3, yy, 1.25),
                    (x + 4.3, yy, 1.25),
                    0.28,
                    "graphite_light",
                )
                b.beam(
                    "disconnector_blade",
                    (x - 3.5, yy, 5.9),
                    (x + 2.8, yy, 7.2),
                    0.17,
                    "white",
                )
                b.polyline(
                    "breaker_bus_drop",
                    [(x, yy, 12.6), (x, yy, 8.4), (x + 2.8, yy, 7.2)],
                    0.10,
                    "graphite_light",
                )
            # Three separate risers land on the transformer terminals.
            for dx in (-2.75, 2.75):
                b.polyline(
                    "tank_jumpers",
                    [(x + dx, -3.55, 11.65), (x + dx, 5, 12.6), (x, 7, 12.6)],
                    0.10,
                    "graphite_light",
                )
    # A control room and outgoing switchgear create clear yard hierarchy.
    b.box("control_room", (-26, -45, 3.1), (20, 14, 5.25), "graphite_light")
    b.box("control_roof", (-26, -45, 5.85), (20.7, 14.7, 0.3), "graphite")
    b.box(
        "control_glazing",
        (-26, -37.96, 3.7),
        (15.5, 0.08, 1.55),
        "glass" if lod < 2 else "graphite",
    )
    b.box("feeder_switchgear", (22, -44, 2.7), (22, 9, 4.5), "graphite_light")
    if lod < 2:
        _rect_edge(b, "roof_edge", -26, -45, 6.02, 20.6, 14.6, 0.16, "edge")
        for x in (13.2, 17.6, 22, 26.4, 30.8):
            b.box("feeder_door", (x, -39.44, 2.6), (3.85, 0.08, 3.45), "graphite")
            b.box("feeder_seam", (x - 1.9, -39.36, 2.6), (0.08, 0.09, 3.42), "white")
        b.polyline(
            "outgoing_feeder",
            [(25, -44, 1.5), (25, -53, 1.5), (25, -56, 1.5)],
            0.24,
            "graphite_light",
        )
    # Terminal ends stay visible and sockets remain the same at every LOD.
    b.polyline("incoming_terminal", [(0, 41, 12.6), (0, 52, 14.0)], 0.19, "white")
    b.polyline(
        "outgoing_terminal",
        [(26, 0, 12.6), (39, 0, 12.6), (43, 0, 12.6)],
        0.19,
        "white",
    )
    if lod == 2:
        b.beam(
            "feeder_terminal", (25, -48, 1.5), (25, -56, 1.5), 0.38, "graphite_light"
        )
    if lod == 0:
        # Sparse practical fencing, with a vehicle opening centred on the front.
        for side in (-1, 1):
            for y in range(-55, 56, 10):
                b.beam(
                    "fence_post",
                    (side * 42, y, 0.48),
                    (side * 42, y, 2.8),
                    0.10,
                    "graphite_light",
                )
            for z in (1.0, 2.6):
                b.beam(
                    "fence_rail",
                    (side * 42, -55, z),
                    (side * 42, 55, z),
                    0.07,
                    "graphite_light",
                )
        for yy in (-55, 55):
            for side in (-1, 1):
                b.beam(
                    "fence_end",
                    (side * 9, yy, 2.6),
                    (side * 42, yy, 2.6),
                    0.07,
                    "graphite_light",
                )
                for x in (12, 22, 32, 42):
                    b.beam(
                        "fence_end_post",
                        (side * x, yy, 0.48),
                        (side * x, yy, 2.8),
                        0.10,
                        "graphite_light",
                    )
        for xx in (-40, 40):
            for yy in (-34, 35):
                b.beam(
                    "light_mast", (xx, yy, 0.46), (xx, yy, 10.3), 0.16, "graphite_light"
                )
                b.box("floodlight", (xx, yy, 10.3), (1.1, 0.5, 0.4), "white")
        for xx in (-30, -22):
            b.box(
                "control_roof_vent", (xx, -45, 6.45), (4.0, 3.5, 0.9), "graphite_light"
            )
            for q in range(7):
                b.box(
                    "vent_louvre",
                    (xx, -46.4 + q * 0.45, 6.92),
                    (3.55, 0.10, 0.12),
                    "graphite",
                )
    b.connector("HV_IN", 0, (0, 52, 14.0))
    b.connector("HV_OUT", 0, (43, 0, 12.6))
    b.connector("MV_FEED", 0, (25, -56, 1.5))
    b.metadata.update(
        {
            "shape_note": "Original generic transformer yard with three tanks, real radiators, bushings, open gantries, busbars and outgoing switchgear. Equipment count asserts no bay rating or facility identity."
        }
    )


def _blade(b, name, angle, lod):
    """Swept, twisted airfoil loft for a deliberately compact horizontal-axis rotor."""
    # Radius, tangent-centre sweep, chord and pitch. The X silhouette stays < 20m.
    stations0 = [
        (0.62, 0.00, 0.44, 0.72),
        (0.92, -0.02, 0.66, 0.63),
        (1.28, -0.09, 0.91, 0.54),
        (1.7, -0.16, 1.12, 0.46),
        (2.2, -0.22, 1.18, 0.36),
        (2.8, -0.22, 1.14, 0.29),
        (3.4, -0.19, 1.03, 0.23),
        (4.0, -0.13, 0.90, 0.18),
        (4.7, -0.06, 0.76, 0.14),
        (5.4, 0.03, 0.63, 0.11),
        (6.1, 0.12, 0.49, 0.08),
        (6.8, 0.24, 0.37, 0.05),
        (7.5, 0.39, 0.27, 0.035),
        (8.1, 0.54, 0.18, 0.02),
        (8.6, 0.69, 0.07, 0.0),
    ]
    indexes = (
        range(len(stations0))
        if lod == 0
        else (0, 2, 4, 6, 8, 10, 12, 14)
        if lod == 1
        else (0, 4, 9, 14)
    )
    stations = [stations0[i] for i in indexes]
    n = (16, 8, 4)[lod]
    verts = []
    ca, sa = math.cos(angle), math.sin(angle)
    for r, sweep, chord, pitch in stations:
        for j in range(n):
            q = math.tau * j / n
            # A lenticular profile with thickened leading edge, tapered trailing edge.
            tx = sweep + chord * 0.5 * math.cos(q)
            normal = chord * 0.13 * math.sin(q) * (0.78 + 0.22 * math.cos(q))
            xp = tx * math.cos(pitch) - normal * math.sin(pitch)
            yp = tx * math.sin(pitch) + normal * math.cos(pitch)
            verts.append((xp * ca + r * sa, 1.95 + yp, 16.5 - xp * sa + r * ca))
    faces = [
        tuple(reversed(range(n))),
        tuple(range((len(stations) - 1) * n, len(stations) * n)),
    ]
    faces += [
        (k * n + j, k * n + (j + 1) % n, (k + 1) * n + (j + 1) % n, (k + 1) * n + j)
        for k in range(len(stations) - 1)
        for j in range(n)
    ]
    b.mesh(name, verts, faces, "graphite_light")
    if lod < 2:
        # One structural leading seam and one short tip accent preserve the airfoil shape.
        lead = []
        tip = []
        for r, sweep, chord, pitch in stations:
            xp = (sweep + chord * 0.5) * math.cos(pitch)
            yp = (sweep + chord * 0.5) * math.sin(pitch)
            lead.append((xp * ca + r * sa, 1.95 + yp, 16.5 - xp * sa + r * ca))
            xp = (sweep - chord * 0.5) * math.cos(pitch)
            yp = (sweep - chord * 0.5) * math.sin(pitch)
            if r > 6:
                tip.append((xp * ca + r * sa, 1.95 + yp, 16.5 - xp * sa + r * ca))
        b.polyline(
            name + "_leading_seam",
            lead,
            0.035 if lod == 0 else 0.045,
            "white",
            sides=6 if lod == 0 else 4,
        )
        if lod == 0 and len(tip) > 1:
            b.polyline(name + "_tip_seam", tip, 0.035, "edge", sides=6)


def _wind(b, lod):
    # Compact wind archetype: 17.4m rotor silhouette inside catalog 20x20m proxy.
    _chamfer_box(b, "turbine_apron", (0, 0, 0.19), (8.8, 8.8, 0.38), 1.3, "graphite")
    b.cylinder(
        "foundation",
        (0, 0, 0.60),
        1.85,
        0.44,
        "graphite_light",
        vertices=(48, 20, 8)[lod],
    )
    b.cylinder(
        "tapered_tower",
        (0, 0, 8.65),
        1.05,
        15.7,
        "graphite_light",
        vertices=(48, 20, 8)[lod],
        radius_top=0.51,
    )
    b.box("mast_status_insert", (0, 1.047, 2.35), (0.34, 0.028, 0.60), "status")
    if lod < 2:
        # Service door and bolted structural tower flange; no decorative rings.
        b.box("tower_service_door", (0, 1.00, 1.75), (0.68, 0.16, 1.55), "graphite")
        b.box("door_threshold", (0, 1.17, 0.98), (0.9, 0.3, 0.12), "white")
        b.box("door_handle", (0.22, 1.105, 1.82), (0.06, 0.05, 0.24), "white")
        b.ring(
            "base_flange",
            (0, 0, 0.88),
            1.18,
            0.08,
            "white",
            segments=48 if lod == 0 else 20,
        )
        if lod == 0:
            for i in range(16):
                q = math.tau * i / 16
                b.cylinder(
                    "anchor_bolt",
                    (1.4 * math.cos(q), 1.4 * math.sin(q), 0.94),
                    0.06,
                    0.24,
                    "white",
                    vertices=8,
                )
            for z in (6.3, 11.5):
                rr = 1.05 - (z - 0.8) / 15.7 * 0.54
                b.ring(
                    "tower_section_joint",
                    (0, 0, z),
                    rr + 0.012,
                    0.020,
                    "graphite",
                    segments=48,
                )
            b.polyline(
                "tower_service_seam",
                [
                    (0.83, -0.62, 0.9),
                    (0.67, -0.50, 6.3),
                    (0.49, -0.36, 11.5),
                    (0.37, -0.28, 16.45),
                ],
                0.025,
                "graphite",
            )
    # Structural shaft and gearbox are visible behind a limited clear service panel.
    b.cylinder(
        "yaw_bearing", (0, 0, 16.15), 0.68, 0.50, "graphite", vertices=(32, 16, 8)[lod]
    )
    if lod == 2:
        _chamfer_box(
            b, "nacelle_lower", (0, -0.20, 16.50), (1.74, 3.7, 1.3), 0.30, "graphite"
        )
    else:
        # Open service-side shell lets the actual gearbox be seen through its window.
        _chamfer_box(
            b, "nacelle_floor", (0, -0.20, 16.02), (1.74, 3.7, 0.34), 0.25, "graphite"
        )
        b.box("nacelle_far_side", (-0.80, -0.20, 16.66), (0.16, 3.7, 0.98), "graphite")
        b.box(
            "nacelle_near_sill",
            (0.80, -0.20, 16.24),
            (0.16, 3.7, 0.18),
            "graphite_light",
        )
        b.box("nacelle_front_bulkhead", (0, 1.60, 16.65), (1.58, 0.13, 1.0), "graphite")
    b.box("nacelle_roof", (0, -0.25, 17.16), (1.70, 3.55, 0.16), "graphite_light")
    b.box("nacelle_rear", (0, -2.03, 16.65), (1.5, 0.10, 0.95), "graphite_light")
    if lod < 2:
        # A narrow side panel reveals shafts without turning the entire nacelle into glass.
        b.box(
            "nacelle_side_window", (0.879, -0.38, 16.68), (0.028, 2.25, 0.61), "glass"
        )
        for yy in (-1.30, 0.55):
            b.beam(
                "window_stile", (0.903, yy, 16.32), (0.903, yy, 17.0), 0.045, "white"
            )
        b.beam(
            "window_header", (0.903, -1.32, 17.0), (0.903, 0.58, 17.0), 0.045, "edge"
        )
    b.cylinder(
        "main_shaft",
        (0, 0.3, 16.5),
        0.22,
        3.0,
        "white",
        vertices=(24, 12, 6)[lod],
        rotation=(math.pi / 2, 0, 0),
    )
    b.ellipsoid(
        "rotor_hub",
        (0, 1.95, 16.5),
        (0.78, 0.65, 0.78),
        "graphite_light",
        segments=(32, 16, 8)[lod],
        rings=(16, 8, 4)[lod],
    )
    if lod < 2:
        _ring_y(
            b,
            "hub_seam",
            (0, 1.63, 16.5),
            0.65,
            0.038,
            "white",
            n=32 if lod == 0 else 16,
            m=6 if lod == 0 else 4,
        )
    if lod == 1:
        for yy, rr in ((-0.90, 0.50), (0.08, 0.38)):
            b.cylinder(
                "gearbox_casing",
                (0, yy, 16.55),
                rr,
                0.50,
                "graphite_light",
                vertices=12,
                rotation=(math.pi / 2, 0, 0),
            )
    if lod == 0:
        # Actual rotor bearings and gears are useful mechanical close-up detail.
        for yy, rr in ((-1.10, 0.48), (-0.62, 0.55), (0.1, 0.42), (0.64, 0.34)):
            b.cylinder(
                "gearbox_casing",
                (0, yy, 16.55),
                rr,
                0.40,
                "graphite_light",
                vertices=32,
                rotation=(math.pi / 2, 0, 0),
            )
            _ring_y(
                b,
                "gearbox_seal",
                (0, yy + 0.21, 16.55),
                rr * 0.90,
                0.035,
                "white",
                24,
                6,
            )
        for i in range(12):
            q = math.tau * i / 12
            b.cylinder(
                "hub_flange_bolt",
                (0.52 * math.cos(q), 1.58, 16.5 + 0.52 * math.sin(q)),
                0.035,
                0.08,
                "white",
                vertices=6,
                rotation=(math.pi / 2, 0, 0),
            )
        for k in range(13):
            b.box(
                "rear_vent",
                (-0.56 + 0.093 * k, -2.098, 16.67),
                (0.032, 0.06, 0.64),
                "graphite",
            )
        b.beam(
            "nacelle_lift_rail",
            (-0.62, -1.75, 17.31),
            (-0.62, 1.18, 17.31),
            0.05,
            "white",
        )
        b.beam(
            "nacelle_lift_rail",
            (0.62, -1.75, 17.31),
            (0.62, 1.18, 17.31),
            0.05,
            "white",
        )
        # Ground-side compact converter, trench stub, and tower working step.
        b.box("service_step", (0, 1.52, 0.5), (1.2, 0.7, 0.24), "graphite_light")
    for k in range(3):
        _blade(b, "rotor_blade", k * math.tau / 3, lod)
    b.box("converter", (2.9, -1.3, 1.12), (1.3, 1.15, 1.85), "graphite_light")
    if lod < 2:
        b.box("converter_front", (2.9, -0.70, 1.19), (1.09, 0.06, 1.51), "graphite")
        for zz in (0.6, 0.8, 1.0, 1.2, 1.4) if lod == 0 else (0.8, 1.2):
            b.box("converter_louvre", (2.9, -0.655, zz), (0.83, 0.035, 0.045), "white")
    b.polyline(
        "feeder_stub",
        [(2.9, -1.8, 0.28), (2.9, -3.75, 0.28), (3.7, -3.75, 0.28)],
        0.07 if lod < 2 else 0.10,
        "graphite_light",
        sides=6 if lod == 0 else 4,
    )
    b.connector("MV_FEED", 0, (3.7, -3.75, 0.28))
    b.metadata.update(
        {
            "shape_note": "Original compact three-blade horizontal-axis turbine. Its approximately 17.4m rotor silhouette deliberately fits the 20m catalog proxy. Rotor geometry and converter carry no output or wind-speed claim."
        }
    )


def build(asset_id, lod):
    if asset_id not in ASSET_IDS:
        raise ValueError(f"Unsupported grid archetype: {asset_id}")
    if lod not in (0, 1, 2):
        raise ValueError("lod must be 0, 1 or 2")
    b = Builder(asset_id, lod)
    if asset_id == "substation_transformer_yard":
        _substation(b, lod)
    elif asset_id == "wind_turbine":
        _wind(b, lod)
    else:
        from solar_battery import build_battery, build_solar

        if asset_id == "solar_array":
            build_solar(b, lod)
            b.connector("MV_FEED", 0, (9, 68.0, 2.1))
        else:
            build_battery(b, lod)
            b.connector("MV_FEED", 0, (7, 37.05, 2.32))
    return b

"""Original, identity-free Flux district archetypes.

Public API: build(asset_id, lod) -> asset_builder.Builder. Importing this module
does not import Blender or create scene state. Geometry is authored in metres,
Z-up, with +Y forward. The shared exporter owns glTF conversion and materials.
"""

import math

ASSET_IDS = (
    "data_center_campus",
    "residential_neighborhood",
    "commercial_buildings",
    "factory_industrial_facility",
    "warehouse_logistics_center",
    "ev_charging_station",
)

FOOTPRINTS = {
    "data_center_campus": (150, 220),
    "residential_neighborhood": (180, 180),
    "commercial_buildings": (100, 120),
    "factory_industrial_facility": (140, 200),
    "warehouse_logistics_center": (120, 180),
    "ev_charging_station": (25, 40),
}


def _quad(b, name, vertices, material="glass"):
    # Front and clerestory panes face +Y; tower side panes are already ordered
    # outward. Glass remains double-sided in the common material contract.
    face = (3, 2, 1, 0) if len({v[1] for v in vertices}) == 1 else (0, 1, 2, 3)
    b.mesh(name, vertices, [face], material)


def _gable(b, name, x, y, width, depth, eave, rise, material="graphite"):
    """Closed pitched roof, ridge parallel to the street frontage axis."""
    vertices = [
        (x - width / 2, y - depth / 2, eave),
        (x + width / 2, y - depth / 2, eave),
        (x, y - depth / 2, eave + rise),
        (x - width / 2, y + depth / 2, eave),
        (x + width / 2, y + depth / 2, eave),
        (x, y + depth / 2, eave + rise),
    ]
    b.mesh(
        name,
        vertices,
        [(1, 2, 0), (5, 4, 3), (3, 4, 1, 0), (4, 5, 2, 1), (5, 3, 0, 2)],
        material,
    )


def _site(b, width, length, lod, feeder_x=None):
    b.box("grade_plinth", (0, 0, 0.24), (width * 0.97, length * 0.97, 0.48), "graphite")
    # A small neutral equipment panel is the runtime's status tint surface.
    fx = width * 0.42 if feeder_x is None else feeder_x
    fy = length * 0.39
    b.box("feeder_cabinet", (fx, fy, 1.85), (2.4, 2.6, 2.74), "graphite_light")
    b.box("neutral_service_panel", (fx, fy + 1.31, 1.95), (1.6, 0.055, 1.65), "status")
    b.connector("MV_FEED", 0, (fx, fy, 3.25))
    if lod == 0:
        # Sparse surveyed-looking corner ticks, not a glowing plot boundary.
        for sx in (-1, 1):
            for sy in (-1, 1):
                x, y = sx * width * 0.46, sy * length * 0.46
                b.beam(
                    "corner_datum", (x, y, 0.55), (x - sx * 4, y, 0.55), 0.10, "white"
                )
                b.beam(
                    "corner_datum", (x, y, 0.55), (x, y - sy * 4, 0.55), 0.10, "white"
                )


def _top_edges(b, name, x, y, z, width, depth, line=0.15, material="edge"):
    p = [
        (x - width / 2, y - depth / 2, z),
        (x + width / 2, y - depth / 2, z),
        (x + width / 2, y + depth / 2, z),
        (x - width / 2, y + depth / 2, z),
    ]
    for a, c in zip(p, p[1:] + p[:1]):
        b.beam(name, a, c, line, material)


def _fan(b, name, x, y, z, radius, lod):
    b.cylinder(
        name + "_housing",
        (x, y, z),
        radius,
        0.65,
        "graphite_light",
        vertices=16 if lod == 0 else 8,
    )
    if lod == 0:
        b.ring(
            name + "_guard", (x, y, z + 0.39), radius * 0.82, 0.09, "white", segments=16
        )
        b.cylinder(
            name + "_hub", (x, y, z + 0.43), radius * 0.20, 0.15, "graphite", vertices=8
        )
        for angle in (0, math.tau / 3, math.tau * 2 / 3):
            ca, sa = math.cos(angle), math.sin(angle)
            points = [
                (x + radius * 0.22 * ca, y + radius * 0.22 * sa, z + 0.49),
                (
                    x + radius * 0.75 * ca - radius * 0.20 * sa,
                    y + radius * 0.75 * sa + radius * 0.20 * ca,
                    z + 0.49,
                ),
                (
                    x + radius * 0.82 * ca + radius * 0.11 * sa,
                    y + radius * 0.82 * sa - radius * 0.11 * ca,
                    z + 0.49,
                ),
            ]
            b.mesh(name + "_blade", points, [(0, 1, 2)], "graphite")


def _data_center(b, lod):
    _site(b, 150, 220, lod)
    for j, y in enumerate((-65, -3, 59)):
        x, w, d, h = -7, 112, 43, 14
        if lod == 2:
            b.box("hall_mass", (x, y, 7.5), (w, d, h), "graphite")
            b.box("cooling_spine", (x, y, 15.5), (w * 0.90, 8, 2), "graphite_light")
            continue
        # Open front construction exposes repeated server aisles through aqua glass.
        b.box("hall_floor", (x, y, 0.95), (w, d, 0.9), "graphite_light")
        b.box("hall_back", (x, y - d / 2 + 0.55, 7.4), (w, 1.1, 13), "graphite")
        b.box("hall_roof", (x, y, 14.25), (w + 1.0, d + 1.0, 1.0), "graphite")
        for sx in (-1, 1):
            b.box(
                "hall_end", (x + sx * (w / 2 - 0.6), y, 7.4), (1.2, d, 13), "graphite"
            )
        b.box("hall_front_apron", (x, y + d / 2, 2.0), (w, 1.1, 3.0), "graphite")
        _quad(
            b,
            "hall_glazed_band",
            [
                (x - w / 2 + 0.7, y + d / 2 + 0.02, 3.5),
                (x + w / 2 - 0.7, y + d / 2 + 0.02, 3.5),
                (x + w / 2 - 0.7, y + d / 2 + 0.02, 13.7),
                (x - w / 2 + 0.7, y + d / 2 + 0.02, 13.7),
            ],
        )
        for k in range(9 if lod == 0 else 5):
            rx = x - 47 + k * (94 / (8 if lod == 0 else 4))
            b.box(
                "visible_server_aisle",
                (rx, y + 12, 6.3),
                (5.0, 6.0, 9.5),
                "graphite_light",
            )
            if lod == 0:
                for sz in (3.3, 5.2, 7.1, 9.0):
                    b.box(
                        "rack_separator",
                        (rx, y + 15.05, sz),
                        (4.5, 0.075, 0.11),
                        "white",
                    )
                b.beam(
                    "facade_mullion",
                    (rx, y + d / 2 + 0.12, 3.6),
                    (rx, y + d / 2 + 0.12, 13.7),
                    0.16,
                    "graphite_light",
                )
        for dy in (-10, 7):
            b.box(
                "cooling_channel",
                (x, y + dy, 15.20),
                (101, 7.2, 0.95),
                "graphite_light",
            )
            for k in range(9 if lod == 0 else 4):
                px = x - 44 + k * (88 / (8 if lod == 0 else 3))
                _fan(b, "roof_fan", px, y + dy, 16.0, 2.6, lod)
        _top_edges(b, "hall_roof_datum", x, y, 14.82, w + 1, d + 1, 0.18)
        if lod == 0:
            for k in range(15):
                rx = x - 50 + k * 100 / 14
                b.beam(
                    "roof_seam",
                    (rx, y - 20, 14.83),
                    (rx, y + 20, 14.83),
                    0.055,
                    "graphite_light",
                )
            for sx in (-1, 1):
                b.polyline(
                    "coolant_header",
                    [
                        (x + sx * 53, y - 13, 15.1),
                        (x + sx * 53, y + 12, 15.1),
                        (x + sx * 53, y + 12, 5.0),
                    ],
                    0.19,
                    "graphite_light",
                    sides=6,
                )
    b.box("administration_spine", (-17, 94, 5.0), (69, 15, 9.0), "graphite_light")
    if lod < 2:
        b.box("entry_awning", (-17, 104, 7.7), (44, 5, 0.45), "graphite")
        _quad(
            b,
            "administration_glazing",
            [
                (-49, 101.56, 1.6),
                (15, 101.56, 1.6),
                (15, 101.56, 8.7),
                (-49, 101.56, 8.7),
            ],
        )
        b.beam(
            "awning_leading_edge", (-39, 106.5, 7.97), (5, 106.5, 7.97), 0.14, "white"
        )
    if lod == 0:
        for y in (-88, -26, 36):
            b.box("service_lane", (-7, y, 0.52), (111, 5, 0.06), "graphite_light")
        for y in (-74, -53, -12, 9, 50, 71):
            b.box(
                "perimeter_cooling_cabinet", (63, y, 3.2), (8, 9, 5.4), "graphite_light"
            )
            for dz in (1.5, 2.3, 3.1, 3.9, 4.7):
                b.box("cabinet_louver", (67.06, y, dz), (0.10, 7.4, 0.16), "graphite")
        b.box("cable_route", (54, -4, 0.72), (2.6, 179, 0.40), "graphite_light")


def _house(b, x, y, variation, lod):
    w, d, eave = 19.0, 24.0, 8.8 + (variation % 2) * 1.2
    b.box(
        "home_wall_mass",
        (x, y, 4.8),
        (w, d, 8.6),
        "graphite_light" if variation % 3 == 0 else "graphite",
    )
    _gable(b, "pitched_home_roof", x, y, w + 1.5, d + 1.6, eave, 5.5, "graphite")
    if lod == 2:
        return
    # Roof ridges and real facade bays preserve the residential reading at map scale.
    b.beam(
        "ridge_cap",
        (x, y - d / 2 - 0.8, eave + 5.56),
        (x, y + d / 2 + 0.8, eave + 5.56),
        0.16,
        "white",
    )
    b.box("entry_canopy", (x - 4, y + 14, 3.35), (5.5, 4, 0.32), "graphite_light")
    for wx in (-5.8, 4.8):
        b.box(
            "window_recess",
            (x + wx, y + 12.03, 5.3),
            (4.6, 0.07, 3.3),
            "graphite_light",
        )
        _quad(
            b,
            "window_pane",
            [
                (x + wx - 2, y + 12.08, 3.85),
                (x + wx + 2, y + 12.08, 3.85),
                (x + wx + 2, y + 12.08, 6.8),
                (x + wx - 2, y + 12.08, 6.8),
            ],
        )
    if lod == 0:
        for sx in (-1, 1):
            b.beam(
                "front_roof_rake",
                (x + sx * (w / 2 + 0.8), y + d / 2 + 0.86, eave),
                (x, y + d / 2 + 0.86, eave + 5.5),
                0.10,
                "edge",
            )
            b.beam(
                "gutter",
                (x + sx * (w / 2 + 0.8), y - d / 2 - 0.8, eave),
                (x + sx * (w / 2 + 0.8), y + d / 2 + 0.8, eave),
                0.11,
                "white",
            )
            b.beam(
                "downpipe",
                (x + sx * (w / 2 + 0.3), y + d / 2 + 0.7, 0.9),
                (x + sx * (w / 2 + 0.3), y + d / 2 + 0.7, eave),
                0.11,
                "graphite_light",
            )
            for wy in (-7.2, 1.2, 7.7):
                b.box(
                    "side_window",
                    (x + sx * (w / 2 + 0.025), y + wy, 5.5),
                    (0.045, 3.8, 3.1),
                    "glass",
                )
                b.beam(
                    "side_window_sill",
                    (x + sx * (w / 2 + 0.065), y + wy - 2, 3.9),
                    (x + sx * (w / 2 + 0.065), y + wy + 2, 3.9),
                    0.10,
                    "white",
                )
        for wx in (-5.8, 4.8):
            b.beam(
                "window_mullion",
                (x + wx, y + 12.13, 3.8),
                (x + wx, y + 12.13, 6.9),
                0.11,
                "white",
            )
            b.beam(
                "window_sill",
                (x + wx - 2.2, y + 12.14, 3.75),
                (x + wx + 2.2, y + 12.14, 3.75),
                0.11,
                "white",
            )
        for px in (-6.2, -1.8):
            b.beam(
                "porch_post",
                (x + px, y + 15.4, 0.65),
                (x + px, y + 15.4, 3.15),
                0.20,
                "graphite_light",
            )
        b.box(
            "front_door", (x - 4, y + 12.1, 1.95), (2.0, 0.08, 2.75), "graphite_light"
        )
        b.box("porch_step", (x - 4, y + 14.3, 0.68), (6, 4.2, 0.35), "graphite_light")
        b.box(
            "chimney", (x + 5.2, y - 5, eave + 2.6), (1.8, 2.3, 4.0), "graphite_light"
        )
        b.box("driveway", (x + 6, y + 16.5, 0.52), (5.0, 8.0, 0.08), "graphite_light")
        for delta in (-6, -2, 2, 6):
            # Thin seams follow both pitched roof planes, visible as material breaks.
            for sx in (-1, 1):
                b.beam(
                    "roof_seam",
                    (x + sx * (w / 2 + 0.6), y + delta, eave + 0.06),
                    (x, y + delta, eave + 5.56),
                    0.05,
                    "graphite_light",
                )


def _residential(b, lod):
    _site(b, 180, 180, lod, feeder_x=79)
    b.box("east_west_street", (0, 0, 0.52), (169, 12, 0.07), "graphite_light")
    # The crossing belongs to the east-west strip. Two abutting segments avoid
    # coplanar faces and the black intersection patch seen in the first preview.
    for y in (-45.25, 45.25):
        b.box("north_south_street", (0, y, 0.52), (12, 78.5, 0.07), "graphite_light")
    coordinates = [(x, y) for y in (-65, -24, 24, 65) for x in (-65, -25, 25, 65)]
    for index, (x, y) in enumerate(coordinates):
        _house(b, x, y, index, lod)
    if lod < 2:
        for y in (-44.5, 45):
            b.box("local_lane", (0, y, 0.53), (163, 5.0, 0.08), "graphite_light")
        if lod == 0:
            for a in range(-76, 77, 12):
                b.box("street_center_dash", (a, 0, 0.58), (4.0, 0.18, 0.03), "white")
                b.box("street_center_dash", (0, a, 0.58), (0.18, 4.0, 0.03), "white")
            for x, y in (
                (-47, -70),
                (46, -65),
                (-46, -25),
                (46, -23),
                (-45, 25),
                (45, 24),
                (-47, 66),
                (46, 66),
            ):
                b.cylinder(
                    "tree_trunk", (x, y, 2.0), 0.35, 3.0, "graphite_light", vertices=8
                )
                b.ellipsoid(
                    "faceted_tree_crown",
                    (x, y, 5.4),
                    (3.4, 3.6, 4.1),
                    "graphite_light",
                    segments=12,
                    rings=5,
                )
            for x in (-9, 9):
                for y in (-70, 27, 69):
                    b.beam(
                        "street_lamp_pole",
                        (x, y, 0.58),
                        (x, y, 7.0),
                        0.14,
                        "graphite_light",
                    )
                    b.box(
                        "street_lamp_head", (x, y + 0.5, 7.0), (0.5, 1.4, 0.16), "white"
                    )


def _tower(b, name, x, y, w, d, base, h, lod):
    if lod == 2:
        b.box(name + "_mass", (x, y, base + h / 2), (w, d, h), "graphite_light")
        return
    # Compact concrete core plus transparent outer facade: no opaque duplicate shell.
    b.box(
        name + "_core",
        (x, y - d * 0.15, base + h / 2),
        (w * 0.50, d * 0.63, h),
        "graphite",
    )
    b.box(name + "_roof", (x, y, base + h - 0.25), (w, d, 0.6), "graphite")
    _quad(
        b,
        name + "_front_glass",
        [
            (x - w / 2, y + d / 2, base),
            (x + w / 2, y + d / 2, base),
            (x + w / 2, y + d / 2, base + h),
            (x - w / 2, y + d / 2, base + h),
        ],
    )
    _quad(
        b,
        name + "_east_glass",
        [
            (x + w / 2, y - d / 2, base),
            (x + w / 2, y + d / 2, base),
            (x + w / 2, y + d / 2, base + h),
            (x + w / 2, y - d / 2, base + h),
        ],
    )
    _quad(
        b,
        name + "_west_glass",
        [
            (x - w / 2, y + d / 2, base),
            (x - w / 2, y - d / 2, base),
            (x - w / 2, y - d / 2, base + h),
            (x - w / 2, y + d / 2, base + h),
        ],
    )
    _top_edges(b, name + "_crown", x, y, base + h + 0.10, w, d, 0.16)
    for sx in (-1, 1):
        b.beam(
            name + "_corner",
            (x + sx * w / 2, y + d / 2, base),
            (x + sx * w / 2, y + d / 2, base + h),
            0.16,
            "white",
        )
    if lod == 0:
        for z in range(4, int(h), 4):
            b.box(
                name + "_floor",
                (x, y, base + z),
                (w - 0.4, d - 0.4, 0.22),
                "graphite_light",
            )
            b.beam(
                name + "_floor_datum",
                (x - w / 2, y + d / 2 + 0.03, base + z),
                (x + w / 2, y + d / 2 + 0.03, base + z),
                0.08,
                "white",
            )
        for k in range(1, 9):
            px = x - w / 2 + w * k / 9
            b.beam(
                name + "_facade_mullion",
                (px, y + d / 2 + 0.06, base),
                (px, y + d / 2 + 0.06, base + h),
                0.095,
                "graphite_light",
            )
        for k in range(1, 7):
            py = y - d / 2 + d * k / 7
            for sx in (-1, 1):
                b.beam(
                    name + "_side_mullion",
                    (x + sx * w / 2, py, base),
                    (x + sx * w / 2, py, base + h),
                    0.095,
                    "graphite_light",
                )
        for rx in (-0.24, 0.24):
            b.box(
                name + "_roof_plant",
                (x + rx * w, y - d * 0.2, base + h + 1.1),
                (w * 0.24, d * 0.24, 1.6),
                "graphite_light",
            )
            _fan(
                b,
                name + "_roof_plant_fan",
                x + rx * w,
                y - d * 0.2,
                base + h + 2.0,
                min(w, d) * 0.09,
                lod,
            )
    else:
        for z in (h * 0.33, h * 0.66):
            b.box(
                name + "_floor_hint",
                (x, y, base + z),
                (w - 0.4, d - 0.4, 0.26),
                "graphite_light",
            )


def _commercial(b, lod):
    _site(b, 100, 120, lod)
    b.box("shared_podium", (0, -7, 4.45), (86, 77, 7.9), "graphite")
    _tower(b, "west_office", -24, -22, 30, 34, 8.4, 47, lod)
    _tower(b, "east_office", 23, 8, 32, 35, 8.4, 31, lod)
    _tower(b, "rear_service_mass", 20, -34, 30, 21, 8.4, 18, lod)
    b.box("retail_pavilion", (-22, 42, 4.4), (36, 18, 7.8), "graphite_light")
    if lod == 2:
        return
    b.box("entry_canopy", (-6, 34, 7.4), (40, 9, 0.48), "graphite_light")
    b.beam("entry_canopy_datum", (-26, 38.5, 7.7), (14, 38.5, 7.7), 0.17, "white")
    _quad(
        b,
        "podium_front_glass",
        [(-41, 31.56, 1.0), (41, 31.56, 1.0), (41, 31.56, 7.5), (-41, 31.56, 7.5)],
    )
    b.box("sky_link_floor", (-1, -2, 21), (20, 10, 0.45), "graphite_light")
    b.box("sky_link_roof", (-1, -2, 26), (20, 10, 0.40), "graphite")
    _quad(b, "sky_link_glass", [(-11, 3, 21), (9, 3, 21), (9, 3, 26), (-11, 3, 26)])
    if lod == 0:
        for x in (-24, -12, 0, 12):
            b.beam(
                "entry_colonnade", (x, 35, 0.6), (x, 35, 7.3), 0.32, "graphite_light"
            )
        for x in range(-38, 42, 8):
            b.beam("shopfront_mullion", (x, 31.7, 1.0), (x, 31.7, 7.6), 0.13, "white")
        for y in (-40, -22, -4, 14):
            b.box("terrace_joint", (-42, y, 8.47), (4, 0.10, 0.05), "graphite_light")
        for x, y in ((-40, 41), (4, 45), (35, 42)):
            b.box("plaza_planter", (x, y, 1.1), (5, 5, 1.2), "graphite_light")
            b.ellipsoid(
                "plaza_tree",
                (x, y, 4.9),
                (2.6, 2.8, 3.5),
                "graphite_light",
                segments=12,
                rings=5,
            )
        for y in (39, 44, 49):
            b.box("entry_paver_joint", (22, y, 0.53), (30, 0.08, 0.03), "white")


def _sawtooth(b, x, y, width, depth, eave, rise, glass=True):
    # A triangular prism per bay creates an actual sawtooth roof silhouette.
    verts = [
        (x - width / 2, y - depth / 2, eave),
        (x - width / 2, y + depth / 2, eave),
        (x - width / 2, y + depth / 2, eave + rise),
        (x + width / 2, y - depth / 2, eave),
        (x + width / 2, y + depth / 2, eave),
        (x + width / 2, y + depth / 2, eave + rise),
    ]
    b.mesh(
        "sawtooth_roof",
        verts,
        [(2, 1, 0), (4, 5, 3), (1, 4, 3, 0), (3, 5, 2, 0), (2, 5, 4, 1)],
        "graphite",
    )
    if glass:
        _quad(
            b,
            "clerestory_glass",
            [
                (x - width / 2 + 0.5, y + depth / 2 + 0.025, eave + 0.5),
                (x + width / 2 - 0.5, y + depth / 2 + 0.025, eave + 0.5),
                (x + width / 2 - 0.5, y + depth / 2 + 0.025, eave + rise - 0.5),
                (x - width / 2 + 0.5, y + depth / 2 + 0.025, eave + rise - 0.5),
            ],
        )


def _factory(b, lod):
    _site(b, 140, 200, lod)
    b.box("production_hall_mass", (-11, -22, 9.5), (101, 120, 18), "graphite")
    # Six sawtooth bays remain at every distance; details disappear progressively.
    for j in range(6):
        y = -70.5 + j * 23
        _sawtooth(b, -11, y, 102, 23, 18.5, 7, lod < 2)
        if lod < 2:
            b.beam(
                "clerestory_top_rail",
                (-62, y + 11.55, 25.55),
                (40, y + 11.55, 25.55),
                0.18,
                "white",
            )
        if lod == 0:
            for x in range(-55, 37, 9):
                b.beam(
                    "roof_fold_seam",
                    (x, y - 11.5, 18.56),
                    (x, y + 11.5, 25.56),
                    0.075,
                    "graphite_light",
                )
                b.beam(
                    "clerestory_mullion",
                    (x, y + 11.56, 18.9),
                    (x, y + 11.56, 25.2),
                    0.12,
                    "graphite_light",
                )
    b.box("administration_wing", (9, 77, 6.5), (73, 22, 12), "graphite_light")
    b.box("side_utility_block", (53, -8, 6.0), (20, 67, 11), "graphite_light")
    b.cylinder(
        "utility_vent",
        (-52, -72, 22),
        2.1,
        43,
        "graphite_light",
        vertices=16 if lod == 0 else 8 if lod == 1 else 6,
    )
    if lod == 2:
        return
    # Front work bay intentionally open under a glass screen.
    b.box("work_bay_floor", (-11, 48, 0.87), (100, 18, 0.6), "graphite_light")
    _quad(
        b,
        "work_bay_glass",
        [(-61, 57.08, 1.1), (39, 57.08, 1.1), (39, 57.08, 18.2), (-61, 57.08, 18.2)],
    )
    for x in (-49, -25, -1, 23):
        b.box("internal_work_cell", (x, 47, 5.6), (13, 11, 10), "graphite_light")
        b.beam(
            "work_bay_column", (x, 57.2, 0.8), (x, 57.2, 18.3), 0.30, "graphite_light"
        )
    b.box("office_roof_cap", (9, 77, 12.7), (74, 23, 0.5), "graphite")
    b.beam(
        "office_canopy_edge", (-27.5, 88.55, 12.96), (45.5, 88.55, 12.96), 0.17, "edge"
    )
    b.box("office_glazing", (9, 88.08, 7.7), (66, 0.06, 5.5), "glass")
    b.box("utility_vent_cap", (-52, -72, 43.8), (5.3, 5.3, 0.65), "graphite")
    if lod == 0:
        for x in (-49, -25, -1, 23):
            b.box("cell_control_cabinet", (x + 5, 54, 3.5), (2.6, 1.3, 5.5), "graphite")
            b.cylinder(
                "cell_service_motor",
                (x - 4, 46, 11.3),
                1.9,
                1.2,
                "graphite",
                vertices=16,
            )
            b.beam(
                "overhead_service_beam",
                (x, 39, 15.2),
                (x, 55, 15.2),
                0.4,
                "graphite_light",
            )
        for z in (7, 13, 19, 25, 31, 37):
            b.ring("vent_joint", (-52, -72, z), 2.15, 0.10, "graphite", segments=12)
        for y in range(-73, 33, 10):
            b.beam(
                "wall_panel_joint",
                (-61.55, y, 0.8),
                (-61.55, y, 18.3),
                0.09,
                "graphite_light",
            )
            b.box("side_window", (-61.6, y, 13.4), (0.07, 7.5, 3.4), "glass")
        for y in (-28, -10, 8):
            b.box("utility_roof_pack", (53, y, 12.4), (10, 9, 1.9), "graphite")
            _fan(b, "utility_roof_fan", 53, y, 13.6, 2.5, lod)
        b.polyline(
            "service_pipe",
            [(43, -40, 6), (43, 26, 6), (34, 26, 6), (34, 40, 6)],
            0.30,
            "graphite_light",
            sides=8,
        )
        for x in range(-23, 44, 8):
            b.beam(
                "office_window_mullion",
                (x, 88.14, 4.9),
                (x, 88.14, 10.5),
                0.13,
                "white",
            )
        for x in (-48, -29):
            b.box("loading_apron", (x, 74, 0.53), (13, 22, 0.08), "graphite_light")
            b.box("loading_canopy", (x, 62, 7.8), (14, 10, 0.50), "graphite")


def build(asset_id, lod):
    """Return batched mesh data. Blender scene creation belongs to the exporter."""
    if asset_id not in ASSET_IDS:
        raise ValueError(f"Unsupported district asset: {asset_id}")
    if lod not in (0, 1, 2):
        raise ValueError("lod must be 0, 1, or 2")
    from asset_builder import Builder

    b = Builder(asset_id, lod)
    if asset_id == "warehouse_logistics_center" or asset_id == "ev_charging_station":
        from district.logistics import ev_station, warehouse

        (warehouse if asset_id == "warehouse_logistics_center" else ev_station)(b, lod)
    else:
        {
            "data_center_campus": _data_center,
            "residential_neighborhood": _residential,
            "commercial_buildings": _commercial,
            "factory_industrial_facility": _factory,
        }[asset_id](b, lod)
    b.metadata.update(
        {
            "author": "Flux procedural asset production",
            "license": "CC0-1.0",
            "source_of_shape": "Original procedural geometry; generic architectural massing, no third-party meshes.",
            "geometry_scope": "Archetype only: no identity, location, owner, capacity, measured value, or operational status.",
        }
    )
    return b

"""Generic distribution and charging geometry; supplied Builder owns all state.

Author coordinates are metres, Z up and +Y forward. Facility identity, charger
ratings, utilisation and electrical topology are intentionally absent.
"""

import math


def _chamfered_case(
    b, name, center, size, material="graphite", chamfer=0.12, open_front=False
):
    """Eight-sided cabinet section: the chamfers have actual silhouette geometry."""
    x, y, z = (v / 2 for v in size)
    cx, cy, cz = center
    c = min(chamfer, x * 0.3, y * 0.3)
    section = [
        (-x + c, -y),
        (x - c, -y),
        (x, -y + c),
        (x, y - c),
        (x - c, y),
        (-x + c, y),
        (-x, y - c),
        (-x, -y + c),
    ]
    verts = [(cx + a, cy + d, cz + h) for h in (-z, z) for a, d in section]
    faces = [tuple(reversed(range(8))), tuple(range(8, 16))]
    faces.extend(
        (i, (i + 1) % 8, (i + 1) % 8 + 8, i + 8)
        for i in range(8)
        if not (open_front and i == 4)
    )
    b.mesh(name, verts, faces, material)


def _warehouse_dock(b, y, detailed):
    """Recess, segmented door, seal and leveller on the warehouse's long side."""
    b.box("dock_recess", (28.22, y, 4.35), (0.28, 7.2, 7.0), "graphite")
    b.box("dock_door", (28.42, y, 4.30), (0.19, 5.5, 5.8), "graphite_light")
    if not detailed:
        b.box("dock_canopy", (30.4, y, 8.25), (5.0, 8.0, 0.4), "graphite")
        return
    for offset in (-3.15, 3.15):
        b.box("dock_seal", (28.7, y + offset, 4.3), (0.8, 0.52, 6.5), "graphite")
        b.box(
            "dock_bumper", (29.2, y + offset * 0.74, 1.5), (0.42, 0.42, 1.3), "graphite"
        )
    b.box("dock_lintel", (28.72, y, 7.7), (0.85, 6.8, 0.55), "graphite")
    b.box("dock_leveller", (30.0, y, 0.99), (3.8, 5.5, 0.34), "graphite_light")
    b.box("dock_canopy", (30.9, y, 8.35), (6.2, 8.0, 0.42), "graphite")
    b.box("dock_canopy_edge", (34.02, y, 8.40), (0.12, 7.7, 0.13), "white")
    for z in (1.7, 2.2, 2.7, 3.2, 3.7, 4.2, 4.7, 5.2, 5.7, 6.2, 6.7):
        b.box("rollup_joint", (28.54, y, z), (0.065, 5.3, 0.065), "graphite")
    for dy in (-2.7, 2.7):
        b.beam(
            "canopy_brace",
            (28.7, y + dy, 6.9),
            (33.2, y + dy, 8.1),
            0.17,
            "graphite_light",
        )
    for dy in (-3.8, 3.8):
        b.cylinder(
            "dock_guard", (31.1, y + dy, 1.17), 0.19, 1.7, "graphite_light", vertices=10
        )
        b.cylinder("guard_cap", (31.1, y + dy, 1.98), 0.20, 0.14, "white", vertices=10)


def warehouse(b, lod):
    """warehouse_logistics_center: 120 m X by 180 m Y footprint."""
    b.box("paved_apron", (0, 0, 0.16), (118, 178, 0.32), "graphite")
    b.box("hall_plinth", (-9, -5, 0.65), (74, 142, 0.66), "graphite_light")
    b.box("hall_core", (-9, -15, 8.49), (74, 122, 15.02), "graphite")
    b.box("hall_roof", (-9, -5, 16.1), (75, 143, 0.62), "graphite_light")
    b.connector("MV_FEED", 0, (-49, -66, 2.2))
    b.box("incoming_cabinet", (-49, -65, 1.7), (3.0, 3.2, 2.75), "graphite_light")
    b.box("neutral_cabinet_tag", (-49, -63.35, 2.25), (1.2, 0.10, 0.35), "status")

    if lod == 2:
        b.box("dispatch_front", (-9, 57, 7.6), (74, 22, 13.2), "graphite")
        b.box("dispatch_glazing", (-13, 68.04, 6.9), (55, 0.10, 7.0), "glass")
        b.box("office", (-21, 74, 4.2), (46, 12, 7.8), "graphite_light")
        b.box("office_glazing", (-21, 80.04, 4.8), (41, 0.10, 4.2), "glass")
        b.box("loading_canopy", (30.6, -9, 8.1), (5.1, 111, 0.5), "graphite")
        for y in (-48, -10, 28):
            b.box("dock_group", (28.1, y, 4.1), (0.2, 24, 5.7), "graphite_light")
        b.box("roof_edge", (28.55, -5, 16.25), (0.16, 142, 0.18), "edge")
        return b

    # The high dispatch end has real interior racks behind selected aqua panes.
    b.box("dispatch_rear", (-9, 46.4, 8.415), (74, 1.0, 14.87), "graphite")
    b.box("dispatch_left", (-45.7, 56.6, 8.415), (0.65, 20.8, 14.87), "graphite")
    b.box("dispatch_right", (27.7, 56.6, 8.415), (0.65, 20.8, 14.87), "graphite")
    b.box("dispatch_sill", (-9, 66.7, 2.0), (74, 0.6, 2.0), "graphite")
    b.box("dispatch_lintel", (-9, 66.7, 13.875), (74, 0.6, 3.95), "graphite")
    b.box("dispatch_pane", (-9, 66.78, 7.45), (72, 0.16, 8.9), "glass")
    for x in (-44, -26, -8, 10, 27):
        b.box("dispatch_mullion", (x, 66.9, 7.5), (0.20, 0.33, 9.0), "graphite_light")
    b.box("dispatch_edge", (-9, 67, 12), (72, 0.17, 0.12), "edge")
    b.box("office", (-21, 74, 4.2), (46, 12, 7.8), "graphite")
    b.box("office_pane", (-21, 80.06, 4.8), (42, 0.12, 4.2), "glass")
    b.box("entry_canopy", (-21, 82.2, 7.8), (48, 5.5, 0.3), "graphite_light")
    b.box("entry_edge", (-21, 84.98, 7.8), (47.7, 0.12, 0.13), "edge")

    if lod == 1:
        for y in (-54, -23, 8, 39):
            _warehouse_dock(b, y, False)
        for x in (-30, -8, 14):
            b.box("racked_goods", (x, 58, 6.19), (8.0, 6.0, 10.42), "graphite_light")
        for y in (-53, -18, 17, 52):
            b.box("roof_rib", (-9, y, 16.55), (73, 0.38, 0.35), "graphite")
        for y in (-40, 20):
            b.box("roof_vent", (-25, y, 17.2), (9, 10, 1.5), "graphite")
        return b

    for y in (-59, -44, -29, -14, 1, 16, 31, 46):
        _warehouse_dock(b, y, True)
    for y in range(-70, 67, 7):
        b.box("standing_seam_roof", (-9, y, 16.5), (74, 0.18, 0.23), "graphite")
    for y in range(-70, 45, 10):
        for x in (-46.01, 28.01):
            b.box("wall_panel_joint", (x, y, 10.6), (0.08, 0.1, 9.6), "graphite_light")
    for y in (-42, -8, 26):
        b.box("vent_curb", (-25, y, 16.8), (9, 11, 0.85), "graphite")
        b.box("vent_housing", (-25, y, 18), (8.0, 10, 1.55), "graphite_light")
        for dy in (-2.7, 2.7):
            b.cylinder(
                "extractor_shroud",
                (-25, y + dy, 19.0),
                1.75,
                0.55,
                "graphite",
                vertices=20,
            )
            for angle in range(0, 180, 30):
                a = math.radians(angle)
                dx, dz = 1.52 * math.cos(a), 1.52 * math.sin(a)
                b.beam(
                    "extractor_grille",
                    (-25 - dx, y + dy - dz, 19.30),
                    (-25 + dx, y + dy + dz, 19.30),
                    0.07,
                    "graphite_light",
                )
    for x in (-33, -13, 7, 21):
        for dx in (-3.2, 3.2):
            for y in (54, 61):
                b.box(
                    "rack_upright",
                    (x + dx, y, 6.29),
                    (0.25, 0.25, 10.62),
                    "graphite_light",
                )
        for z in (2.0, 5.4, 8.8):
            b.box("rack_shelf", (x, 57.5, z), (6.7, 7.3, 0.23), "white")
            b.box(
                "generic_goods", (x, 57.5, z + 1.25), (5.7, 5.7, 2.2), "graphite_light"
            )
    for x in (-40, -31, -22, -13, -4):
        b.box("office_mullion", (x, 80.15, 4.8), (0.12, 0.20, 4.2), "graphite_light")
    for y in (-62, -20, 23, 63):
        b.box("apron_joint", (44, y, 0.335), (24, 0.12, 0.03), "graphite_light")
    b.box("long_roof_edge", (28.55, -5, 16.25), (0.13, 142, 0.16), "edge")
    b.box("service_conduit", (-47.0, -65, 1.25), (1.1, 0.18, 0.18), "white")
    return b


def _charger(b, x, y, lod):
    """Slim dispenser with a hanging hose; the unmarked pane is a service cover."""
    if lod == 2:
        b.box("charger", (x, y, 1.42), (0.72, 0.7, 2.2), "graphite_light")
        return
    b.box("charger_base", (x, y, 0.45), (0.98, 0.95, 0.26), "graphite_light")
    if lod == 1:
        b.box("charger_body", (x, y, 1.5), (0.68, 0.66, 2.1), "graphite_light")
        b.box("charger_cover", (x, y + 0.34, 1.72), (0.5, 0.05, 0.95), "glass")
        b.polyline(
            "hanging_cable",
            [
                (x + 0.35, y, 2.20),
                (x + 0.95, y, 1.3),
                (x + 0.8, y, 0.64),
                (x + 0.41, y, 1.65),
            ],
            0.065,
            "graphite",
            sides=4,
        )
        return
    _chamfered_case(
        b, "charger_housing", (x, y, 1.52), (0.75, 0.70, 2.12), open_front=True
    )
    # The shallow opening contains visible power modules, fins and a conduit.
    b.box("charger_lower_panel", (x, y + 0.35, 0.73), (0.52, 0.025, 0.56), "graphite")
    b.box("charger_header", (x, y + 0.35, 2.46), (0.52, 0.025, 0.26), "graphite")
    b.box("charger_service_cover", (x, y + 0.36, 1.67), (0.52, 0.045, 1.32), "glass")
    for z in (1.16, 1.58, 2.0):
        b.box("power_module", (x, y + 0.28, z), (0.4, 0.10, 0.26), "graphite_light")
        b.box("module_fin", (x, y + 0.316, z), (0.34, 0.035, 0.07), "white")
    b.box("charger_top", (x, y, 2.61), (0.72, 0.68, 0.13), "graphite_light")
    b.box("charger_edge", (x - 0.28, y + 0.387, 1.66), (0.035, 0.03, 1.26), "edge")
    for z in (0.73, 0.84, 0.95, 1.06, 1.17, 1.28):
        b.box("side_vent", (x - 0.383, y, z), (0.025, 0.39, 0.045), "graphite_light")
    points = [
        (
            x + 0.40 + 0.61 * math.sin(t * math.pi),
            y - 0.08,
            2.23 - 1.62 * math.sin(t * math.pi / 1.28),
        )
        for t in (i / 14 for i in range(15))
    ]
    points[-1] = (x + 0.40, y - 0.08, 1.68)
    b.polyline("hanging_cable", points, 0.058, "graphite", sides=8)
    b.beam(
        "holstered_plug",
        (x + 0.4, y - 0.08, 1.60),
        (x + 0.46, y - 0.08, 1.85),
        0.16,
        "graphite_light",
    )
    b.polyline(
        "internal_conduit",
        [
            (x - 0.18, y + 0.25, 0.7),
            (x - 0.18, y + 0.25, 2.27),
            (x + 0.17, y + 0.25, 2.27),
        ],
        0.03,
        "white",
        sides=6,
    )


def ev_station(b, lod):
    """ev_charging_station: 25 m X by 40 m Y footprint."""
    b.box("forecourt", (0, 0, 0.12), (24.6, 39.6, 0.24), "graphite")
    b.box("charging_island", (0, 0, 0.29), (6.7, 31.4, 0.1), "graphite_light")
    for y in (-9.6, 9.6):
        b.box("canopy_mast", (0, y, 2.48), (0.45, 0.6, 4.28), "graphite_light")
    b.connector("MV_FEED", 0, (0, -17.8, 1.1))
    b.box("feeder_cabinet", (0, -17.3, 1.02), (1.45, 1.0, 1.56), "graphite_light")
    b.box("neutral_cabinet_tag", (0, -16.77, 1.25), (0.56, 0.045, 0.18), "status")
    for x in (-2.2, 2.2):
        for y in (-10, 0, 10):
            _charger(b, x, y, lod)
    if lod == 2:
        b.box("canopy", (0, 0, 4.65), (21.2, 27.4, 0.28), "graphite_light")
        b.box("canopy_front_edge", (0, 13.73, 4.64), (21.2, 0.10, 0.10), "edge")
        return b

    b.box("canopy_spine", (0, 0, 4.65), (2.3, 27.4, 0.36), "graphite")
    for x in (-9.45, 9.45):
        b.box("canopy_wing", (x, 0, 4.68), (2.3, 27.4, 0.24), "graphite")
    for x in (-4.72, 4.72):
        b.box("frosted_canopy", (x, 0, 4.69), (7.10, 27.4, 0.10), "glass")
    for y in (-13.7, 13.7):
        b.box("canopy_fascia", (0, y, 4.64), (21.2, 0.18, 0.32), "graphite_light")
        b.box("canopy_edge", (0, y + 0.105, 4.69), (21.1, 0.05, 0.06), "edge")
    for y in (-9.6, 9.6):
        b.box("canopy_crossbeam", (0, y, 4.34), (20.8, 0.28, 0.40), "graphite_light")
    if lod == 1:
        return b

    for y in (-9.6, 9.6):
        for x in (-7.8, 7.8):
            b.beam(
                "cantilever_strut", (0, y, 3.25), (x, y, 4.15), 0.19, "graphite_light"
            )
            b.box("underside_light", (x * 0.62, y, 4.12), (5.0, 0.12, 0.055), "white")
    for y in (-12.6, -8.4, -4.2, 0, 4.2, 8.4, 12.6):
        b.box("canopy_purlin", (0, y, 4.585), (20.8, 0.10, 0.12), "graphite_light")
    for x in (-7.25, 7.25):
        for y in (-14.4, -5.0, 5.0, 14.4):
            b.box("stall_divider", (x, y, 0.254), (8.1, 0.075, 0.022), "white")
        for y in (-10, 0, 10):
            b.box(
                "wheel_stop", (x, y - 3.2, 0.33), (1.35, 0.20, 0.16), "graphite_light"
            )
    for x in (-3.0, 3.0):
        for y in (-14.0, 14.0):
            b.cylinder(
                "protective_bollard",
                (x, y, 0.79),
                0.095,
                0.9,
                "graphite_light",
                vertices=12,
            )
            b.cylinder(
                "bollard_reflector", (x, y, 1.16), 0.10, 0.07, "white", vertices=12
            )
    b.polyline(
        "feeder_conduit",
        [(0, -16.8, 0.46), (0, -15.5, 0.46), (0, -15.5, 0.35)],
        0.045,
        "graphite_light",
        sides=6,
    )
    return b

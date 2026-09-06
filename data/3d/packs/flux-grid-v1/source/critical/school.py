"""Original, identity-free school and apparatus-bay architectural archetype.

Geometry is authored in metres, Z-up, with the main approach toward +Y.
The shared pipeline owns scene creation, glTF axis conversion, and rendering.
"""

from asset_builder import Builder


def _gable(b, name, x, y, width, length, eave, ridge):
    """Closed triangular prism, with its ridge parallel to the Y axis."""
    left, right = x - width / 2, x + width / 2
    rear, front = y - length / 2, y + length / 2
    b.mesh(
        name,
        [
            (left, rear, eave),
            (right, rear, eave),
            (x, rear, ridge),
            (left, front, eave),
            (right, front, eave),
            (x, front, ridge),
        ],
        [(0, 1, 2), (5, 4, 3), (3, 4, 1, 0), (4, 5, 2, 1), (5, 3, 0, 2)],
        "graphite",
    )


def _facade_box(b, name, axis, wall, along, z, width, depth, height, material):
    if axis == "x":
        b.box(name, (wall, along, z), (depth, width, height), material)
    else:
        b.box(name, (along, wall, z), (width, depth, height), material)


def _window(b, name, axis, wall, along, z, width, height, outward):
    """A recessed panel, opaque reveals, sill, and one vertical mullion."""
    p = wall + outward * 0.07
    _facade_box(
        b,
        name + "_reveal",
        axis,
        p,
        along,
        z,
        width + 0.22,
        0.18,
        height + 0.22,
        "graphite",
    )
    p += outward * 0.105
    _facade_box(b, name + "_glass", axis, p, along, z, width, 0.055, height, "glass")
    p += outward * 0.035
    for dx in (-width / 2, width / 2):
        _facade_box(
            b,
            name + "_jamb",
            axis,
            p,
            along + dx,
            z,
            0.11,
            0.16,
            height + 0.18,
            "graphite_light",
        )
    for dz in (-height / 2, height / 2):
        _facade_box(
            b,
            name + "_rail",
            axis,
            p,
            along,
            z + dz,
            width,
            0.17,
            0.1,
            "graphite_light",
        )
    _facade_box(
        b, name + "_mullion", axis, p, along, z, 0.085, 0.13, height, "graphite_light"
    )
    _facade_box(
        b,
        name + "_sill",
        axis,
        p + outward * 0.1,
        along,
        z - height / 2 - 0.14,
        width + 0.35,
        0.35,
        0.13,
        "white",
    )


def _ribbon(b, name, axis, wall, along, z, width, height):
    _facade_box(b, name + "_glass", axis, wall, along, z, width, 0.11, height, "glass")
    _facade_box(
        b,
        name + "_sill",
        axis,
        wall,
        along,
        z - height / 2,
        width + 0.2,
        0.22,
        0.12,
        "white",
    )


def _flat_wing(b, name, center, size, height, lod):
    x, y = center
    width, length = size
    b.box(
        name + "_body",
        (x, y, 0.4 + height / 2),
        (width, length, height),
        "graphite_light",
    )
    b.box(
        name + "_roof",
        (x, y, height + 0.55),
        (width + 0.65, length + 0.65, 0.3),
        "graphite",
    )
    if lod == 2:
        return
    for side in (-1, 1):
        b.box(
            name + "_parapet_x",
            (x + side * width / 2, y, height + 0.83),
            (0.22, length + 0.3, 0.34),
            "graphite_light",
        )
        b.box(
            name + "_parapet_y",
            (x, y + side * length / 2, height + 0.83),
            (width, 0.22, 0.34),
            "graphite_light",
        )
    # A narrow continuous floor joint makes the two-storey classroom wing legible.
    for side in (-1, 1):
        b.box(
            name + "_floor_joint",
            (x + side * (width / 2 + 0.06), y, 4.13),
            (0.14, length, 0.16),
            "graphite",
        )


def _ventilator(b, name, x, y, roof_z, lod):
    b.box(name + "_curb", (x, y, roof_z + 0.14), (2.7, 3.3, 0.28), "graphite")
    b.box(name + "_body", (x, y, roof_z + 0.8), (2.3, 2.9, 1.15), "graphite_light")
    b.box(name + "_cap", (x, y, roof_z + 1.44), (2.7, 3.3, 0.18), "graphite")
    if lod == 0:
        for side in (-1, 1):
            for row in range(5):
                b.box(
                    name + "_louver",
                    (x + side * 1.19, y, roof_z + 0.45 + row * 0.2),
                    (0.12, 2.6, 0.08),
                    "graphite",
                )


def _bay(b, x, lod):
    # Tall sectional openings distinguish the apparatus wing from classrooms.
    b.box("bay_dark_recess", (x, 33.095, 4.12), (6.5, 0.21, 7.1), "graphite")
    b.box("bay_sectional_door", (x, 33.235, 3.37), (6.05, 0.1, 5.6), "graphite_light")
    b.box("bay_upper_glazing", (x, 33.31, 6.25), (5.9, 0.055, 1.55), "glass")
    if lod == 2:
        return
    for dx in (-3.34, 3.34):
        b.box("bay_jamb", (x + dx, 33.28, 4.18), (0.23, 0.42, 7.35), "white")
    b.box("bay_lintel", (x, 33.28, 7.84), (6.9, 0.42, 0.24), "white")
    b.box("bay_threshold", (x, 33.7, 0.52), (6.6, 1.1, 0.16), "graphite_light")
    if lod == 0:
        for z in (1.05, 1.7, 2.35, 3.0, 3.65, 4.3, 4.95, 5.47):
            b.box("bay_door_joint", (x, 33.315, z), (5.96, 0.055, 0.07), "graphite")
        for dx in (-1.97, 0, 1.97):
            b.box(
                "bay_glazing_mullion",
                (x + dx, 33.36, 6.25),
                (0.1, 0.1, 1.6),
                "graphite",
            )
        b.box("bay_glazing_rail", (x, 33.36, 6.25), (6.0, 0.1, 0.07), "graphite")
        b.box("bay_pull", (x, 33.42, 1.75), (0.8, 0.16, 0.12), "white")


def build(asset_id, lod) -> Builder:
    """Return batched geometry; this function never creates Blender objects."""
    if asset_id != "school_emergency_services":
        raise ValueError("school.py builds only school_emergency_services")
    if lod not in (0, 1, 2):
        raise ValueError("lod must be 0, 1, or 2")
    b = Builder(asset_id, lod)

    # The 68 x 96 slab centres the nominal 70 x 100 footprint at the origin.
    b.box("campus_ground", (0, 0, 0.2), (68, 96, 0.4), "graphite")
    b.box("school_walk", (-8, 27.0, 0.365), (19, 28, 0.09), "graphite_light")
    b.box("apparatus_apron", (25, 39.7, 0.37), (17.4, 12.8, 0.1), "graphite_light")

    # U-shaped academic block, with an offset apparatus wing facing the approach.
    b.box("assembly_hall", (-7, -26, 5.5), (48, 28, 10.2), "graphite_light")
    _gable(b, "assembly_gable_roof", -7, -26, 49.2, 29.2, 10.6, 15.15)
    _flat_wing(b, "west_classrooms", (-24, 7), (14, 38), 7.6, lod)
    _flat_wing(b, "east_classrooms", (8, 2), (18, 28), 7.6, lod)
    _flat_wing(b, "apparatus_wing", (25, 20), (16, 26), 9.0, lod)

    # Entry is a shallow, graphite-framed glazed volume within the court.
    b.box("entry_core", (-8, -3.0, 3.48), (17, 15, 6.16), "graphite")
    b.box("entry_front_glass", (-8, 4.57, 3.65), (15.7, 0.12, 5.65), "glass")
    b.box("entry_canopy", (-8, 7.6, 5.85), (19.2, 7.0, 0.3), "graphite")
    b.box("entry_canopy_fascia", (-8, 11.12, 5.89), (19.25, 0.12, 0.17), "white")
    # Neutral status is a physical strip on the entry fascia, never a baked label.
    b.box("neutral_status_fascia", (-8, 11.205, 5.87), (5.2, 0.075, 0.32), "status")
    for x in (-16.7, 0.7):
        b.box("entry_canopy_column", (x, 9.3, 3.15), (0.3, 0.3, 5.5), "graphite_light")
    for x in (21.0, 29.0):
        _bay(b, x, lod)

    # A compact neutral feed pedestal carries the sole geometric attachment node.
    b.box("feed_pedestal", (31.4, -36.4, 1.16), (2.0, 1.5, 1.68), "graphite_light")
    b.connector("MV_FEED", 0, (31.4, -37.15, 1.48))

    if lod == 2:
        b.box("west_window_mass", (-31.08, 7, 4.45), (0.12, 31.4, 3.9), "glass")
        b.box("east_window_mass", (-1.08, 2, 4.45), (0.12, 21.4, 3.9), "glass")
        return b

    # Physical roof seams and eave lines: restrained highlights on architecture.
    for x in (-31.6, 17.6):
        b.box("hall_eave", (x, -26, 10.71), (0.17, 29.3, 0.17), "white")
    b.box("hall_ridge_cap", (-7, -26, 15.16), (0.22, 29.5, 0.16), "graphite_light")
    b.box("hall_ridge_inlay", (-7, -26, 15.252), (0.07, 24.0, 0.03), "edge")
    for y in (-40.55, -11.45):
        b.beam("hall_raking_fascia", (-31.6, y, 10.75), (-7, y, 15.2), 0.16, "white")
        b.beam("hall_raking_fascia", (-7, y, 15.2), (17.6, y, 10.75), 0.16, "white")

    # Classroom glazing is individual framed windows close up, ribbons at map LOD.
    for side, wall in ((-1, -31), (1, -17)):
        for z in (2.4, 5.7):
            if lod == 0:
                for index, y in enumerate((-8, -2, 4, 10, 16, 22)):
                    _window(
                        b, f"west_classroom_{index}", "x", wall, y, z, 3.95, 1.8, side
                    )
            else:
                _ribbon(
                    b, "west_classroom_band", "x", wall + side * 0.12, 7, z, 33.2, 1.8
                )
    for side, wall in ((-1, -1), (1, 17)):
        for z in (2.4, 5.7):
            if lod == 0:
                for index, y in enumerate((-8, -2, 4, 10)):
                    _window(
                        b, f"east_classroom_{index}", "x", wall, y, z, 3.95, 1.8, side
                    )
            else:
                _ribbon(
                    b, "east_classroom_band", "x", wall + side * 0.12, 1, z, 21.2, 1.8
                )

    # Front end walls give both classroom wings their own two-storey expression.
    for x, y, span in ((-24, 26, 10.8), (8, 16, 14.8)):
        for z in (2.4, 5.7):
            _ribbon(b, "classroom_front_glass", "y", y + 0.12, x, z, span, 1.8)

    for side, wall in ((-1, -40), (1, -12)):
        if lod == 0:
            for x in (-27, -20.4, -13.8, -7.2, -0.6, 6, 12.6):
                _window(b, "hall_clerestory", "y", wall, x, 8.6, 4.2, 2.4, side)
        else:
            _ribbon(b, "hall_clerestory", "y", wall + side * 0.12, -7, 8.6, 42.0, 2.4)
    for side, wall in ((-1, -31), (1, 17)):
        if lod == 0:
            for y in (-36, -30, -24, -18):
                _window(b, "hall_side_clerestory", "x", wall, y, 8.6, 3.8, 2.4, side)
        else:
            _ribbon(
                b, "hall_side_clerestory", "x", wall + side * 0.12, -27, 8.6, 23, 2.4
            )

    for x in (-15.8, -11.9, -8, -4.1, -0.2):
        b.box(
            "entry_curtain_mullion", (x, 4.7, 3.6), (0.13, 0.17, 5.8), "graphite_light"
        )
    for z in (0.83, 3.9, 6.5):
        b.box(
            "entry_curtain_transom", (-8, 4.7, z), (15.8, 0.17, 0.12), "graphite_light"
        )
    b.box("entry_door_frame", (-8, 4.84, 2.0), (4.3, 0.18, 3.2), "graphite_light")
    b.box("entry_door_glass", (-8, 4.95, 2.0), (3.95, 0.07, 2.85), "glass")
    b.box("entry_door_mullion", (-8, 5.03, 2.0), (0.12, 0.09, 2.9), "graphite")
    b.box("entry_roof", (-8, -3.0, 6.68), (17.7, 15.7, 0.22), "graphite_light")

    # Pale glass sits behind an exposed structural frame on the apparatus flank.
    _ribbon(b, "apparatus_side_glazing", "x", 33.12, 19.6, 6.9, 20.7, 1.4)
    b.box("apparatus_front_roof_edge", (25, 33.37, 9.68), (16.5, 0.12, 0.12), "edge")
    for x, y in ((-24, -1), (-24, 17), (8, -3), (8, 9)):
        _ventilator(b, "classroom_roof_vent", x, y, 8.3, lod)
    _ventilator(b, "apparatus_roof_vent", 25, 16, 9.7, lod)

    if lod == 0:
        for y in (-39, -37, -35, -33, -31, -29, -27, -25, -23, -21, -19, -17, -15, -13):
            b.beam(
                "standing_seam_left",
                (-31.4, y, 10.77),
                (-7, y, 15.22),
                0.07,
                "graphite_light",
            )
            b.beam(
                "standing_seam_right",
                (-7, y, 15.22),
                (17.4, y, 10.77),
                0.07,
                "graphite_light",
            )
        # Small gable vents and their louvers add close-range scale without symbols.
        for y in (-40.64, -11.36):
            b.box(
                "gable_vent_recess", (-7, y, 12.3), (3.6, 0.12, 1.25), "graphite_light"
            )
            for z in (11.88, 12.08, 12.28, 12.48, 12.68):
                b.box("gable_vent_louver", (-7, y, z), (3.3, 0.17, 0.07), "graphite")
        # Structural bays and drainage remain dark; cyan is limited to roof inlays.
        for wall in (-31.3, -16.7):
            for y in (-11, -5, 1, 7, 13, 19, 25):
                b.box("west_wall_pier", (wall, y, 4.15), (0.28, 0.3, 7.45), "graphite")
        for wall in (-1.3, 17.3):
            for y in (-11, -5, 1, 7, 13):
                b.box("east_wall_pier", (wall, y, 4.15), (0.28, 0.3, 7.45), "graphite")
        for x, y, z in (
            (-31.35, 25.6, 7.9),
            (-16.65, -11.5, 7.9),
            (-1.35, 15.5, 7.9),
            (17.3, -11.5, 7.9),
            (33.35, 7.4, 9.3),
        ):
            b.cylinder(
                "roof_downpipe", (x, y, 0.5 + z / 2), 0.09, z, "graphite", vertices=10
            )
        # Court paving joints, benches, and low planter kerbs are real scene objects.
        for y in (14, 20, 26, 32, 38):
            b.box("walk_paving_joint", (-8, y, 0.423), (18.8, 0.065, 0.018), "graphite")
        for x in (-14.8, -1.2):
            for y in (20, 30):
                b.box(
                    "court_bench_seat",
                    (x, y, 0.92),
                    (0.75, 3.3, 0.18),
                    "graphite_light",
                )
                for dy in (-1.1, 1.1):
                    b.box(
                        "court_bench_leg",
                        (x, y + dy, 0.635),
                        (0.45, 0.18, 0.45),
                        "graphite",
                    )
        for x in (-22, 4.5):
            b.box("low_planter", (x, 37, 0.64), (6.2, 5.0, 0.56), "graphite_light")
            b.box("planter_inset", (x, 37, 0.94), (5.65, 4.45, 0.08), "graphite")
        for x in (17.5, 24.8, 32.5):
            b.cylinder(
                "apron_bollard",
                (x, 35.1, 0.97),
                0.15,
                1.15,
                "graphite_light",
                vertices=12,
            )
            b.cylinder(
                "bollard_cap", (x, 35.1, 1.565), 0.16, 0.06, "white", vertices=12
            )
        for x in (-8.48, -7.52):
            b.box("entry_door_pull", (x, 5.11, 1.97), (0.08, 0.17, 0.7), "white")
        b.box("pedestal_panel", (31.4, -37.2, 1.22), (1.5, 0.075, 1.17), "graphite")
    return b

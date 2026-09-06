"""Original Flux generation archetypes; import has no scene side effects.

Build coordinates: metres, Z up, +Y forward, ground-centred footprint.
The shared pipeline owns materials, transform baking, glTF axes, and export.
No plant identities, capacities, retirement state, or geographic positions are
baked into these models. Geometry is schematic and is not a vendor design.
"""

from math import cos, pi, sin

ASSETS = {
    "nuclear_smr_module": {
        "footprint_m": {"width": 100, "length": 120},
        "connector": (0, 56, 8),
        "source_of_shape": "Original procedural compact PWR-inspired plant: broad domed containment, connected turbine/generator hall, control/service annex, and a user-requested flared hyperboloid cooling tower adapted from this pack's originally authored coal-plant tower geometry. Architectural context from EDF Sizewell B and Rolls-Royce SMR public descriptions; no third-party mesh, vendor replica, capacity, or claim that every SMR has this dome or cooling system.",
    },
    "coal_plant_retiring_site": {
        "footprint_m": {"width": 180, "length": 260},
        "connector": (61, 108, 12),
        "source_of_shape": "Original procedural boiler house, turbine hall, chimneys, cooling tower, and fuel handling; retirement state is not encoded.",
    },
    "natural_gas_plant": {
        "footprint_m": {"width": 140, "length": 200},
        "connector": (48, 88, 10),
        "source_of_shape": "Original procedural combined-cycle silhouette with turbine enclosures, heat-recovery trains, exhausts, and cooling cells; no plant capacity is encoded.",
    },
}


def _lod(value):
    value = int(str(value).lower().replace("lod", ""))
    if value not in (0, 1, 2):
        raise ValueError("LOD must be 0, 1 or 2")
    return value


def _mesh(b, name, vertices, faces, material="graphite"):
    return b.mesh(name, vertices, faces, material=material)


def _outline(b, name, center, size, level, material="edge", vertical=True):
    """Selective architectural contours, never whole-mesh wireframe."""
    x, y, z = center
    sx, sy, sz = (v / 2 for v in size)
    top = [
        (x - sx, y - sy, z + sz),
        (x + sx, y - sy, z + sz),
        (x + sx, y + sy, z + sz),
        (x - sx, y + sy, z + sz),
    ]
    width = 0.10 if level == 0 else 0.13
    for i in range(4):
        b.beam(
            f"{name}_roof_edge_{i}", top[i], top[(i + 1) % 4], width, material=material
        )
    if vertical and level < 2:
        for i in range(4):
            b.beam(
                f"{name}_corner_{i}",
                (top[i][0], top[i][1], z - sz),
                top[i],
                width,
                material=material,
            )


def _revolve(
    b,
    name,
    center,
    profile,
    sectors,
    material="graphite",
    start=0,
    stop=2 * pi,
    cap=False,
):
    """A thin, visible lathed skin. Angles can isolate a glass shell sector."""
    full = abs(stop - start - 2 * pi) < 1e-6
    n = sectors if full else sectors + 1
    vertices = []
    for radius, height in profile:
        for j in range(n):
            a = start + (stop - start) * j / sectors
            vertices.append(
                (
                    center[0] + radius * cos(a),
                    center[1] + radius * sin(a),
                    center[2] + height,
                )
            )
    faces = []
    for i in range(len(profile) - 1):
        for j in range(sectors):
            jn = (j + 1) % n
            faces.append((i * n + j, i * n + jn, (i + 1) * n + jn, (i + 1) * n + j))
    if cap and full:
        faces.append(tuple(reversed(range(n))))
        faces.append(tuple((len(profile) - 1) * n + j for j in range(n)))
    return _mesh(b, name, vertices, faces, material)


def _profile_contour(b, name, center, profile, angle, radius=0.09, material="edge"):
    points = [
        (center[0] + r * cos(angle), center[1] + r * sin(angle), center[2] + z)
        for r, z in profile
    ]
    b.polyline(name, points, radius, material=material)


def _fan(b, name, center, radius, level):
    x, y, z = center
    sectors = (20, 10, 6)[level]
    b.cylinder(
        name + "_well", center, radius, 0.5, material="graphite", vertices=sectors
    )
    if level == 2:
        return
    b.ring(name + "_rim", (x, y, z + 0.28), radius, 0.08, material="white")
    b.cylinder(
        name + "_hub",
        (x, y, z + 0.4),
        radius * 0.17,
        0.26,
        material="graphite_light",
        vertices=sectors // 2,
    )
    for k in range(3):
        angle = k * 2 * pi / 3
        local = [(0.17, -0.12), (0.89, -0.22), (0.85, 0.07), (0.24, 0.16)]
        points = [
            (
                x + radius * (u * cos(angle) - v * sin(angle)),
                y + radius * (u * sin(angle) + v * cos(angle)),
                z + 0.4,
            )
            for u, v in local
        ]
        _mesh(b, f"{name}_blade_{k}", points, [(0, 1, 2, 3)], "graphite_light")
    if level == 0:
        for k in range(6):
            angle = k * pi / 3
            b.beam(
                f"{name}_guard_{k}",
                (x - radius * cos(angle), y - radius * sin(angle), z + 0.55),
                (x + radius * cos(angle), y + radius * sin(angle), z + 0.55),
                0.065,
                material="graphite_light",
            )


def _cooler_bank(b, name, center, cell_count, cell_size, level):
    x, y, z = center
    width, depth, height = cell_size
    total_width = width * cell_count
    if level == 2:
        b.box(
            name + "_mass",
            (x, y, z + height / 2),
            (total_width, depth, height),
            material="graphite_light",
        )
        return
    b.box(
        name + "_plenum",
        (x, y, z + height * 0.55),
        (total_width, depth, height * 0.65),
        material="graphite",
    )
    for i in range(cell_count):
        cx = x + width * (i - (cell_count - 1) / 2)
        for side in (-1, 1):
            b.beam(
                f"{name}_leg_{i}_{side}",
                (cx, y + side * (depth / 2 - 0.5), z),
                (cx, y + side * (depth / 2 - 0.5), z + height),
                0.35,
                material="graphite_light",
            )
        _fan(
            b,
            f"{name}_fan_{i}",
            (cx, y, z + height * 0.91),
            min(width, depth) * 0.38,
            level,
        )
        if level == 0:
            for j in range(5):
                zf = z + height * (0.33 + 0.105 * j)
                b.beam(
                    f"{name}_louvre_{i}_{j}",
                    (cx - width * 0.47, y + depth * 0.51, zf),
                    (cx + width * 0.47, y + depth * 0.51, zf),
                    0.15,
                    material="graphite_light",
                )
    _outline(
        b,
        name,
        (x, y, z + height / 2),
        (total_width, depth, height),
        level,
        vertical=False,
    )


def _hall(b, name, center, size, level, panes=True):
    x, y, z = center
    sx, sy, sz = size
    if level == 2:
        b.box(name + "_silhouette", center, size, material="graphite_light")
        return
    floor = z - sz / 2
    b.box(name + "_podium", (x, y, floor + 0.7), (sx, sy, 1.4), material="graphite")
    b.box(
        name + "_rear_wall",
        (x, y - sy / 2 + 0.35, z),
        (sx, 0.7, sz),
        material="graphite_light",
    )
    for sign in (-1, 1):
        b.box(
            name + f"_end_{sign}",
            (x + sign * (sx / 2 - 0.35), y, z),
            (0.7, sy, sz),
            material="graphite_light",
        )
    b.box(
        name + "_front_spandrel",
        (x, y + sy / 2 - 0.2, floor + sz * 0.19),
        (sx, 0.6, sz * 0.38),
        material="graphite_light",
    )
    b.box(
        name + "_roof_spine",
        (x, y - sy * 0.20, z + sz / 2 - 0.3),
        (sx, sy * 0.60, 0.6),
        material="graphite",
    )
    # Separate low-alpha panes expose physical machinery without requiring transmission.
    if panes:
        b.box(
            name + "_front_frosted_panes",
            (x, y + sy / 2, z + sz * 0.16),
            (sx - 0.8, 0.12, sz * 0.66),
            material="glass",
        )
        b.box(
            name + "_roof_frosted_panes",
            (x, y + sy * 0.30, z + sz / 2),
            (sx - 0.8, sy * 0.39, 0.10),
            material="glass",
        )
    bays = max(3, round(sx / 9)) if level == 0 else 3
    for i in range(bays + 1):
        cx = x - sx / 2 + sx * i / bays
        b.beam(
            f"{name}_column_{i}",
            (cx, y + sy / 2, floor),
            (cx, y + sy / 2, z + sz / 2),
            0.25,
            material="graphite_light",
        )
        if level == 0:
            b.beam(
                f"{name}_rafter_{i}",
                (cx, y - sy / 2, z + sz / 2),
                (cx, y + sy / 2, z + sz / 2),
                0.20,
                material="graphite_light",
            )
    _outline(b, name, center, size, level)


def _transformer(b, name, center, level, height=5):
    x, y, z = center
    b.box(
        name + "_tank",
        (x, y, z + height * 0.5),
        (6, 8, height),
        material="graphite_light",
    )
    b.box(
        name + "_status_band",
        (x, y + 4.06, z + height * 0.8),
        (5.6, 0.14, 0.35),
        material="status",
    )
    if level == 2:
        return
    for i in range(3):
        bx = x + (i - 1) * 1.8
        b.cylinder(
            f"{name}_bushing_{i}",
            (bx, y, z + height + 1.2),
            0.24,
            2.4,
            material="white",
            vertices=(12 if level == 0 else 6),
        )
        if level == 0:
            for k in range(5):
                b.ring(
                    f"{name}_shed_{i}_{k}",
                    (bx, y, z + height + 0.4 + k * 0.36),
                    0.4,
                    0.075,
                    material="graphite_light",
                )
    if level == 0:
        for side in (-1, 1):
            for j in range(9):
                b.box(
                    f"{name}_fin_{side}_{j}",
                    (x + side * 3.7, y - 3.3 + j * 0.82, z + height * 0.45),
                    (0.75, 0.14, height * 0.72),
                    material="graphite",
                )


def _site_base(b, asset_id, level):
    spec = ASSETS[asset_id]
    w, l = spec["footprint_m"]["width"], spec["footprint_m"]["length"]
    b.box("foundation", (0, 0, 0.3), (w * 0.97, l * 0.97, 0.6), material="graphite")
    if level < 2:
        # Only two thin approach strips, attached to the ground and architecturally plausible.
        for side in (-1, 1):
            b.beam(
                f"service_lane_{side}",
                (side * w * 0.40, -l * 0.43, 0.66),
                (side * w * 0.40, l * 0.43, 0.66),
                0.20,
                material="graphite_light",
            )


def _nuclear(b, level):
    _site_base(b, "nuclear_smr_module", level)
    b.metadata["source_of_shape"] = ASSETS["nuclear_smr_module"]["source_of_shape"]
    b.metadata["shape_reference_urls"] = [
        "https://www.edfenergy.com/energy/power-stations/sizewell-b",
        "https://www.edfenergy.com/media-centre/sizewell-b-turns-thirty",
        "https://www.rolls-royce-smr.com/about-the-rolls-royce-smr",
        "https://gda.rolls-royce-smr.com/assets/documents/documents/rr-smr-e3s-case-chapter-25---detailed-information-about-the-design-v2-public-issue-clean.pdf",
    ]
    b.metadata["shape_revision"] = (
        "broad-containment-cooling-tower-connected-power-block-v3"
    )

    # One stout containment building replaces the earlier silo-like pair.
    # A 40 m diameter hemisphere over a 12.5 m drum is the dominant silhouette.
    # This is a compact PWR-inspired archetype, not a particular SMR design.
    cx, cy = -21, -16
    center = (cx, cy, 0.6)
    radius, stem = 20, 12.5
    dome = [(radius, stem)]
    for i in range(1, (9, 5, 3)[level] + 1):
        a = pi * 0.5 * i / (9, 5, 3)[level]
        dome.append((max(0.06, radius * cos(a)), stem + radius * sin(a)))
    drum = [(radius, 0), (radius, stem)]
    if level == 0:
        _revolve(
            b,
            "containment_opaque_drum",
            center,
            drum,
            36,
            "graphite_light",
            start=pi * 0.5,
            stop=pi * 2,
        )
        _revolve(
            b,
            "containment_opaque_hemisphere",
            center,
            dome,
            36,
            "white",
            start=pi * 0.5,
            stop=pi * 2,
        )
        _revolve(
            b,
            "containment_frosted_quarter",
            center,
            drum + dome[1:],
            12,
            "glass",
            start=0,
            stop=pi * 0.5,
        )
        # A restrained see-through quadrant reveals a vessel and its surrounding
        # steam-generator equipment, tied into the physical power-block gallery.
        b.cylinder(
            "reactor_pressure_vessel",
            (cx, cy, 12.5),
            4.1,
            17.5,
            material="graphite",
            vertices=28,
        )
        b.ellipsoid(
            "reactor_vessel_head",
            (cx, cy, 21.25),
            (4.1, 4.1, 2.0),
            material="graphite_light",
        )
        for k, a in enumerate((0.12 * pi, 0.52 * pi, 0.94 * pi)):
            px = cx + 10 * cos(a)
            py = cy + 10 * sin(a)
            b.cylinder(
                f"steam_generator_{k}",
                (px, py, 13),
                2.25,
                17.0,
                material="graphite",
                vertices=20,
            )
            b.ellipsoid(
                f"steam_generator_head_{k}",
                (px, py, 21.5),
                (2.25, 2.25, 1.35),
                material="graphite_light",
            )
            b.polyline(
                f"primary_loop_{k}",
                [(cx, cy, 16.5), (px, py, 16.5), (px, py, 7.5), (cx, cy, 7.5)],
                0.48,
                material="white",
            )
        for k, a in enumerate((0, pi * 0.5, pi, pi * 1.5)):
            _profile_contour(b, f"containment_dome_joint_{k}", center, dome, a, 0.065)
        # Thick buttresses on the concrete drum identify a reinforced building.
        for k, a in enumerate((pi * 0.6, pi * 0.9, pi * 1.2, pi * 1.5, pi * 1.8)):
            b.box(
                f"containment_buttress_{k}",
                (cx + 20 * cos(a), cy + 20 * sin(a), 6.6),
                (1.3, 1.3, 12),
                material="graphite",
            )
    else:
        _revolve(
            b,
            "containment_drum",
            center,
            drum,
            (20, 10)[level - 1],
            "graphite_light",
            cap=True,
        )
        _revolve(
            b,
            "containment_hemisphere",
            center,
            dome,
            (20, 10)[level - 1],
            "white",
            cap=True,
        )
    b.cylinder(
        "containment_raft",
        (cx, cy, 1.2),
        20.8,
        1.2,
        material="graphite",
        vertices=(48, 20, 10)[level],
    )
    if level < 2:
        b.ring(
            "containment_drum_collar", (cx, cy, 2.1), 20.15, 0.16, material="graphite"
        )
        b.ring(
            "containment_dome_spring_line", (cx, cy, 13.1), 20, 0.11, material="edge"
        )

    # The adjoining buildings, not a decorative icon, make this read as a plant.
    _hall(b, "turbine_generator_hall", (11, 23, 9.6), (66, 32, 18), level)
    b.box(
        "turbine_hall_roof_monitor",
        (11, 18.5, 20.6),
        (54, 12, 4),
        material="graphite_light",
    )
    b.box(
        "reactor_service_gallery",
        (-1.5, 0, 6.6),
        (33, 14, 12),
        material="graphite_light",
    )
    b.box(
        "control_service_annex", (29, -2, 6.6), (28, 18, 12), material="graphite_light"
    )
    b.box(
        "containment_entrance_airlock",
        (-31, 3, 4.6),
        (8, 9, 8),
        material="graphite_light",
    )
    b.box("plant_status_band", (-31, 7.6, 2.0), (6, 0.13, 0.4), material="status")
    if level < 2:
        _outline(b, "turbine_roof_monitor", (11, 18.5, 20.6), (54, 12, 4), level)
        _outline(
            b, "service_gallery", (-1.5, 0, 6.6), (33, 14, 12), level, vertical=False
        )
        _outline(b, "control_annex", (29, -2, 6.6), (28, 18, 12), level)
        b.box(
            "monitor_clerestory", (11, 24.56, 20.6), (52, 0.12, 2.1), material="glass"
        )
        b.box(
            "control_room_window_band",
            (43.08, -2, 9.5),
            (0.12, 15, 2.3),
            material="glass",
        )
        b.box(
            "personnel_airlock_door",
            (-31, 7.58, 3.8),
            (3, 0.12, 5.5),
            material="graphite",
        )
        # Paired main-steam ducts cross a short gallery to the turbine island.
        for k, x in enumerate((-7, -3)):
            b.polyline(
                f"main_steam_gallery_{k}",
                [(x, -7, 19.5), (x, 1, 19.5), (x, 1, 15.5), (x, 11, 15.5)],
                0.7,
                material="graphite_light",
            )
        b.polyline(
            "feedwater_return",
            [(9, -7, 10), (9, 3, 10), (9, 3, 5.2), (9, 30, 5.2)],
            0.38,
            material="white",
        )
        if level == 0:
            # One long generator train is visible through the front clerestory.
            for k, (x, length, r) in enumerate(
                ((-10, 12, 2.8), (4, 13, 3.7), (18, 10, 3.0), (30, 10, 2.4))
            ):
                b.polyline(
                    f"turbine_generator_casing_{k}",
                    [(x - length / 2, 31, 7.4), (x + length / 2, 31, 7.4)],
                    r,
                    material="graphite_light",
                )
                b.box(
                    f"turbine_generator_mount_{k}",
                    (x, 31, 3),
                    (length - 2, 8, 4.8),
                    material="graphite",
                )
            for k, x in enumerate(range(-17, 41, 8)):
                b.beam(
                    f"turbine_crane_frame_{k}",
                    (x, 28, 2),
                    (x, 28, 16.8),
                    0.28,
                    material="graphite_light",
                )
                b.beam(
                    f"turbine_crane_top_{k}",
                    (x, 8, 16.8),
                    (x, 38, 16.8),
                    0.22,
                    material="graphite_light",
                )
            b.beam(
                "turbine_crane_runway",
                (-20, 28, 15.8),
                (42, 28, 15.8),
                0.50,
                material="white",
            )
            for x in (-10, 11, 32):
                b.box(
                    f"turbine_access_door_{x}",
                    (x, 39.07, 3.6),
                    (5, 0.12, 6),
                    material="graphite",
                )
            for x in (21, 29, 37):
                _fan(b, f"annex_roof_vent_{x}", (x, -2, 12.9), 2.1, level)
            # A physical, neutral industrial plaque above the personnel airlock.
            # The small trefoil supplements the containment form; it is not a
            # status colour or a label for a real facility.
            b.box(
                "nuclear_identity_plaque",
                (-31, 7.68, 7.2),
                (2.5, 0.16, 2.5),
                material="graphite",
            )
            for k in range(3):
                angle = pi / 2 + k * 2 * pi / 3
                verts = []
                for r in (0.37, 0.99):
                    verts.extend(
                        (
                            -31 + r * cos(angle - 0.43 + j * 0.86 / 8),
                            7.785,
                            7.2 + r * sin(angle - 0.43 + j * 0.86 / 8),
                        )
                        for j in range(9)
                    )
                _mesh(
                    b,
                    f"nuclear_plaque_lobe_{k}",
                    verts,
                    [(j, j + 1, j + 10, j + 9) for j in range(8)],
                    "white",
                )
            disk = [(-31, 7.786, 7.2)] + [
                (-31 + 0.20 * cos(k * pi / 8), 7.786, 7.2 + 0.20 * sin(k * pi / 8))
                for k in range(16)
            ]
            _mesh(
                b,
                "nuclear_plaque_center",
                disk,
                [(0, k + 1, (k + 1) % 16 + 1) for k in range(16)],
                "white",
            )

    # Explicit user-requested cooling stack: the familiar flared concrete shell
    # remains distinct from the broad containment dome at every detail level.
    # The original authored coal-plant tower profile is reused at this scale;
    # it is scene geometry and does not assert a plant's actual cooling system.
    tower_center = (25, -32, 0.6)
    tower_profile = [
        (16, 3.2),
        (14.4, 12),
        (11.1, 23),
        (8.8, 33),
        (8.5, 38),
        (9.6, 46),
        (11.5, 52),
    ]
    if level == 1:
        tower_profile = [(16, 3.2), (11.1, 23), (8.5, 38), (11.5, 52)]
    elif level == 2:
        tower_profile = [(16, 0), (8.5, 35), (11.5, 52)]
    _revolve(
        b,
        "nuclear_cooling_tower_shell",
        tower_center,
        tower_profile,
        (40, 20, 10)[level],
        "graphite_light",
    )
    if level < 2:
        b.ring(
            "nuclear_cooling_tower_crown", (25, -32, 52.6), 11.5, 0.14, material="edge"
        )
        b.ring(
            "nuclear_cooling_tower_intake", (25, -32, 3.8), 16, 0.11, material="edge"
        )
        for k in range(12 if level == 0 else 6):
            a = 2 * pi * k / (12 if level == 0 else 6)
            b.beam(
                f"nuclear_cooling_tower_column_{k}",
                (25 + 15.5 * cos(a), -32 + 15.5 * sin(a), 0.6),
                (25 + 16 * cos(a), -32 + 16 * sin(a), 3.8),
                0.44,
                material="graphite",
            )
        if level == 0:
            for k in (1, 3, 5, 7):
                _profile_contour(
                    b,
                    f"nuclear_cooling_tower_meridian_{k}",
                    tower_center,
                    tower_profile,
                    k * pi / 4,
                    0.085,
                )
            _revolve(
                b,
                "nuclear_cooling_tower_inner_lip",
                tower_center,
                [(11.1, 50.5), (11.1, 52)],
                40,
                "graphite",
            )
    else:
        b.ring(
            "nuclear_cooling_tower_lod2_crown",
            (25, -32, 52.6),
            11.5,
            0.16,
            material="edge",
        )
    _cooler_bank(b, "auxiliary_cooling", (-30, 45, 0.6), 2, (8, 11, 5.8), level)
    b.box("condenser_pump_house", (31, 47, 4.6), (19, 12, 8), material="graphite_light")
    _transformer(b, "grid_transformer", (0, 47, 0.6), level)
    if level < 2:
        _outline(b, "condenser_pump_house", (31, 47, 4.6), (19, 12, 8), level)
        b.polyline(
            "cooling_service_pipe",
            [(25, -16, 3), (25, -14, 3), (46, -14, 3), (46, 45, 3), (40, 45, 3)],
            0.65,
            material="graphite_light",
        )
        b.beam("output_bus", (-3, 55, 8), (3, 55, 8), 0.22, material="white")
        for x in (-3, 3):
            b.beam(
                f"output_support_{x}",
                (x, 55, 0.6),
                (x, 55, 8),
                0.24,
                material="graphite_light",
            )


def _coal(b, level):
    _site_base(b, "coal_plant_retiring_site", level)
    # Tall asymmetrical boiler mass stays legible at statewide LOD.
    _hall(b, "boiler_house", (-28, -7, 29.6), (62, 55, 58), level)
    if level < 2:
        b.box("boiler_roof_service", (-28, -15, 62.6), (34, 23, 8), material="graphite")
        _outline(b, "boiler_roof_service", (-28, -15, 62.6), (34, 23, 8), level)
        if level == 0:
            for x in (-50, -28, -6):
                b.cylinder(
                    f"boiler_internal_vessel_{x}",
                    (x, -1, 34),
                    5.5,
                    35,
                    material="graphite",
                    vertices=24,
                )
                for z in (17, 28, 39, 50):
                    b.ring(
                        f"boiler_vessel_band_{x}_{z}",
                        (x, -1, z),
                        5.7,
                        0.16,
                        material="graphite_light",
                    )
            for z in (17, 32, 47):
                b.beam(
                    f"boiler_front_catwalk_{z}",
                    (-59, 20.9, z),
                    (3, 20.9, z),
                    0.55,
                    material="graphite_light",
                )
            for j in range(6):
                x = -57 + j * 12
                b.beam(
                    f"boiler_crossbrace_a_{j}",
                    (x, 21.1, 5),
                    (min(x + 12, 3), 21.1, 20),
                    0.18,
                    material="graphite_light",
                )
                b.beam(
                    f"boiler_crossbrace_b_{j}",
                    (x, 21.1, 32),
                    (min(x + 12, 3), 21.1, 47),
                    0.18,
                    material="graphite_light",
                )
    _hall(b, "turbine_hall", (-10, 54, 14.6), (120, 35, 28), level)
    for idx, (x, height) in enumerate(((-63, 112), (-41, 101))):
        profile = [(4.8, 0), (4.6, 12), (3.0, height)]
        _revolve(
            b,
            f"chimney_{idx}",
            (x, -51, 0.6),
            profile,
            (28, 12, 6)[level],
            "graphite_light",
            cap=True,
        )
        if level < 2:
            for z in (height * 0.26, height * 0.67, height):
                r = 4.6 + (3.0 - 4.6) * (z - 12) / (height - 12)
                b.ring(
                    f"chimney_{idx}_band_{z}",
                    (x, -51, 0.6 + z),
                    r,
                    0.09,
                    material="edge",
                )
        if level == 0:
            b.polyline(
                f"chimney_{idx}_ladder",
                [(x + 4.8, -51, 2), (x + 3, -51, height)],
                0.1,
                material="white",
            )
            b.cylinder(
                f"chimney_{idx}_dark_flue",
                (x, -51, height + 0.66),
                2.5,
                0.12,
                material="graphite",
                vertices=28,
            )
    center = (47, -51, 0.6)
    profile = [(25, 4), (22, 17), (16, 33), (13.8, 47), (14.5, 60), (18, 78)]
    if level == 1:
        profile = [(25, 4), (16, 33), (13.8, 47), (18, 78)]
    elif level == 2:
        profile = [(25, 0), (13.8, 47), (18, 78)]
    _revolve(
        b, "cooling_tower_shell", center, profile, (40, 16, 8)[level], "graphite_light"
    )
    if level < 2:
        b.ring("cooling_tower_crown", (47, -51, 78.6), 18, 0.15, material="edge")
        b.ring("cooling_tower_base", (47, -51, 4.6), 25, 0.12, material="edge")
        for k in range(12 if level == 0 else 6):
            a = 2 * pi * k / (12 if level == 0 else 6)
            b.beam(
                f"cooling_tower_column_{k}",
                (47 + 24.4 * cos(a), -51 + 24.4 * sin(a), 0.6),
                (47 + 25 * cos(a), -51 + 25 * sin(a), 4.6),
                0.55,
                material="graphite",
            )
        if level == 0:
            for k in (1, 3, 5, 7):
                _profile_contour(
                    b, f"cooling_tower_meridian_{k}", center, profile, k * pi / 4, 0.10
                )
            _revolve(
                b,
                "cooling_tower_inner_lip",
                center,
                [(17.4, 76), (17.4, 78)],
                40,
                "graphite",
            )
            b.polyline(
                "cooling_water_return",
                [(47, -24, 4), (47, 11, 4), (37, 11, 4), (37, 34, 4)],
                1.05,
                material="graphite_light",
            )
    # Low covered handling bunker: no piles or effects that imply operating state.
    b.box("fuel_handling_bunker", (-22, -101, 5.6), (99, 29, 10), material="graphite")
    if level < 2:
        _outline(b, "fuel_handling_bunker", (-22, -101, 5.6), (99, 29, 10), level)
        b.polyline(
            "enclosed_conveyor",
            [(-22, -89, 9), (-22, -71, 12), (-27, -34, 32)],
            1.35,
            material="graphite_light",
        )
        if level == 0:
            for y, z in ((-82, 11), (-66, 17), (-50, 24)):
                b.beam(
                    f"conveyor_trestle_{y}",
                    (-25, y, 0.6),
                    (-25, y, z),
                    0.48,
                    material="graphite_light",
                )
                b.beam(
                    f"conveyor_trestle_cross_{y}",
                    (-25, y, 0.6),
                    (-19, y, z),
                    0.26,
                    material="graphite",
                )
    for idx, x in enumerate((38, 59)):
        _transformer(b, f"grid_transformer_{idx}", (x, 93, 0.6), level, 7)
    if level < 2:
        b.beam("output_crossbar", (39, 108, 12), (67, 108, 12), 0.30, material="white")
        for x in (39, 67):
            b.beam(
                f"output_portal_{x}",
                (x, 108, 0.6),
                (x, 108, 12),
                0.5,
                material="graphite_light",
            )
    if level == 0:
        for x in (-50, -25, 0, 25):
            _fan(b, f"turbine_roof_extract_{x}", (x, 48, 29.1), 2.9, level)
        b.box("workshop", (-54, 100, 5.6), (35, 30, 10), material="graphite_light")
        _outline(b, "workshop", (-54, 100, 5.6), (35, 30, 10), level)


def _gas(b, level):
    _site_base(b, "natural_gas_plant", level)
    # Three coherent turbine/HRSG/exhaust trains, with distinct masses at every LOD.
    for idx, x in enumerate((-41, 0, 41)):
        _hall(b, f"turbine_train_{idx}", (x, 18, 9.6), (30, 47, 18), level)
        b.box(f"hrsg_{idx}", (x, -26, 20.6), (27, 26, 40), material="graphite_light")
        b.box(
            f"exhaust_transition_{idx}",
            (x, -47, 16.6),
            (17, 15, 20),
            material="graphite",
        )
        b.cylinder(
            f"exhaust_stack_{idx}",
            (x, -50, 38.6),
            3.2,
            64,
            material="graphite_light",
            vertices=(24, 10, 6)[level],
        )
        if level < 2:
            _outline(b, f"hrsg_{idx}", (x, -26, 20.6), (27, 26, 40), level)
            b.ring(f"stack_{idx}_crown", (x, -50, 70.6), 3.2, 0.1, material="edge")
            b.box(
                f"hrsg_{idx}_frosted_inspection",
                (x, -12.91, 23),
                (23, 0.10, 26),
                material="glass",
            )
            b.polyline(
                f"steam_header_{idx}",
                [(x, -12, 33), (x, -4, 33), (x, -4, 23), (x, 40, 23)],
                0.38,
                material="white",
            )
            if level == 0:
                for z in (10, 21, 32):
                    b.beam(
                        f"hrsg_{idx}_horizontal_{z}",
                        (x - 13.5, -12.7, z),
                        (x + 13.5, -12.7, z),
                        0.2,
                        material="graphite",
                    )
                for side in (-1, 1):
                    for k in range(7):
                        z = 5 + k * 5
                        b.beam(
                            f"hrsg_{idx}_louvre_{side}_{k}",
                            (x + side * 13.61, -37, z),
                            (x + side * 13.61, -15, z),
                            0.19,
                            material="graphite",
                        )
                for off in (-7, 7):
                    b.polyline(
                        f"gas_turbine_{idx}_{off}",
                        [(x + off, 3, 6.3), (x + off, 32, 6.3)],
                        2.2,
                        material="graphite_light",
                    )
                    for k in range(3):
                        b.box(
                            f"turbine_mount_{idx}_{off}_{k}",
                            (x + off, 7 + 10 * k, 2.8),
                            (6, 2.5, 4.4),
                            material="graphite",
                        )
                b.box(
                    f"intake_filter_{idx}",
                    (x, 39, 12),
                    (22, 8, 12),
                    material="graphite_light",
                )
                for j in range(9):
                    b.beam(
                        f"intake_louvre_{idx}_{j}",
                        (x - 10, 43.1, 7 + j * 1.1),
                        (x + 10, 43.1, 7 + j * 1.1),
                        0.16,
                        material="graphite",
                    )
    _hall(b, "steam_turbine_hall", (-23, 65, 8.6), (80, 24, 16), level)
    _transformer(b, "grid_transformer", (48, 76, 0.6), level, 6)
    for idx, x in enumerate((-38, 0, 38)):
        _cooler_bank(
            b, f"air_cooling_bank_{idx}", (x, -80, 0.6), 3, (8.5, 14, 8), level
        )
    if level < 2:
        b.beam("output_bus", (41, 88, 10), (55, 88, 10), 0.26, material="white")
        for x in (41, 55):
            b.beam(
                f"output_support_{x}",
                (x, 88, 0.6),
                (x, 88, 10),
                0.33,
                material="graphite_light",
            )
        if level == 0:
            b.polyline(
                "gas_service_header",
                [(-56, -66, 3), (56, -66, 3)],
                0.45,
                material="graphite_light",
            )
            for x in (-41, 0, 41):
                b.polyline(
                    f"gas_branch_{x}",
                    [(x, -66, 3), (x, -60, 3), (x, -60, 7), (x, -12, 7)],
                    0.3,
                    material="graphite_light",
                )


def build(asset_id, lod=0):
    """Create one isolated archetype using the shared Blender Builder."""
    from asset_builder import Builder

    level = _lod(lod)
    if asset_id not in ASSETS:
        raise ValueError(f"Unknown generation archetype: {asset_id}")
    b = Builder(asset_id, level)
    {
        "nuclear_smr_module": _nuclear,
        "coal_plant_retiring_site": _coal,
        "natural_gas_plant": _gas,
    }[asset_id](b, level)
    b.connector("HV_OUT", 0, ASSETS[asset_id]["connector"])
    return b

"""Validate the committed 3D archetype source kits against the shared contract.

`scripts/validate_asset_archetypes.py` validates the *catalog* and never walks
`data/3d/assets/`, so every property an asset directory claims - its identity,
its metadata fields, its status-label vocabulary, and above all its geometry -
was unchecked. This module walks each source kit and refuses one that disagrees
with the catalog row named by its own directory.

The directory name is the identity. The catalog row is looked up by directory
name, never by the metadata's own `archetype_id`, so a coherent hospital meta
dropped into `data/3d/assets/factory_industrial_facility/` fails instead of
passing against the row it names.

`data/3d/assets/` holds three delivery tiers, and this module applies exactly
one of them per entry, chosen from what the entry actually contains:

* **source kit** - a directory holding `<id>.scene.json`; the geometry is
  authored as data and is checked against the footprint here.
* **blender kit** - a directory holding `<id>.blender.py`; the geometry lives in
  a Blender build script, so this module checks the metadata, the declared
  `bounds_m`, and that no build output was committed beside it.
* **flat meta** - a bare `<id>.meta.json` file directly under the asset root,
  which declares a pipeline delivery and is checked by
  `scripts.asset_contract_lib.validate_export_meta`.

An entry that matches none of the three is refused by name
(`unknown_asset_tier`) rather than skipped: a directory nobody validates is
indistinguishable from one that passes.
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data/3d/asset-archetypes-v1.json"
DEFAULT_ASSET_ROOT = ROOT / "data/3d/assets"

SOURCE_FORMAT = "flux:3d-archetype-source:v1"
# Rendered geometry must fit inside its declared footprint rectangle within 5%
# (catalog `footprint.tolerance`).
FOOTPRINT_TOLERANCE = 0.05
GEOMETRY_EPSILON = 1e-6
CONNECTOR_NAME = re.compile(r"^CONN_(?P<role>[A-Z_]+)_(?P<index>\d+)$")
# A source kit is text-only: the binaries are asset-pipeline outputs.
SOURCE_KIT_SUFFIXES = (".meta.json", ".scene.json", ".preview.svg")
# A blender kit is text-only too: the scene lives in a build script.
BLENDER_KIT_SUFFIXES = (".meta.json", ".blender.py")
BLENDER_KIT_DOC = "README.md"
# The tier names this module reports; `UNKNOWN_TIER` is a refusal, not a skip.
SOURCE_KIT_TIER = "source_kit"
BLENDER_KIT_TIER = "blender_kit"
FLAT_META_TIER = "flat_meta"
UNKNOWN_TIER = "unknown_asset_tier"
FLAT_META_SUFFIX = ".meta.json"
# The transform keys a blender kit pins; each value is read from the catalog.
BLENDER_TRANSFORM_KEYS = (
    ("length_unit", "lengthUnit"),
    ("unit_scale", "unitScale"),
    ("up_axis", "upAxis"),
    ("forward_axis", "forwardAxis"),
    ("pivot", "pivot"),
)
BLENDER_STATUS_BINDING = "placement.status_label"
BLENDER_OUTPUT_SUFFIXES = (("glb", ".glb"), ("preview", ".preview.png"))
PIPELINE_OUTPUT_KEYS = ("model_file", "preview_file")
MIN_PREVIEW_DRAW_ELEMENTS = 4
DRAWABLE_TAGS = {
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "path",
    "text",
    "use",
    "image",
}


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def load_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def asset_dirs(asset_root: Path = DEFAULT_ASSET_ROOT) -> list[Path]:
    if not asset_root.is_dir():
        return []
    return sorted(path for path in asset_root.iterdir() if path.is_dir())


def flat_meta_files(asset_root: Path = DEFAULT_ASSET_ROOT) -> list[Path]:
    """Bare `<id>.meta.json` deliveries that sit directly under the asset root."""
    if not asset_root.is_dir():
        return []
    return sorted(
        path
        for path in asset_root.iterdir()
        if path.is_file() and path.name.endswith(FLAT_META_SUFFIX)
    )


def asset_entries(asset_root: Path = DEFAULT_ASSET_ROOT) -> list[Path]:
    """Every asset this module is answerable for: kit directories and flat metas."""
    return sorted(
        asset_dirs(asset_root) + flat_meta_files(asset_root), key=lambda p: p.name
    )


def entry_id(path: Path) -> str:
    """The archetype id an entry claims by its own name."""
    if path.is_file() or path.name.endswith(FLAT_META_SUFFIX):
        return path.name[: -len(FLAT_META_SUFFIX)]
    return path.name


def asset_tier(path: Path) -> str | None:
    """Which tier's rules govern this entry, or ``None`` when it matches none.

    Tier is decided by what the entry contains, never by its name, so a kit that
    changes tier changes the rules applied to it and a kit that carries neither
    marker file is refused rather than validated against a guess.
    """
    if path.is_file():
        return FLAT_META_TIER if path.name.endswith(FLAT_META_SUFFIX) else None
    if not path.is_dir():
        return None
    asset_id = path.name
    if (path / f"{asset_id}.scene.json").is_file():
        return SOURCE_KIT_TIER
    if (path / f"{asset_id}.blender.py").is_file():
        return BLENDER_KIT_TIER
    return None


def node_aabb(nodes: list[dict[str, Any]]) -> dict[str, list[float]] | None:
    """Axis-aligned bounds of every node, empties included as points."""
    lows: list[list[float]] = []
    highs: list[list[float]] = []
    for node in nodes:
        position = node.get("position_m")
        if not isinstance(position, list) or len(position) != 3:
            continue
        size = node.get("size_m") or [0.0, 0.0, 0.0]
        if not isinstance(size, list) or len(size) != 3:
            continue
        lows.append([position[axis] - size[axis] / 2 for axis in range(3)])
        highs.append([position[axis] + size[axis] / 2 for axis in range(3)])
    if not lows:
        return None
    return {
        "min": [min(low[axis] for low in lows) for axis in range(3)],
        "max": [max(high[axis] for high in highs) for axis in range(3)],
    }


def _validate_files(asset_dir: Path, asset_id: str) -> list[str]:
    errors: list[str] = []
    expected = {f"{asset_id}{suffix}" for suffix in SOURCE_KIT_SUFFIXES}
    present = {path.name for path in asset_dir.iterdir() if path.is_file()}
    for missing in sorted(expected - present):
        errors.append(f"{asset_id}: source kit is missing {missing}")
    for extra in sorted(present - expected):
        errors.append(
            f"{asset_id}: {extra} is not part of the source kit; binaries and "
            "renders are asset-pipeline outputs and are not committed"
        )
    return errors


def _validate_meta_identity(
    meta: dict[str, Any], archetype: dict[str, Any], catalog: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    asset_id = archetype["id"]
    if meta.get("archetype_id") != asset_id:
        errors.append(
            f"{asset_id}: meta archetype_id {meta.get('archetype_id')!r} must equal "
            "the asset directory name"
        )
    if meta.get("contract_id") != catalog["contractId"]:
        errors.append(f"{asset_id}: meta contract_id must be {catalog['contractId']}")
    if meta.get("semantic_name") != archetype["semantic_name"]:
        errors.append(f"{asset_id}: semantic_name must match the catalog row")
    if meta.get("category") != archetype["category"]:
        errors.append(
            f"{asset_id}: category {meta.get('category')!r} must equal the catalog "
            f"category {archetype['category']!r}"
        )
    if meta.get("footprint_m") != archetype["footprint_m"]:
        errors.append(f"{asset_id}: footprint_m must match the catalog row")
    for field in ("author", "license", "source_of_shape", "limit"):
        value = meta.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{asset_id}: meta {field} must be a non-empty string")
    return errors


def _validate_meta_fields(
    meta: dict[str, Any], archetype: dict[str, Any], catalog: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    asset_id = archetype["id"]
    required = set(catalog["deliverables"]["metaFields"])
    for missing in sorted(required - set(meta)):
        errors.append(f"{asset_id}: meta is missing required field {missing}")
    for level, expected in archetype["lod_triangles"].items():
        flat = f"triangles_{level}"
        if flat in meta and meta[flat] != expected:
            errors.append(
                f"{asset_id}: {flat} {meta[flat]} must equal the catalog budget "
                f"{expected}"
            )
    nested = meta.get("triangles")
    if nested is not None and nested != archetype["lod_triangles"]:
        errors.append(f"{asset_id}: triangles block must equal the catalog budget")
    return errors


def _validate_transform(meta: dict[str, Any], asset_id: str) -> list[str]:
    errors: list[str] = []
    transform = meta.get("transform") or {}
    expected = {
        "length_unit": "meter",
        "unit_scale": 1.0,
        "up_axis": "Y",
        "forward_axis": "-Z",
        "handedness": "right",
        "pivot": "ground_center",
    }
    for key, value in expected.items():
        if transform.get(key) != value:
            errors.append(
                f"{asset_id}: transform.{key} must be {value!r}, got "
                f"{transform.get(key)!r}"
            )
    return errors


def _validate_status_slot(
    meta: dict[str, Any], catalog: dict[str, Any], asset_id: str
) -> list[str]:
    errors: list[str] = []
    slots = meta.get("material_slots")
    if not isinstance(slots, list) or not slots:
        return [f"{asset_id}: meta must declare the shared status material slot"]
    materials = catalog["statusMaterials"]
    status = next(
        (slot for slot in slots if slot.get("name") == materials["slotName"]), None
    )
    if status is None:
        return [f"{asset_id}: meta has no {materials['slotName']} slot"]
    if status.get("runtime_tinted") is not True:
        errors.append(f"{asset_id}: {materials['slotName']} must be runtime_tinted")
    if status.get("default") != "neutral":
        errors.append(f"{asset_id}: {materials['slotName']} must ship neutral")
    if status.get("allowed_labels") != materials["allowedLabels"]:
        errors.append(
            f"{asset_id}: allowed_labels must be exactly the server-asserted labels "
            f"{materials['allowedLabels']}"
        )
    return errors


def _validate_connectors(
    meta: dict[str, Any], archetype: dict[str, Any], catalog: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    asset_id = archetype["id"]
    connectors = meta.get("connectors")
    if not isinstance(connectors, list) or not connectors:
        return [f"{asset_id}: meta connectors must be a non-empty list"]
    roles = [connector.get("role") for connector in connectors]
    if roles != archetype["connectors"]:
        errors.append(
            f"{asset_id}: connector roles {roles} must equal the catalog roles "
            f"{archetype['connectors']}"
        )
    known_roles = set(catalog["connectors"]["roles"])
    for connector in connectors:
        name = connector.get("name", "")
        match = CONNECTOR_NAME.match(name if isinstance(name, str) else "")
        if match is None or match.group("role") not in known_roles:
            errors.append(
                f"{asset_id}: connector name {name!r} must be CONN_<role>_<index>"
            )
        elif match.group("role") != connector.get("role"):
            errors.append(f"{asset_id}: connector {name} does not name its own role")
        position = connector.get("position_m")
        if not isinstance(position, list) or len(position) != 3:
            errors.append(f"{asset_id}: connector {name} needs a 3-vector position_m")
    return errors


def _validate_export(
    meta: dict[str, Any], asset_dir: Path, catalog: dict[str, Any]
) -> list[str]:
    """The meta may not name a render that does not exist and nobody produces."""
    errors: list[str] = []
    asset_id = asset_dir.name
    export = meta.get("export") or {}
    if export.get("container") != "glb" or export.get("specification") != "glTF 2.0":
        errors.append(f"{asset_id}: export must declare the glb / glTF 2.0 runtime")
    if export.get("preview_pixels") != catalog["deliverables"]["previewPixels"]:
        errors.append(
            f"{asset_id}: export preview_pixels must be "
            f"{catalog['deliverables']['previewPixels']}"
        )
    for phantom in PIPELINE_OUTPUT_KEYS:
        if phantom in export:
            errors.append(
                f"{asset_id}: export.{phantom} names a file this repository does not "
                "contain; declare it under export.pipeline_outputs instead"
            )
    preview_source = export.get("preview_source")
    if preview_source != f"{asset_id}.preview.svg":
        errors.append(f"{asset_id}: export preview_source must name the committed SVG")
    elif not (asset_dir / preview_source).is_file():
        errors.append(f"{asset_id}: export preview_source {preview_source} is missing")
    outputs = export.get("pipeline_outputs")
    if not isinstance(outputs, dict) or set(outputs) != set(PIPELINE_OUTPUT_KEYS):
        errors.append(
            f"{asset_id}: export.pipeline_outputs must name {list(PIPELINE_OUTPUT_KEYS)}"
        )
    else:
        if outputs["model_file"] != f"{asset_id}.glb":
            errors.append(f"{asset_id}: pipeline model_file must be {asset_id}.glb")
        if outputs["preview_file"] != f"{asset_id}.preview.png":
            errors.append(
                f"{asset_id}: pipeline preview_file must be {asset_id}.preview.png"
            )
        for name in outputs.values():
            if isinstance(name, str) and (asset_dir / name).exists():
                errors.append(
                    f"{asset_id}: {name} is an asset-pipeline output and must not be "
                    "committed"
                )
    return errors


def _validate_scene(
    meta: dict[str, Any], asset_dir: Path, archetype: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    asset_id = archetype["id"]
    source_scene = meta.get("source_scene")
    if source_scene != f"{asset_id}.scene.json":
        errors.append(f"{asset_id}: meta source_scene must name {asset_id}.scene.json")
        return errors
    scene_path = asset_dir / source_scene
    if not scene_path.is_file():
        errors.append(f"{asset_id}: meta source_scene {source_scene} does not resolve")
        return errors
    try:
        scene = json.loads(scene_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{asset_id}: {source_scene} is not valid JSON ({exc})"]

    if scene.get("format") != SOURCE_FORMAT:
        errors.append(f"{asset_id}: scene format must be {SOURCE_FORMAT}")
    if scene.get("archetype_id") != asset_id:
        errors.append(
            f"{asset_id}: scene archetype_id {scene.get('archetype_id')!r} must equal "
            "the asset directory name"
        )
    if scene.get("pivot") != "ground_center":
        errors.append(f"{asset_id}: scene pivot must be ground_center")

    nodes = scene.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append(f"{asset_id}: scene must declare at least one node")
        return errors

    empties = {node.get("name") for node in nodes if node.get("primitive") == "empty"}
    declared = {connector.get("name") for connector in meta.get("connectors", [])}
    if empties != declared:
        errors.append(
            f"{asset_id}: scene connector empties {sorted(map(str, empties))} must "
            f"equal the meta connectors {sorted(map(str, declared))}"
        )

    aabb = node_aabb(nodes)
    if aabb is None:
        errors.append(f"{asset_id}: no scene node carries a usable position/size")
        return errors

    footprint = archetype["footprint_m"]
    limits = (
        ("width", 0, footprint["width"]),
        ("length", 2, footprint["length"]),
    )
    for label, axis, declared_size in limits:
        extent = aabb["max"][axis] - aabb["min"][axis]
        if extent > declared_size * (1 + FOOTPRINT_TOLERANCE) + GEOMETRY_EPSILON:
            over = extent / declared_size - 1
            errors.append(
                f"{asset_id}: geometry {label} {extent:g} m exceeds the declared "
                f"{declared_size:g} m footprint by {over:.1%} (tolerance "
                f"{FOOTPRINT_TOLERANCE:.0%})"
            )
    if abs(aabb["min"][1]) > GEOMETRY_EPSILON:
        errors.append(
            f"{asset_id}: pivot is ground_center but geometry starts at y="
            f"{aabb['min'][1]:g}, not 0"
        )

    bounds = scene.get("bounds_m")
    if not isinstance(bounds, dict) or not {"min", "max"} <= set(bounds):
        errors.append(f"{asset_id}: scene must declare bounds_m with min and max")
    else:
        for axis, name in enumerate("xyz"):
            if aabb["min"][axis] < bounds["min"][axis] - GEOMETRY_EPSILON or (
                aabb["max"][axis] > bounds["max"][axis] + GEOMETRY_EPSILON
            ):
                errors.append(
                    f"{asset_id}: geometry spans {name} "
                    f"[{aabb['min'][axis]:g}, {aabb['max'][axis]:g}] outside the "
                    f"declared bounds_m [{bounds['min'][axis]:g}, "
                    f"{bounds['max'][axis]:g}]"
                )
    return errors


def _validate_preview(asset_dir: Path, catalog: dict[str, Any]) -> list[str]:
    """The preview must be a readable image, not an empty element."""
    errors: list[str] = []
    asset_id = asset_dir.name
    path = asset_dir / f"{asset_id}.preview.svg"
    if not path.is_file():
        return [f"{asset_id}: {path.name} is missing"]
    text = path.read_text(encoding="utf-8")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [f"{asset_id}: {path.name} is not parseable SVG ({exc})"]
    if _tag(root) != "svg":
        return [f"{asset_id}: {path.name} root element must be <svg>"]

    pixels = str(catalog["deliverables"]["previewPixels"])
    if root.get("width") != pixels or root.get("height") != pixels:
        errors.append(f"{asset_id}: preview must be {pixels}x{pixels} px")

    described_by = (root.get("aria-labelledby") or "").split()
    titles = {
        _tag(element): element
        for element in root.iter()
        if _tag(element) in {"title", "desc"}
    }
    for kind in ("title", "desc"):
        element = titles.get(kind)
        if element is None or not (element.text or "").strip():
            errors.append(f"{asset_id}: preview needs a non-empty <{kind}>")
        elif element.get("id") not in described_by:
            errors.append(
                f"{asset_id}: preview <{kind}> id must appear in aria-labelledby"
            )
    if root.get("role") != "img":
        errors.append(f'{asset_id}: preview root must carry role="img"')

    drawn = sum(1 for element in root.iter() if _tag(element) in DRAWABLE_TAGS)
    if drawn < MIN_PREVIEW_DRAW_ELEMENTS:
        errors.append(
            f"{asset_id}: preview draws {drawn} element(s); an empty or placeholder "
            f"SVG is not a preview (minimum {MIN_PREVIEW_DRAW_ELEMENTS})"
        )
    return errors


def _validate_blender_files(asset_dir: Path, asset_id: str) -> list[str]:
    """A blender kit is its README, its build script, and its meta - nothing else."""
    errors: list[str] = []
    expected = {f"{asset_id}{suffix}" for suffix in BLENDER_KIT_SUFFIXES}
    expected.add(BLENDER_KIT_DOC)
    present = {path.name for path in asset_dir.iterdir() if path.is_file()}
    for missing in sorted(expected - present):
        errors.append(f"{asset_id}: blender kit is missing {missing}")
    for extra in sorted(present - expected):
        errors.append(
            f"{asset_id}: {extra} is not part of the blender kit; binaries and "
            "renders are asset-pipeline outputs and must not be committed"
        )
    return errors


def _validate_blender_transform(
    meta: dict[str, Any], catalog: dict[str, Any], asset_id: str
) -> list[str]:
    """Every pinned axis value is read from the catalog, never restated here."""
    errors: list[str] = []
    transform = meta.get("transform")
    if not isinstance(transform, dict):
        return [f"{asset_id}: meta transform must be an object"]
    catalog_transform = catalog["transform"]
    for key, catalog_key in BLENDER_TRANSFORM_KEYS:
        expected = catalog_transform[catalog_key]
        if transform.get(key) != expected:
            errors.append(
                f"{asset_id}: transform.{key} must be {expected!r}, got "
                f"{transform.get(key)!r}"
            )
    return errors


def _validate_blender_status_slot(
    meta: dict[str, Any], catalog: dict[str, Any], asset_id: str
) -> list[str]:
    slot_name = catalog["statusMaterials"]["slotName"]
    expected = [
        {"name": slot_name, "default": "neutral", "binding": BLENDER_STATUS_BINDING}
    ]
    if meta.get("material_slots") != expected:
        return [
            (
                f"{asset_id}: meta material_slots must be exactly the neutral "
                f"{slot_name} slot bound to {BLENDER_STATUS_BINDING}"
            )
        ]
    return []


def _validate_blender_bounds(
    meta: dict[str, Any], archetype: dict[str, Any]
) -> list[str]:
    """A blender kit ships no scene data, so its declared bounds carry the geometry."""
    errors: list[str] = []
    asset_id = archetype["id"]
    bounds = meta.get("bounds_m")
    if not isinstance(bounds, dict) or not {"min", "max"} <= set(bounds):
        return [f"{asset_id}: meta must declare bounds_m with min and max"]
    for key in ("min", "max"):
        value = bounds[key]
        if not isinstance(value, list) or len(value) != 3:
            errors.append(f"{asset_id}: bounds_m.{key} must be a 3-vector")
    if errors:
        return errors
    for axis, name in enumerate("xyz"):
        if bounds["min"][axis] > bounds["max"][axis]:
            errors.append(f"{asset_id}: bounds_m {name} min exceeds max")
    if errors:
        return errors
    footprint = archetype["footprint_m"]
    for label, axis, declared_size in (
        ("width", 0, footprint["width"]),
        ("length", 2, footprint["length"]),
    ):
        extent = bounds["max"][axis] - bounds["min"][axis]
        if extent > declared_size * (1 + FOOTPRINT_TOLERANCE) + GEOMETRY_EPSILON:
            over = extent / declared_size - 1
            errors.append(
                f"{asset_id}: geometry {label} {extent:g} m exceeds the declared "
                f"{declared_size:g} m footprint by {over:.1%} (tolerance "
                f"{FOOTPRINT_TOLERANCE:.0%})"
            )
    if abs(bounds["min"][1]) > GEOMETRY_EPSILON:
        errors.append(
            f"{asset_id}: pivot is ground_center but geometry starts at y="
            f"{bounds['min'][1]:g}, not 0"
        )
    return errors


def _validate_blender_outputs(meta: dict[str, Any], asset_dir: Path) -> list[str]:
    """The meta names its build outputs; none of them may be in the repository."""
    errors: list[str] = []
    asset_id = asset_dir.name
    outputs = meta.get("outputs")
    if not isinstance(outputs, dict):
        return [f"{asset_id}: meta outputs must name the build products"]
    expected = {key: f"{asset_id}{suffix}" for key, suffix in BLENDER_OUTPUT_SUFFIXES}
    expected["source"] = f"{asset_id}.blender.py"
    if set(outputs) != set(expected):
        errors.append(f"{asset_id}: outputs must name {sorted(expected)}")
    for key, want in expected.items():
        if key in outputs and outputs[key] != want:
            errors.append(f"{asset_id}: outputs.{key} must be {want}")
    if not (asset_dir / expected["source"]).is_file():
        errors.append(
            f"{asset_id}: outputs.source {expected['source']} does not resolve"
        )
    for key, _ in BLENDER_OUTPUT_SUFFIXES:
        name = outputs.get(key)
        if isinstance(name, str) and (asset_dir / name).exists():
            errors.append(
                f"{asset_id}: {name} is an asset-pipeline output and must not be "
                "committed"
            )
    return errors


def validate_blender_kit(
    asset_dir: Path, archetype: dict[str, Any], catalog: dict[str, Any]
) -> list[str]:
    """Contract violations for a kit whose geometry lives in a Blender script."""
    asset_id = archetype["id"]
    errors = _validate_blender_files(asset_dir, asset_id)
    meta_path = asset_dir / f"{asset_id}.meta.json"
    if not meta_path.is_file():
        return errors
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return errors + [f"{asset_id}: {meta_path.name} is not valid JSON ({exc})"]

    errors += _validate_meta_identity(meta, archetype, catalog)
    errors += _validate_meta_fields(meta, archetype, catalog)
    errors += _validate_blender_transform(meta, catalog, asset_id)
    errors += _validate_blender_status_slot(meta, catalog, asset_id)
    errors += _validate_connectors(meta, archetype, catalog)
    errors += _validate_blender_bounds(meta, archetype)
    errors += _validate_blender_outputs(meta, asset_dir)
    return errors


def _contract_lib() -> Any:
    """`scripts.asset_contract_lib`, importable as a package or as a bare script."""
    try:
        from scripts import asset_contract_lib
    except ImportError:  # pragma: no cover - direct `python scripts/...` execution
        import asset_contract_lib  # type: ignore[no-redef]
    return asset_contract_lib


def validate_flat_meta(meta_path: Path, catalog: dict[str, Any]) -> list[str]:
    """A bare `<id>.meta.json` delivery, checked by the shared contract library."""
    asset_id = entry_id(meta_path)
    lib = _contract_lib()
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{asset_id}: {meta_path.name} is not valid JSON ({exc})"]
    try:
        errors = lib.validate_export_meta(meta, catalog, asset_id, ROOT)
    except lib.AssetContractError as exc:
        return [f"{asset_id}: {exc.reason}: {exc.detail}"]
    return [f"{asset_id}: {error}" for error in errors]


def validate_source_kit(
    asset_dir: Path, archetype: dict[str, Any], catalog: dict[str, Any]
) -> list[str]:
    """Contract violations for a kit whose geometry is authored in `<id>.scene.json`."""
    asset_id = archetype["id"]
    errors = _validate_files(asset_dir, asset_id)
    meta_path = asset_dir / f"{asset_id}.meta.json"
    if not meta_path.is_file():
        return errors
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return errors + [f"{asset_id}: {meta_path.name} is not valid JSON ({exc})"]

    errors += _validate_meta_identity(meta, archetype, catalog)
    errors += _validate_meta_fields(meta, archetype, catalog)
    errors += _validate_transform(meta, asset_id)
    errors += _validate_status_slot(meta, catalog, asset_id)
    errors += _validate_connectors(meta, archetype, catalog)
    errors += _validate_export(meta, asset_dir, catalog)
    errors += _validate_scene(meta, asset_dir, archetype)
    errors += _validate_preview(asset_dir, catalog)
    return errors


def validate_asset(asset_path: Path, catalog: dict[str, Any]) -> list[str]:
    """Return every contract violation for one asset entry; empty means it conforms.

    The entry's own contents choose the tier, and only that tier's rules run. An
    entry matching no tier is refused by name; it is never silently skipped.
    """
    asset_id = entry_id(asset_path)
    archetype = next(
        (entry for entry in catalog["archetypes"] if entry["id"] == asset_id), None
    )
    if archetype is None:
        return [
            (
                f"{asset_id}: no catalog archetype is named by this directory; "
                "an asset directory name is its identity"
            )
        ]

    tier = asset_tier(asset_path)
    if tier == SOURCE_KIT_TIER:
        return validate_source_kit(asset_path, archetype, catalog)
    if tier == BLENDER_KIT_TIER:
        return validate_blender_kit(asset_path, archetype, catalog)
    if tier == FLAT_META_TIER:
        return validate_flat_meta(asset_path, catalog)
    return [
        (
            f"{asset_id}: {UNKNOWN_TIER}: an asset entry must be a source kit "
            f"({asset_id}.scene.json), a blender kit ({asset_id}.blender.py), or a "
            f"flat {asset_id}{FLAT_META_SUFFIX} delivery; this one is none of them"
        )
    ]


def build_report(
    catalog: dict[str, Any], asset_root: Path = DEFAULT_ASSET_ROOT
) -> dict[str, Any]:
    entries = asset_entries(asset_root)
    assets = {entry_id(entry): validate_asset(entry, catalog) for entry in entries}
    tiers = {entry_id(entry): asset_tier(entry) for entry in entries}
    errors = [error for messages in assets.values() for error in messages]
    return {
        "contractId": catalog.get("contractId"),
        "assetRoot": str(asset_root),
        "assetCount": len(entries),
        "assets": {
            name: {"passed": not messages, "tier": tiers[name] or UNKNOWN_TIER}
            for name, messages in assets.items()
        },
        "validation": {"passed": not errors, "errors": errors},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSET_ROOT)
    args = parser.parse_args()
    report = build_report(load_catalog(args.catalog), args.assets)
    print(json.dumps(report, indent=2))
    return 0 if report["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

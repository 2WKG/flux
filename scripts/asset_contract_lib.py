"""Shared helpers binding a 3D archetype delivery to the catalog that governs it.

Every rule in this module reads ``data/3d/asset-archetypes-v1.json``. Nothing
hand-copies a footprint, a connector role, a preview size, or a triangle budget,
so a delivery that drifts from the catalog is an error rather than a value that
silently re-anchors. Failures are named (``AssetContractError.reason``) instead
of surfacing as a bare ``KeyError``, per CLAUDE.md's rule that missing data
produces an explicit error and never a plausible default.
"""

from __future__ import annotations

import json
import re
import struct
import zlib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data/3d/asset-archetypes-v1.json"

GLB_JSON_CHUNK = b"JSON"
GLB_BIN_CHUNK = b"BIN\x00"


class AssetContractError(Exception):
    """A named failure. ``reason`` is machine-readable; ``detail`` is for a human."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def load_json(path: Path, what: str) -> Any:
    """Read JSON, naming the failure instead of leaking a traceback."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise AssetContractError(f"{what}_unavailable", f"{path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AssetContractError(f"{what}_malformed", f"{path}: {exc}") from exc


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    catalog = load_json(path, "catalog")
    if not isinstance(catalog, dict) or not isinstance(catalog.get("archetypes"), list):
        raise AssetContractError(
            "catalog_malformed", f"{path} carries no archetype list"
        )
    return catalog


def require(mapping: Any, key: str, what: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise AssetContractError("missing_field", f"{what}.{key}")
    return mapping[key]


def catalog_entry(catalog: dict[str, Any], archetype_id: str) -> dict[str, Any]:
    for item in catalog.get("archetypes") or []:
        if isinstance(item, dict) and item.get("id") == archetype_id:
            return item
    raise AssetContractError("archetype_not_in_catalog", archetype_id)


def budgets(catalog: dict[str, Any]) -> dict[str, Any]:
    return require(catalog, "budgets", "catalog")


def deliverables(catalog: dict[str, Any]) -> dict[str, Any]:
    return require(catalog, "deliverables", "catalog")


def preview_pixels(catalog: dict[str, Any]) -> int:
    return int(require(deliverables(catalog), "previewPixels", "catalog.deliverables"))


def meta_fields(catalog: dict[str, Any]) -> list[str]:
    return list(require(deliverables(catalog), "metaFields", "catalog.deliverables"))


def required_filenames(catalog: dict[str, Any], archetype_id: str) -> list[str]:
    templates = require(deliverables(catalog), "required", "catalog.deliverables")
    return [str(t).replace("<archetype_id>", archetype_id) for t in templates]


def connector_roles(catalog: dict[str, Any]) -> list[str]:
    roles = require(
        require(catalog, "connectors", "catalog"), "roles", "catalog.connectors"
    )
    return list(roles)


def allowed_labels(catalog: dict[str, Any]) -> list[str]:
    slot = require(catalog, "statusMaterials", "catalog")
    return list(require(slot, "allowedLabels", "catalog.statusMaterials"))


def retired_labels(catalog: dict[str, Any]) -> list[str]:
    """Labels the catalog's own note retires, e.g. the quoted 'illustrative'."""
    note = str(require(catalog, "statusMaterials", "catalog").get("note", ""))
    return [word.lower() for word in re.findall(r"'([A-Za-z_]+)'", note)]


def lod_ratios(catalog: dict[str, Any]) -> tuple[float, float]:
    """Read the lod1/lod2 percentages out of the catalog's own lodRule prose."""
    rule = str(require(budgets(catalog), "lodRule", "catalog.budgets"))
    percents = re.findall(r"(\d+)\s*%", rule)
    if len(percents) != 2:
        raise AssetContractError("catalog_lod_rule_unparsed", rule)
    return int(percents[0]) / 100.0, int(percents[1]) / 100.0


def triangle_budget_errors(
    counts: dict[str, Any], catalog: dict[str, Any], label: str = "lod_triangles"
) -> list[str]:
    """Ceiling and LOD-chain rules. ``None`` means "not measured", not "zero"."""
    ceiling = int(
        require(budgets(catalog), "perArchetypeTrianglesLod0", "catalog.budgets")
    )
    lod1_ratio, lod2_ratio = lod_ratios(catalog)
    errors: list[str] = []
    lod0 = counts.get("lod0")
    if lod0 is None:
        return errors
    if not isinstance(lod0, (int, float)) or isinstance(lod0, bool) or lod0 <= 0:
        return [f"{label}.lod0 must be a positive triangle count"]
    if lod0 > ceiling:
        errors.append(f"{label}.lod0 {lod0} exceeds the contract ceiling {ceiling}")
    for lod, ratio in (("lod1", lod1_ratio), ("lod2", lod2_ratio)):
        value = counts.get(lod)
        if value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            errors.append(f"{label}.{lod} must be a positive triangle count")
        elif value > lod0 * ratio:
            errors.append(
                f"{label}.{lod} {value} exceeds {int(ratio * 100)}% of lod0 ({lod0})"
            )
    return errors


def file_size_errors(nbytes: int, catalog: dict[str, Any], name: str) -> list[str]:
    ceiling = int(require(budgets(catalog), "perArchetypeFileBytes", "catalog.budgets"))
    if nbytes > ceiling:
        return [f"{name} is {nbytes} bytes, over the contract ceiling {ceiling}"]
    return []


def meta_field_errors(meta: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    return [
        f"metadata is missing the contract field {field}"
        for field in meta_fields(catalog)
        if not isinstance(meta, dict) or field not in meta
    ]


def filename_errors(
    meta: dict[str, Any], catalog: dict[str, Any], archetype_id: str
) -> list[str]:
    names = required_filenames(catalog, archetype_id)
    expected = {Path(n).suffixes[-1]: n for n in names}
    errors: list[str] = []
    for key, suffix in (("model_filename", ".glb"), ("preview_filename", ".png")):
        want = expected.get(suffix)
        if want is None:
            errors.append(f"catalog declares no required {suffix} deliverable")
        elif meta.get(key) != want:
            errors.append(f"{key} must be {want} per deliverables.required")
    return errors


def label_vocabulary_errors(
    label: Any, disclosure: Any, catalog: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    if label not in allowed_labels(catalog):
        errors.append(f"truth_label {label!r} is not in statusMaterials.allowedLabels")
    text = str(disclosure or "")
    if not text.strip():
        errors.append("disclosure must state what the asset is not")
    for retired in retired_labels(catalog):
        if re.search(rf"\b{re.escape(retired)}\b", text, re.IGNORECASE):
            errors.append(f"disclosure uses {retired!r}, a label the catalog retires")
    return errors


def glb_chunk(kind: bytes, payload: bytes) -> bytes:
    """Pack one GLB chunk. JSON pads with spaces, BIN pads with zeros (glTF 2.0 3.3)."""
    if len(kind) != 4:
        raise AssetContractError("glb_chunk_type_invalid", repr(kind))
    pad = b" " if kind == GLB_JSON_CHUNK else b"\x00"
    payload = payload + pad * ((-len(payload)) % 4)
    return struct.pack("<I4s", len(payload), kind) + payload


def glb_bytes(document: dict[str, Any], binary: bytes) -> bytes:
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    body = glb_chunk(GLB_JSON_CHUNK, payload) + glb_chunk(GLB_BIN_CHUNK, binary)
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def parse_glb(raw: bytes) -> tuple[dict[str, Any], bytes]:
    """Parse a GLB the way a conformant loader does: unknown chunk types are ignored.

    Raises a named error for anything three.js or loaders.gl would silently drop,
    which is what makes a wrong BIN chunk type observable from a test.
    """
    if len(raw) < 12:
        raise AssetContractError("glb_truncated", f"{len(raw)} bytes")
    magic, version, declared = struct.unpack("<4sII", raw[:12])
    if magic != b"glTF":
        raise AssetContractError("glb_magic_invalid", repr(magic))
    if version != 2:
        raise AssetContractError("glb_version_unsupported", str(version))
    if declared != len(raw):
        raise AssetContractError("glb_length_mismatch", f"{declared} != {len(raw)}")
    seen: dict[bytes, bytes] = {}
    order: list[bytes] = []
    offset = 12
    while offset + 8 <= len(raw):
        length, kind = struct.unpack("<I4s", raw[offset : offset + 8])
        offset += 8
        if offset + length > len(raw):
            raise AssetContractError("glb_chunk_truncated", repr(kind))
        order.append(kind)
        seen.setdefault(kind, raw[offset : offset + length])
        offset += length
    if not order or order[0] != GLB_JSON_CHUNK:
        raise AssetContractError("glb_json_chunk_missing", repr(order))
    if GLB_BIN_CHUNK not in seen:
        raise AssetContractError("glb_bin_chunk_missing", repr(order))
    document = json.loads(seen[GLB_JSON_CHUNK].decode("utf-8").rstrip(" "))
    return document, seen[GLB_BIN_CHUNK]


def png_bytes(width: int, height: int, scanlines: bytes, color_type: int) -> bytes:
    """Assemble a PNG from already filter-prefixed scanlines."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, 9))
        + chunk(b"IEND", b"")
    )

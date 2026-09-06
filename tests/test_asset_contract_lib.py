"""Negative coverage for the shared archetype-contract helpers.

Each rule in ``scripts/asset_contract_lib.py`` gets a case that fails when the
rule is removed, so a deleted rule cannot pass as a green suite.
"""

from __future__ import annotations

import copy
import json
import struct

import pytest

from scripts.asset_contract_lib import (
    GLB_BIN_CHUNK,
    GLB_JSON_CHUNK,
    AssetContractError,
    catalog_entry,
    file_size_errors,
    filename_errors,
    glb_bytes,
    glb_chunk,
    label_vocabulary_errors,
    load_catalog,
    load_json,
    lod_ratios,
    meta_field_errors,
    parse_glb,
    png_bytes,
    preview_pixels,
    required_filenames,
    triangle_budget_errors,
)


@pytest.fixture
def catalog():
    return load_catalog()


def test_load_json_names_a_missing_file(tmp_path):
    with pytest.raises(AssetContractError) as excinfo:
        load_json(tmp_path / "absent.json", "meta")
    assert excinfo.value.reason == "meta_unavailable"


def test_load_json_names_malformed_content(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(AssetContractError) as excinfo:
        load_json(broken, "meta")
    assert excinfo.value.reason == "meta_malformed"


def test_load_catalog_rejects_a_catalog_without_archetypes(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"contractId": "x"}), encoding="utf-8")
    with pytest.raises(AssetContractError) as excinfo:
        load_catalog(path)
    assert excinfo.value.reason == "catalog_malformed"


def test_catalog_entry_names_an_unknown_archetype(catalog):
    with pytest.raises(AssetContractError) as excinfo:
        catalog_entry(catalog, "not_an_archetype")
    assert excinfo.value.reason == "archetype_not_in_catalog"


def test_lod_ratios_come_from_the_catalog_rule_text(catalog):
    assert lod_ratios(catalog) == (0.40, 0.12)
    drifted = copy.deepcopy(catalog)
    drifted["budgets"]["lodRule"] = "lod1 <= 25% of lod0 triangles, lod2 <= 5%."
    assert lod_ratios(drifted) == (0.25, 0.05)
    unparsed = copy.deepcopy(catalog)
    unparsed["budgets"]["lodRule"] = "keep the chain small"
    with pytest.raises(AssetContractError) as excinfo:
        lod_ratios(unparsed)
    assert excinfo.value.reason == "catalog_lod_rule_unparsed"


def test_triangle_budget_rule_accepts_under_budget_and_rejects_over(catalog):
    ceiling = catalog["budgets"]["perArchetypeTrianglesLod0"]
    assert triangle_budget_errors({"lod0": 12}, catalog) == []
    assert triangle_budget_errors({"lod0": ceiling}, catalog) == []
    assert triangle_budget_errors({"lod0": ceiling // 2}, catalog) == []
    over = triangle_budget_errors({"lod0": ceiling + 1}, catalog)
    assert any("exceeds the contract ceiling" in error for error in over)


def test_triangle_budget_rule_enforces_the_lod_chain(catalog):
    assert (
        triangle_budget_errors({"lod0": 10000, "lod1": 4000, "lod2": 1200}, catalog)
        == []
    )
    errors = triangle_budget_errors(
        {"lod0": 10000, "lod1": 9000, "lod2": 8000}, catalog
    )
    assert any("lod1" in error for error in errors)
    assert any("lod2" in error for error in errors)


def test_triangle_budget_rule_treats_none_as_not_measured(catalog):
    assert (
        triangle_budget_errors({"lod0": None, "lod1": None, "lod2": None}, catalog)
        == []
    )
    assert triangle_budget_errors({"lod0": 12, "lod1": None}, catalog) == []
    assert triangle_budget_errors({"lod0": 0}, catalog) != []


def test_file_size_rule_uses_the_catalog_ceiling(catalog):
    ceiling = catalog["budgets"]["perArchetypeFileBytes"]
    assert file_size_errors(ceiling, catalog, "a.glb") == []
    assert file_size_errors(ceiling + 1, catalog, "a.glb") != []


def test_meta_field_rule_names_every_missing_contract_field(catalog):
    complete = {field: "x" for field in catalog["deliverables"]["metaFields"]}
    assert meta_field_errors(complete, catalog) == []
    del complete["author"]
    assert meta_field_errors(complete, catalog) == [
        "metadata is missing the contract field author"
    ]


def test_filename_rule_requires_the_archetype_id_stem(catalog):
    good = {
        "model_filename": "military_base.glb",
        "preview_filename": "military_base.preview.png",
    }
    assert filename_errors(good, catalog, "military_base") == []
    assert filename_errors(good, catalog, "hospital") != []
    assert (
        filename_errors(
            {**good, "model_filename": "other.glb"}, catalog, "military_base"
        )
        != []
    )


def test_required_filenames_and_preview_pixels_come_from_the_catalog(catalog):
    assert required_filenames(catalog, "hospital") == [
        "hospital.glb",
        "hospital.preview.png",
        "hospital.meta.json",
    ]
    assert preview_pixels(catalog) == catalog["deliverables"]["previewPixels"]


def test_label_vocabulary_rule_rejects_unknown_and_retired_labels(catalog):
    assert (
        label_vocabulary_errors("unavailable", "Catalogue preview only.", catalog) == []
    )
    assert (
        label_vocabulary_errors("hypothetical_x", "Catalogue preview.", catalog) != []
    )
    retired = label_vocabulary_errors(
        "unavailable", "Illustrative catalogue preview.", catalog
    )
    assert any("retires" in error for error in retired)
    assert label_vocabulary_errors("unavailable", "   ", catalog) != []


def test_glb_chunk_pads_json_with_spaces_and_binary_with_zeros():
    assert glb_chunk(GLB_JSON_CHUNK, b"abc")[8:] == b"abc "
    assert glb_chunk(GLB_BIN_CHUNK, b"abc")[8:] == b"abc\x00"
    with pytest.raises(AssetContractError):
        glb_chunk(b"BIN\\x00", b"abc")


def test_parse_glb_round_trips_a_well_formed_container():
    document = {"asset": {"version": "2.0"}}
    raw = glb_bytes(document, b"\x01\x02\x03\x04")
    parsed, binary = parse_glb(raw)
    assert parsed == document
    assert binary == b"\x01\x02\x03\x04"
    assert struct.unpack("<I4s", raw[12:20])[1] == GLB_JSON_CHUNK


def test_parse_glb_rejects_a_binary_chunk_a_loader_would_ignore():
    """The exact defect a truncated b"BIN\\x00" literal produces."""
    document = {"asset": {"version": "2.0"}}
    payload = json.dumps(document, separators=(",", ":")).encode()
    bad_kind = struct.pack("<4s", b"BIN\\x00")  # truncates to b"BIN\\"
    binary = b"\x01\x02\x03\x04"
    body = (
        glb_chunk(GLB_JSON_CHUNK, payload)
        + struct.pack("<I4s", len(binary), bad_kind)
        + binary
    )
    raw = struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body
    with pytest.raises(AssetContractError) as excinfo:
        parse_glb(raw)
    assert excinfo.value.reason == "glb_bin_chunk_missing"


def test_parse_glb_rejects_a_corrupt_header():
    raw = glb_bytes({"asset": {"version": "2.0"}}, b"\x00\x00\x00\x00")
    with pytest.raises(AssetContractError):
        parse_glb(b"XXXX" + raw[4:])
    with pytest.raises(AssetContractError):
        parse_glb(raw[:-4])


def test_png_bytes_writes_a_decodable_image():
    scanlines = b"".join(bytes([0]) + bytes([1, 2, 3] * 4) for _ in range(4))
    raw = png_bytes(4, 4, scanlines, 2)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(raw[16:20], "big") == 4
    assert raw[25] == 2

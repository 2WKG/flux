from __future__ import annotations

import json
import struct

from scripts.build_military_base_asset import build


def test_military_base_builder_emits_contract_bound_delivery(tmp_path):
    metadata = build(tmp_path)
    glb = tmp_path / "military_base.glb"
    preview = tmp_path / "military_base.preview.png"

    assert glb.read_bytes()[:4] == b"glTF"
    assert preview.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert metadata["archetype_id"] == "military_base"
    assert metadata["contract_id"] == "flux:3d-asset-archetypes:v1"
    assert metadata["footprint_m"] == {"length": 200, "width": 160}
    assert metadata["connectors"] == ["MV_FEED"]
    assert metadata["status_material"] == "MAT_STATUS"
    assert json.loads((tmp_path / "military_base.meta.json").read_text()) == metadata


def test_glb_has_neutral_status_material_and_named_feeder_connector(tmp_path):
    build(tmp_path)
    raw = (tmp_path / "military_base.glb").read_bytes()
    _magic, _version, _length = struct.unpack("<4sII", raw[:12])
    json_length, chunk_type = struct.unpack("<I4s", raw[12:20])
    assert chunk_type == b"JSON"
    gltf = json.loads(raw[20 : 20 + json_length])

    assert gltf["materials"][0]["name"] == "MAT_STATUS"
    assert gltf["extras"]["pivot"] == "ground_center"
    assert {node["name"] for node in gltf["nodes"]} >= {
        "military_base",
        "CONN_MV_FEED_0",
    }

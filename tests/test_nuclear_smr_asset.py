from __future__ import annotations

import json
import struct

from scripts.build_nuclear_smr_asset import build


def test_nuclear_builder_produces_contract_bound_delivery(tmp_path):
    metadata = build(tmp_path)
    assert (tmp_path / "nuclear_smr_module.glb").read_bytes()[:4] == b"glTF"
    assert (tmp_path / "nuclear_smr_module.preview.png").read_bytes()[
        :8
    ] == b"\x89PNG\r\n\x1a\n"
    assert metadata["archetype_id"] == "nuclear_smr_module"
    assert metadata["footprint_m"] == {"length": 120, "width": 100}
    assert metadata["connectors"] == ["HV_OUT"]
    assert (
        json.loads((tmp_path / "nuclear_smr_module.meta.json").read_text()) == metadata
    )


def test_nuclear_glb_binds_the_status_slot_and_hv_connector(tmp_path):
    build(tmp_path)
    raw = (tmp_path / "nuclear_smr_module.glb").read_bytes()
    json_length, kind = struct.unpack("<I4s", raw[12:20])
    assert kind == b"JSON"
    document = json.loads(raw[20 : 20 + json_length])
    assert document["extras"]["pivot"] == "ground_center"
    assert document["materials"][0]["name"] == "MAT_STATUS"
    assert "CONN_HV_OUT_0" in {node["name"] for node in document["nodes"]}

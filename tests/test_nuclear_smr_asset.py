from __future__ import annotations

import copy
import json
import struct
from pathlib import Path

import pytest

from scripts.asset_contract_lib import (
    CATALOG_PATH,
    ROOT,
    AssetContractError,
    load_catalog,
    meta_field_errors,
    parse_glb,
)
from scripts.build_nuclear_smr_asset import (
    ARCHETYPE_ID,
    DEFAULT_OUTPUT,
    REQUEST,
    build,
    main,
)

GLB = f"{ARCHETYPE_ID}.glb"
PREVIEW = f"{ARCHETYPE_ID}.preview.png"
META = f"{ARCHETYPE_ID}.meta.json"


def _request() -> dict:
    return json.loads(REQUEST.read_text())


def _write(path: Path, document: dict) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _mutated_request(tmp_path: Path, **changes) -> Path:
    document = _request()
    document["model"].update(changes)
    return _write(tmp_path / "request.json", document)


def _mutated_catalog(tmp_path: Path, mutate) -> Path:
    catalog = json.loads(CATALOG_PATH.read_text())
    entry = next(item for item in catalog["archetypes"] if item["id"] == ARCHETYPE_ID)
    mutate(catalog, entry)
    return _write(tmp_path / "catalog.json", catalog)


def test_nuclear_smr_builder_emits_the_contract_named_delivery(tmp_path):
    metadata = build(tmp_path)

    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([GLB, PREVIEW, META])
    assert (tmp_path / GLB).read_bytes()[:4] == b"glTF"
    assert (tmp_path / PREVIEW).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert metadata["archetype_id"] == ARCHETYPE_ID
    assert metadata["contract_id"] == "flux:3d-asset-archetypes:v1"
    assert metadata["footprint_m"] == _request()["model"]["footprint_m"]
    assert metadata["connectors"] == _request()["model"]["connectors"]
    assert metadata["status_material"] == "MAT_STATUS"
    assert json.loads((tmp_path / META).read_text()) == metadata


def test_metadata_carries_every_field_the_contract_requires(tmp_path):
    assert meta_field_errors(build(tmp_path), load_catalog()) == []


def test_lod_chain_reports_absence_rather_than_a_measured_zero(tmp_path):
    metadata = build(tmp_path)
    assert metadata["triangles_lod0"] == 12
    assert metadata["triangles_lod1"] is None
    assert metadata["triangles_lod2"] is None
    assert "not produced" in metadata["lod_chain_status"]


def test_glb_is_readable_by_a_conformant_loader(tmp_path):
    """A wrong BIN chunk type is ignored by three.js/loaders.gl, so parse it as they do."""
    build(tmp_path)
    raw = (tmp_path / GLB).read_bytes()
    document, binary = parse_glb(raw)

    buffer_view = document["bufferViews"][0]
    positions = binary[
        buffer_view["byteOffset"] : buffer_view["byteOffset"]
        + buffer_view["byteLength"]
    ]
    assert len(binary) == document["buffers"][0]["byteLength"]
    assert "uri" not in document["buffers"][0]
    assert len(positions) == 8 * 3 * 4
    corners = [
        struct.unpack("<fff", positions[index * 12 : index * 12 + 12])
        for index in range(8)
    ]
    assert min(corner[1] for corner in corners) == 0.0


def test_binary_chunk_type_is_the_bytes_the_spec_requires(tmp_path):
    build(tmp_path)
    raw = (tmp_path / GLB).read_bytes()
    json_length = struct.unpack("<I", raw[12:16])[0]
    offset = 12 + 8 + json_length
    length, kind = struct.unpack("<I4s", raw[offset : offset + 8])
    assert kind == b"BIN\x00"
    assert struct.unpack("<I", raw[offset + 4 : offset + 8])[0] == 0x004E4942
    assert length % 4 == 0


def test_geometry_is_derived_from_the_requested_footprint(tmp_path):
    build(tmp_path)
    document, _binary = parse_glb((tmp_path / GLB).read_bytes())
    accessor = document["accessors"][0]
    footprint = _request()["model"]["footprint_m"]
    assert accessor["max"][0] - accessor["min"][0] == pytest.approx(footprint["width"])
    assert accessor["max"][2] - accessor["min"][2] == pytest.approx(footprint["length"])
    assert accessor["min"][1] == 0.0


def test_a_wider_footprint_moves_the_mesh_not_only_the_metadata(tmp_path):
    catalog = _mutated_catalog(
        tmp_path,
        lambda _c, entry: entry.__setitem__(
            "footprint_m", {"length": 300, "width": 240}
        ),
    )
    request = _mutated_request(tmp_path, footprint_m={"length": 300, "width": 240})
    out = tmp_path / "wide"
    metadata = build(out, request, catalog)

    document, _binary = parse_glb((out / GLB).read_bytes())
    accessor = document["accessors"][0]
    assert metadata["footprint_m"] == {"length": 300, "width": 240}
    assert accessor["max"][0] - accessor["min"][0] == pytest.approx(240)
    assert accessor["max"][2] - accessor["min"][2] == pytest.approx(300)


def test_material_ships_neutral_and_bakes_no_status_colour(tmp_path):
    build(tmp_path)
    document, _binary = parse_glb((tmp_path / GLB).read_bytes())
    material = document["materials"][0]
    red, green, blue, _alpha = material["pbrMetallicRoughness"]["baseColorFactor"]
    assert material["name"] == "MAT_STATUS"
    assert red == green == blue
    assert {node["name"] for node in document["nodes"]} == {
        ARCHETYPE_ID,
        "CONN_HV_OUT_0",
    }
    assert document["extras"]["pivot"] == "ground_center"


def test_the_builder_refuses_a_request_that_contradicts_the_catalog(tmp_path):
    with pytest.raises(AssetContractError) as excinfo:
        build(
            tmp_path,
            _mutated_request(tmp_path, footprint_m={"length": 999, "width": 999}),
        )
    assert excinfo.value.reason == "footprint_m_contradicts_catalog"
    assert not list(tmp_path.glob("*.glb"))


def test_the_builder_refuses_catalog_drift_it_did_not_cause(tmp_path):
    catalog = _mutated_catalog(
        tmp_path, lambda _c, entry: entry.__setitem__("connectors", ["HV_IN"])
    )
    with pytest.raises(AssetContractError) as excinfo:
        build(tmp_path / "out", REQUEST, catalog)
    assert excinfo.value.reason == "connectors_contradicts_catalog"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"archetype_id": "wind_turbine"}, "archetype_id_unexpected"),
        ({"contract_id": "flux:3d-asset-archetypes:v999"}, "contract_id_mismatch"),
    ],
)
def test_the_builder_names_each_invalid_request(tmp_path, changes, reason):
    with pytest.raises(AssetContractError) as excinfo:
        build(tmp_path, _mutated_request(tmp_path, **changes))
    assert excinfo.value.reason == reason


def test_a_missing_request_field_is_a_named_error_not_default_geometry(tmp_path):
    document = _request()
    del document["model"]["footprint_m"]
    request = _write(tmp_path / "request.json", document)
    with pytest.raises(AssetContractError) as excinfo:
        build(tmp_path / "out", request)
    assert excinfo.value.reason == "missing_field"
    assert "footprint_m" in excinfo.value.detail
    assert not (tmp_path / "out").exists()


def test_an_unknown_connector_role_is_refused(tmp_path):
    catalog = _mutated_catalog(
        tmp_path, lambda _c, entry: entry.__setitem__("connectors", ["HV_MAGIC"])
    )
    request = _mutated_request(tmp_path, connectors=["HV_MAGIC"])
    with pytest.raises(AssetContractError) as excinfo:
        build(tmp_path / "out", request, catalog)
    assert excinfo.value.reason == "unknown_connector_role"


def test_an_absent_or_malformed_request_is_named_not_traced(tmp_path):
    with pytest.raises(AssetContractError) as excinfo:
        build(tmp_path / "out", tmp_path / "absent.json")
    assert excinfo.value.reason == "request_unavailable"

    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(AssetContractError) as excinfo:
        build(tmp_path / "out", broken)
    assert excinfo.value.reason == "request_malformed"


def test_the_delivery_is_refused_when_it_breaches_the_catalog_budget(tmp_path):
    catalog = _mutated_catalog(
        tmp_path,
        lambda c, _entry: c["budgets"].__setitem__("perArchetypeTrianglesLod0", 6),
    )
    with pytest.raises(AssetContractError) as excinfo:
        build(tmp_path / "out", REQUEST, catalog)
    assert excinfo.value.reason == "delivery_violates_contract"
    assert "exceeds the contract ceiling" in excinfo.value.detail
    assert not (tmp_path / "out").exists()


def test_the_delivery_is_refused_when_it_breaches_the_file_size_budget(tmp_path):
    catalog = _mutated_catalog(
        tmp_path,
        lambda c, _entry: c["budgets"].__setitem__("perArchetypeFileBytes", 16),
    )
    with pytest.raises(AssetContractError) as excinfo:
        build(tmp_path / "out", REQUEST, catalog)
    assert "over the contract ceiling" in excinfo.value.detail


def test_the_build_is_byte_identical_across_runs(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    build(first)
    build(second)
    for name in (GLB, PREVIEW, META):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_the_default_output_never_lands_in_the_repository():
    assert ROOT not in DEFAULT_OUTPUT.parents
    assert not str(DEFAULT_OUTPUT).startswith(str(ROOT))


def test_main_reports_success_and_failure_through_its_exit_code(tmp_path, capsys):
    assert main(["--output", str(tmp_path / "ok")]) == 0
    assert (tmp_path / "ok" / GLB).exists()

    broken = _mutated_request(tmp_path, footprint_m={"length": 1, "width": 1})
    assert main(["--output", str(tmp_path / "bad"), "--request", str(broken)]) == 1
    assert "footprint_m_contradicts_catalog" in capsys.readouterr().err
    assert not (tmp_path / "bad").exists()


def test_the_committed_request_matches_the_shared_catalog():
    """The request is not allowed to hand-copy numbers the catalog no longer holds."""
    catalog = load_catalog()
    entry = next(item for item in catalog["archetypes"] if item["id"] == ARCHETYPE_ID)
    model = _request()["model"]
    for field in ("footprint_m", "connectors", "lod_triangles"):
        assert model[field] == entry[field]
    assert copy.deepcopy(model)["contract_id"] == catalog["contractId"]

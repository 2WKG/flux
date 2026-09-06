import json
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parents[1] / "data/3d/assets/water_treatment_plant"


def _read(name: str) -> dict:
    return json.loads((ASSET_DIR / name).read_text(encoding="utf-8"))


def test_water_treatment_asset_source_matches_the_shared_archetype_contract():
    catalog = json.loads(
        (
            Path(__file__).resolve().parents[1] / "data/3d/asset-archetypes-v1.json"
        ).read_text(encoding="utf-8")
    )
    archetype = next(
        item for item in catalog["archetypes"] if item["id"] == "water_treatment_plant"
    )
    meta = _read("water_treatment_plant.meta.json")

    assert meta["archetype_id"] == archetype["id"]
    assert meta["contract_id"] == catalog["contractId"]
    assert meta["footprint_m"] == archetype["footprint_m"]
    assert meta["triangles"] == archetype["lod_triangles"]
    assert [connector["role"] for connector in meta["connectors"]] == archetype[
        "connectors"
    ]
    assert meta["transform"]["pivot"] == "ground_center"
    assert meta["transform"]["up_axis"] == "Y"
    assert meta["transform"]["forward_axis"] == "-Z"


def test_water_treatment_asset_source_has_neutral_status_slot_and_feeder_connector():
    meta = _read("water_treatment_plant.meta.json")
    scene = _read("water_treatment_plant.scene.json")

    assert meta["material_slots"][0]["name"] == "MAT_STATUS"
    assert meta["material_slots"][0]["runtime_tinted"] is True
    assert {
        node["name"] for node in scene["nodes"] if node["primitive"] == "empty"
    } == {"CONN_MV_FEED_0"}
    assert (ASSET_DIR / meta["export"]["preview_source"]).is_file()
    assert not list(ASSET_DIR.glob("*.glb"))

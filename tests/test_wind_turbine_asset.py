import json
from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parents[1] / "data/3d/assets/wind_turbine"


def test_wind_turbine_asset_matches_shared_contract():
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / "data/3d/asset-archetypes-v1.json").read_text())
    meta = json.loads((ASSET_DIR / "wind_turbine.meta.json").read_text())
    archetype = next(
        item for item in catalog["archetypes"] if item["id"] == meta["archetype_id"]
    )
    assert meta["contract_id"] == catalog["contractId"]
    assert meta["footprint_m"] == archetype["footprint_m"]
    assert meta["triangles"] == archetype["lod_triangles"]
    assert [item["role"] for item in meta["connectors"]] == archetype["connectors"]
    assert meta["material_slots"][0]["name"] == "MAT_STATUS"
    assert (ASSET_DIR / meta["export"]["preview_source"]).is_file()
    assert not list(ASSET_DIR.glob("*.glb"))

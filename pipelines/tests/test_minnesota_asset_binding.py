from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
from shapely.geometry import Polygon

from pipelines.minnesota_asset_binding import (
    AssetBindingError,
    bind_asset,
    bind_city_essentials,
    bind_city_essentials_from_files,
    bind_from_files,
)
from pipelines.minnesota_schema import ensure_minnesota_schema

ROOT = Path(__file__).resolve().parents[2]

CATALOG_PATH = ROOT / "data/3d/asset-archetypes-v1.json"
INVENTORY_PATH = ROOT / "data/sources/minnesota-accepted-artifact-inventory.json"
CITY_ESSENTIALS_REQUEST_PATH = (
    ROOT / "data/3d/requests/minnesota-city-essentials-v1.json"
)

ACCEPTED_ARTIFACT = "mn:scene:coverage:v1"
ACCEPTED_SCENE = "mn:scene:coverage:v1:facility-1"
# Downtown Minneapolis, well inside the state.
MINNEAPOLIS = {"longitude": -93.265, "latitude": 44.977}


def _catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text())


def _inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text())


def _city_essentials_request() -> dict:
    return json.loads(CITY_ESSENTIALS_REQUEST_PATH.read_text())


def _model(archetype_id: str = "transmission_line_segment") -> dict:
    entry = next(e for e in _catalog()["archetypes"] if e["id"] == archetype_id)
    return {
        "archetype_id": entry["id"],
        "contract_id": "flux:3d-asset-archetypes:v1",
        "glb_uri": "assets/transmission_tower.glb",
        "footprint_m": entry["footprint_m"],
        "connectors": entry["connectors"],
        "lod_triangles": entry["lod_triangles"],
    }


def _placement(**overrides) -> dict:
    placement = {
        "scene_id": ACCEPTED_SCENE,
        "source_artifact_id": ACCEPTED_ARTIFACT,
        "coordinates": dict(MINNEAPOLIS),
        "truth_label": "source_backed",
    }
    placement.update(overrides)
    return placement


def _db(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(tmp_path / "mn.duckdb"))
    ensure_minnesota_schema(con)
    return con


def _manifest(
    con: duckdb.DuckDBPyConnection,
    artifact_id: str = ACCEPTED_ARTIFACT,
    availability: str = "available",
) -> None:
    con.execute(
        "INSERT INTO mn_artifact_manifests VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            artifact_id,
            "geography",
            "2.0.0-mn",
            "mn",
            availability,
            "not_applicable",
            "{}",
            "2026-09-05 00:00:00",
            "[]",
            "[]",
            "[]",
        ],
    )


def _score(
    con: duckdb.DuckDBPyConnection,
    regulatory_label: str,
    artifact_id: str = ACCEPTED_ARTIFACT,
) -> None:
    con.execute(
        "INSERT INTO mn_score_results VALUES (?,?,?,?,?,?)",
        [artifact_id, "coverage", 1.0, "count", "{}", regulatory_label],
    )


def _geography(
    con: duckdb.DuckDBPyConnection,
    polygon: Polygon,
    artifact_id: str = ACCEPTED_ARTIFACT,
) -> None:
    con.execute(
        "INSERT INTO mn_geography_artifacts VALUES (?,?,?,?,?,?)",
        [artifact_id, polygon.wkb, None, None, "derived", "source"],
    )


def _bind(con, placement, model=None, inventory=None):
    return bind_asset(
        con, _catalog(), inventory or _inventory(), model or _model(), placement
    )


# --- acceptance is sourced from storage, never from the request ---------------


def test_no_placement_returns_a_visible_non_geographic_preview(tmp_path):
    binding = _bind(_db(tmp_path), None)

    assert binding["render_mode"] == "catalog_preview"
    assert "coordinates" not in binding
    assert binding["material"] == {"slot": "MAT_STATUS", "status_label": "unavailable"}
    assert "not Minnesota infrastructure" in binding["disclosure"]


def test_request_claiming_acceptance_without_a_manifest_row_is_a_preview(tmp_path):
    """The request asserts an accepted Minnesota identity; storage does not."""
    binding = _bind(_db(tmp_path), _placement())

    assert binding["render_mode"] == "catalog_preview"
    assert "coordinates" not in binding
    assert "no mn_artifact_manifests row" in binding["disclosure"]
    assert ACCEPTED_ARTIFACT in binding["disclosure"]


def test_unavailable_manifest_fails_closed_with_a_named_reason(tmp_path):
    con = _db(tmp_path)
    _manifest(con, availability="unavailable")

    binding = _bind(con, _placement())

    assert binding["render_mode"] == "catalog_preview"
    assert "availability 'unavailable'" in binding["disclosure"]


def test_hypothetical_regulatory_label_is_not_placed(tmp_path):
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "hypothetical")

    binding = _bind(con, _placement())

    assert binding["render_mode"] == "catalog_preview"
    assert "regulatory_label 'hypothetical'" in binding["disclosure"]


def test_source_supported_placement_binds_identity_and_shared_material_slot(tmp_path):
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")

    binding = _bind(con, _placement())

    assert binding["render_mode"] == "placed"
    assert binding["scene_id"] == ACCEPTED_SCENE
    assert binding["source_artifact_id"] == ACCEPTED_ARTIFACT
    assert binding["semantic_type"] == "network"
    assert binding["crs"] == "EPSG:4326"
    assert binding["coordinates"] == {**MINNEAPOLIS, "crs": "EPSG:4326"}
    assert binding["material"] == {
        "slot": "MAT_STATUS",
        "status_label": "source_supported",
    }


def test_source_screened_places_with_its_own_status_label(tmp_path):
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_screened")

    binding = _bind(con, _placement())

    assert binding["render_mode"] == "placed"
    assert binding["material"]["status_label"] == "source_screened"


def test_inventory_prohibiting_placement_fails_closed(tmp_path):
    """A real inventory entry whose prohibited_uses forbid point placement."""
    artifact_id = "mn:facility_context:unassigned:2024"
    con = _db(tmp_path)
    _manifest(con, artifact_id=artifact_id)
    _score(con, "source_supported", artifact_id=artifact_id)

    binding = _bind(
        con,
        _placement(
            source_artifact_id=artifact_id, scene_id=f"{artifact_id}:facility-1"
        ),
    )

    assert binding["render_mode"] == "catalog_preview"
    assert "prohibits" in binding["disclosure"]
    assert "placement" in binding["disclosure"]


def test_truth_label_outside_the_inventory_vocabulary_is_rejected(tmp_path):
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")

    # "source_supported" is a regulatory_label, not one of the inventory's
    # truth_labels; the old gate switched on exactly this invented token.
    with pytest.raises(AssetBindingError, match="truth_labels"):
        _bind(con, _placement(truth_label="source_supported"))


# --- scene identity ------------------------------------------------------------


def test_scene_id_must_be_a_string(tmp_path):
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")

    with pytest.raises(AssetBindingError, match="scene_id must be a non-empty string"):
        _bind(con, _placement(scene_id=17))


def test_scene_id_must_be_namespaced_under_its_source_artifact(tmp_path):
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")

    with pytest.raises(AssetBindingError, match="not namespaced under"):
        _bind(con, _placement(scene_id="mn:fictional:substation"))


# --- coordinates ---------------------------------------------------------------


def test_missing_coordinates_object_is_rejected(tmp_path):
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")

    with pytest.raises(AssetBindingError, match="coordinates must be an object"):
        _bind(con, _placement(coordinates=None))


@pytest.mark.parametrize("axis", ["longitude", "latitude"])
def test_boolean_coordinates_are_rejected(tmp_path, axis):
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")

    with pytest.raises(AssetBindingError, match=f"{axis} must be a numeric"):
        _bind(con, _placement(coordinates={**MINNEAPOLIS, axis: True}))


@pytest.mark.parametrize("axis", ["longitude", "latitude"])
def test_non_finite_coordinates_are_rejected(tmp_path, axis):
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")

    with pytest.raises(AssetBindingError, match=f"{axis} must be finite"):
        _bind(con, _placement(coordinates={**MINNEAPOLIS, axis: float("nan")}))


def test_longitude_outside_epsg4326_range_is_rejected(tmp_path):
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")

    with pytest.raises(AssetBindingError, match=r"longitude in \[-180.0, 180.0\]"):
        _bind(con, _placement(coordinates={**MINNEAPOLIS, "longitude": -193.265}))


def test_the_89_probe_latitude_of_minus_97_is_refused(tmp_path):
    """#89's probe: a longitude parked in the latitude field."""
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")

    with pytest.raises(AssetBindingError, match=r"latitude in \[-90.0, 90.0\]"):
        _bind(con, _placement(coordinates={**MINNEAPOLIS, "latitude": -97.0}))


def test_swapped_longitude_and_latitude_are_refused(tmp_path):
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")

    # Every Minnesota longitude is below -89, so a swap always parks an
    # out-of-range value in the latitude field.
    swapped = {
        "longitude": MINNEAPOLIS["latitude"],
        "latitude": MINNEAPOLIS["longitude"],
    }
    with pytest.raises(AssetBindingError, match=r"latitude in \[-90.0, 90.0\]"):
        _bind(con, _placement(coordinates=swapped))


def test_a_valid_point_outside_minnesota_is_refused(tmp_path):
    """Austin, Texas is a valid EPSG:4326 point and still not Minnesota."""
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")

    with pytest.raises(AssetBindingError, match="outside the Minnesota bounding box"):
        _bind(
            con,
            _placement(coordinates={"longitude": -97.74, "latitude": 30.27}),
        )


def test_a_crs_other_than_epsg4326_is_refused(tmp_path):
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")

    with pytest.raises(AssetBindingError, match="must be declared EPSG:4326"):
        _bind(con, _placement(coordinates={**MINNEAPOLIS, "crs": "EPSG:26915"}))


def test_accepted_minnesota_geometry_is_preferred_over_the_bounding_box(tmp_path):
    """With a stored boundary, a bbox-legal point outside it is still refused."""
    con = _db(tmp_path)
    _manifest(con)
    _score(con, "source_supported")
    _geography(
        con, Polygon([(-93.4, 44.9), (-93.1, 44.9), (-93.1, 45.1), (-93.4, 45.1)])
    )

    inside = _bind(con, _placement())
    assert inside["render_mode"] == "placed"

    # Duluth: inside MINNESOTA_BBOX, outside the stored boundary.
    with pytest.raises(AssetBindingError, match="outside the accepted Minnesota"):
        _bind(con, _placement(coordinates={"longitude": -92.1, "latitude": 46.79}))


# --- archetype contract --------------------------------------------------------


def test_import_rejects_metadata_that_does_not_match_its_archetype(tmp_path):
    model = _model()
    model["connectors"] = ["NONE"]
    with pytest.raises(AssetBindingError, match="connectors"):
        _bind(_db(tmp_path), None, model=model)


def test_unknown_archetype_id_is_a_named_error(tmp_path):
    model = _model()
    model["archetype_id"] = "hyperloop_terminal"
    with pytest.raises(
        AssetBindingError, match="unknown archetype: hyperloop_terminal"
    ):
        _bind(_db(tmp_path), None, model=model)


def test_archetype_ids_come_from_the_shared_asset_catalog(tmp_path):
    """Ids are validated against data/3d/asset-archetypes-v1.json itself."""
    catalog_ids = {entry["id"] for entry in _catalog()["archetypes"]}
    assert {
        "transmission_line_segment",
        "substation_transformer_yard",
        "coal_plant_retiring_site",
        "data_center_campus",
    } <= catalog_ids

    binding = _bind(_db(tmp_path), None, model=_model("coal_plant_retiring_site"))
    assert binding["archetype_id"] == "coal_plant_retiring_site"
    assert binding["semantic_type"] == "generation"


# --- file entry point ----------------------------------------------------------


def test_bind_from_files_drives_the_whole_import_end_to_end(tmp_path):
    db_path = tmp_path / "mn.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_minnesota_schema(con)
    _manifest(con)
    _score(con, "source_supported")
    con.close()

    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps({"model": _model(), "placement": _placement()}), encoding="utf-8"
    )

    binding = bind_from_files(CATALOG_PATH, INVENTORY_PATH, request_path, db_path)

    assert binding["render_mode"] == "placed"
    assert binding["scene_id"] == ACCEPTED_SCENE
    assert binding["crs"] == "EPSG:4326"


def test_bind_from_files_previews_when_storage_has_no_manifest(tmp_path):
    db_path = tmp_path / "mn.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_minnesota_schema(con)
    con.close()

    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps({"model": _model(), "placement": _placement()}), encoding="utf-8"
    )

    binding = bind_from_files(CATALOG_PATH, INVENTORY_PATH, request_path, db_path)

    assert binding["render_mode"] == "catalog_preview"
    assert "no mn_artifact_manifests row" in binding["disclosure"]


# --- Gate 6 city-essential pack ------------------------------------------------


def test_city_essentials_request_semantically_binds_all_seven_as_safe_previews(
    tmp_path,
):
    """The committed Gate 6 request is complete but invents no Minnesota place."""
    binding = bind_city_essentials(
        _db(tmp_path), _catalog(), _inventory(), _city_essentials_request()
    )

    assert binding["summary"] == {"total": 7, "placed": 0, "catalog_previews": 7}
    assert [asset["archetype_id"] for asset in binding["assets"]] == [
        "data_center_campus",
        "residential_neighborhood",
        "commercial_buildings",
        "factory_industrial_facility",
        "natural_gas_plant",
        "wind_turbine",
        "solar_array",
    ]
    assert {asset["semantic_type"] for asset in binding["assets"]} == {
        "load",
        "generation",
    }
    assert all(asset["render_mode"] == "catalog_preview" for asset in binding["assets"])
    assert all("coordinates" not in asset for asset in binding["assets"])


def test_city_essentials_request_rejects_a_partial_or_substituted_pack(tmp_path):
    request = _city_essentials_request()
    request["assets"] = request["assets"][:-1]

    with pytest.raises(AssetBindingError, match="exactly the seven Gate 6 archetypes"):
        bind_city_essentials(_db(tmp_path), _catalog(), _inventory(), request)


def test_city_essentials_file_entry_point_uses_the_committed_request(tmp_path):
    db_path = tmp_path / "mn.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_minnesota_schema(con)
    con.close()

    binding = bind_city_essentials_from_files(
        CATALOG_PATH, INVENTORY_PATH, CITY_ESSENTIALS_REQUEST_PATH, db_path
    )

    assert binding["summary"]["total"] == 7
    assert binding["summary"]["catalog_previews"] == 7

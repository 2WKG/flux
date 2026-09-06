import json
from pathlib import Path

from pipelines.minnesota_mille_lacs_physical_inventory import build_artifact
from pipelines.physical_inventory import validate_artifact


def test_mille_lacs_inventory_keeps_native_crs_and_never_creates_connectivity(
    tmp_path: Path,
):
    lines = {
        "geometryType": "esriGeometryPolyline",
        "spatialReference": {"wkid": 103705},
        "features": [
            {
                "attributes": {"OBJECTID": 7, "COMPANY": "Example", "VOLTAGE": 69},
                "geometry": {"paths": [[[500000, 200000], [500100, 200100]]]},
            }
        ],
    }
    substations = {
        "geometryType": "esriGeometryPoint",
        "spatialReference": {"wkid": 103705},
        "features": [
            {
                "attributes": {"OBJECTID": 9, "COMPANY": "Example"},
                "geometry": {"x": 500000, "y": 200000},
            }
        ],
    }
    lines_path, substations_path = (
        tmp_path / "lines.json",
        tmp_path / "substations.json",
    )
    lines_path.write_text(json.dumps(lines))
    substations_path.write_text(json.dumps(substations))
    artifact = build_artifact(
        lines_path=lines_path,
        substations_path=substations_path,
        retrieved_at="2026-09-06T00:00:00+00:00",
    )
    validate_artifact(artifact)
    assert len(artifact["assets"]) == 2
    assert {row["geometry_crs"] for row in artifact["assets"]} == {"ESRI:103705"}
    assert {row["geometry_precision_m"] for row in artifact["assets"]} == {None}
    assert artifact["terminals"] == []
    assert artifact["connectivity_edges"] == []
    assert [row["denominator_count"] for row in artifact["coverage"]] == [1, 1]
    assert all(
        "not countywide or statewide" in row["source_scope"]
        for row in artifact["coverage"]
    )

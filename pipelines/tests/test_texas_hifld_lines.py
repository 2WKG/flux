from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import shape

from pipelines.texas_hifld_lines import _esri_polygon, fetch_texas_lines

FIXTURES = Path(__file__).parent / "fixtures"
TEXAS_BOUNDARY = FIXTURES / "texas-boundary-tigerweb-simplified.geojson"


def _texas_boundary() -> dict:
    return json.loads(TEXAS_BOUNDARY.read_text(encoding="utf-8"))


def _feature(record_id: str | None, *, drop_geometry: bool = False) -> dict:
    properties = {"TYPE": "AC; OVERHEAD", "SUB_1": "UNKNOWN", "SUB_2": "TAP"}
    if record_id is not None:
        properties["ID"] = record_id
    return {
        "type": "Feature",
        "geometry": None
        if drop_geometry
        else {"type": "LineString", "coordinates": [[-100, 30], [-99, 31]]},
        "properties": properties,
    }


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class Session:
    """Stand in for the ArcGIS service; records every request it is given."""

    def __init__(self, object_ids=(7, 8), features=None, page_extra=None):
        self.calls = []
        self.object_ids = list(object_ids)
        self.features = (
            list(features)
            if features is not None
            else [_feature(str(item)) for item in object_ids]
        )
        self.page_extra = page_extra or {}

    def post(self, url, data, timeout):
        self.calls.append(data)
        assert timeout == 60
        if data.get("returnIdsOnly") == "true":
            return Response({"objectIds": self.object_ids})
        assert data["objectIds"].split(",") == [str(i) for i in self.object_ids]
        return Response(
            {
                "type": "FeatureCollection",
                "features": self.features,
                **self.page_extra,
            }
        )


def test_selects_with_the_real_texas_polygon_and_records_partial_without_edges() -> (
    None
):
    session = Session()
    artifact = fetch_texas_lines(_texas_boundary(), session)

    selection, page = session.calls
    assert selection["geometryType"] == "esriGeometryPolygon"
    assert selection["spatialRel"] == "esriSpatialRelIntersects"
    assert selection["inSR"] == "4326"
    geometry = json.loads(selection["geometry"])
    assert geometry["spatialReference"] == {"wkid": 4326}
    # The committed boundary really is Texas, not a bounding box of it.
    boundary = shape(_texas_boundary()["geometry"])
    sent = shape(
        {"type": "Polygon", "coordinates": [ring for ring in geometry["rings"]]}
    )
    assert sent.area == pytest.approx(boundary.area, rel=1e-9)
    assert sent.area < shape(boundary.envelope).area * 0.75

    assert page["outSR"] == "4326"
    assert artifact["assets"][0]["geometry_crs"] == "EPSG:4326"
    assert artifact["assets"][0]["geometry_status"] == "source"
    coverage = artifact["coverage"][0]
    assert coverage["status"] == "partial"
    assert coverage["denominator_count"] is None
    assert coverage["observed_count"] == 2
    assert artifact["terminals"] == []
    assert artifact["connectivity_edges"] == []


def test_sends_clockwise_exterior_rings_and_keeps_multipolygon_parts() -> None:
    # RFC 7946 counter-clockwise exterior with a clockwise hole, two parts.
    multi = {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
                [[1, 1], [1, 2], [2, 2], [2, 1], [1, 1]],
            ],
            [[[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]]],
        ],
    }
    rings = _esri_polygon(multi)["rings"]
    assert len(rings) == 3

    def signed_area(ring):
        return sum(
            (ring[i][0] * ring[i + 1][1]) - (ring[i + 1][0] * ring[i][1])
            for i in range(len(ring) - 1)
        )

    # Esri: clockwise (negative signed area) is an outer ring, counter-clockwise
    # is a hole.  Both parts must survive as outer rings.
    assert [signed_area(ring) < 0 for ring in rings] == [True, False, True]
    assert {tuple(sorted(point[0] for point in ring)) for ring in rings} == {
        (0.0, 0.0, 0.0, 4.0, 4.0),
        (1.0, 1.0, 1.0, 2.0, 2.0),
        (10.0, 10.0, 10.0, 12.0, 12.0),
    }


def test_refuses_a_feature_without_an_id_or_without_geometry() -> None:
    session = Session(object_ids=[7], features=[_feature(None)])
    with pytest.raises(RuntimeError, match="lacks an ID"):
        fetch_texas_lines(_texas_boundary(), session)

    session = Session(object_ids=[7], features=[_feature("7", drop_geometry=True)])
    with pytest.raises(RuntimeError, match="lacks native geometry"):
        fetch_texas_lines(_texas_boundary(), session)


def test_never_turns_sub_1_or_sub_2_labels_into_terminals_or_edges() -> None:
    session = Session()
    artifact = fetch_texas_lines(_texas_boundary(), session)
    assert artifact["terminals"] == []
    assert artifact["connectivity_edges"] == []
    serialised = json.dumps(artifact)
    assert "UNKNOWN" not in serialised
    assert "TAP" not in serialised


def test_refuses_a_page_that_returns_fewer_features_than_were_selected() -> None:
    session = Session(object_ids=[7, 8], features=[_feature("7")])
    with pytest.raises(RuntimeError, match="1 features for 2 selected object ids"):
        fetch_texas_lines(_texas_boundary(), session)


def test_refuses_a_page_the_service_reports_as_truncated() -> None:
    session = Session(page_extra={"exceededTransferLimit": True})
    with pytest.raises(RuntimeError, match="exceededTransferLimit"):
        fetch_texas_lines(_texas_boundary(), session)

from __future__ import annotations

from pipelines.texas_hifld_lines import fetch_texas_lines


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class Session:
    def __init__(self):
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params)
        if params.get("returnIdsOnly") == "true":
            return Response({"objectIds": [7, 8]})
        return Response(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-100, 30], [-99, 31]],
                        },
                        "properties": {"ID": "7", "SUB_1": "UNKNOWN", "SUB_2": "TAP"},
                    }
                ],
            }
        )

    def post(self, url, data, timeout):
        self.calls.append(data)
        if data.get("returnIdsOnly") == "true":
            return Response({"objectIds": [7, 8]})
        return Response(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[-100, 30], [-99, 31]],
                        },
                        "properties": {"ID": "7"},
                    }
                ],
            }
        )


def test_uses_real_polygon_not_bbox_and_records_partial_without_edges():
    session = Session()
    artifact = fetch_texas_lines(
        {
            "type": "Polygon",
            "coordinates": [[[-100, 30], [-99, 30], [-99, 31], [-100, 30]]],
        },
        session,
    )
    first = session.calls[0]
    assert first["geometryType"] == "esriGeometryPolygon"
    assert first["spatialRel"] == "esriSpatialRelIntersects"
    assert '"rings"' in first["geometry"]
    assert '"wkid":4326' in first["geometry"]
    coverage = artifact["coverage"][0]
    assert coverage["status"] == "partial"
    assert coverage["denominator_count"] is None
    assert artifact["connectivity_edges"] == []
    assert artifact["assets"][0]["geometry_status"] == "source"

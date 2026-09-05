"""Fixture-safe static map-layer reads.

The route deliberately exposes only the stable ``buses`` layer.  Scenario and
derived layers have separate ownership; returning a successful empty response
for an unbuilt table would hide a broken hand-off.
"""

from __future__ import annotations

from typing import Any

import duckdb
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from copilot.api import (
    ArtifactRef,
    NotFoundError,
    SuccessEnvelope,
    UnavailableError,
    success,
)
from copilot.api.errors import request_id_of
from copilot.config import Settings

router = APIRouter(prefix="/layers", tags=["layers"])

_CRS_NAME = "EPSG:4326"
_BUS_ATTRIBUTES: dict[str, dict[str, str]] = {
    "bus_id": {"unit": "identifier", "source": "buses.bus_id"},
    "name": {"unit": "label", "source": "buses.name"},
    "kv": {"unit": "kV", "source": "buses.base_kv"},
    "county_fips": {"unit": "FIPS code", "source": "buses.county_fips"},
    "ba_code": {"unit": "balancing-authority code", "source": "buses.ba_code"},
}


class MapLayerData(BaseModel):
    """A GeoJSON layer plus the metadata needed to interpret its properties."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    layer: str
    crs: str
    attributes: dict[str, dict[str, str]]
    feature_collection: dict[str, Any]


def _bus_feature(row: tuple[Any, ...]) -> dict[str, Any]:
    bus_id, name, kv, lon, lat, county_fips, ba_code = row
    return {
        "type": "Feature",
        "id": str(bus_id),
        "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
        "properties": {
            "bus_id": str(bus_id),
            "name": name,
            "kv": kv,
            "county_fips": county_fips,
            "ba_code": ba_code,
        },
    }


def _read_buses(path: str) -> list[dict[str, Any]]:
    """Read only the contract fields needed for map points, in stable order."""
    connection = duckdb.connect(path, read_only=True)
    try:
        rows = connection.execute(
            """
            SELECT bus_id, name, base_kv, lon, lat, county_fips, ba_code
            FROM buses
            WHERE lon IS NOT NULL AND lat IS NOT NULL
            ORDER BY bus_id
            """
        ).fetchall()
    finally:
        connection.close()
    return [_bus_feature(row) for row in rows]


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    # GeoJSON's legacy CRS member is retained intentionally: the contract
    # requires an explicit CRS even though RFC 7946 defaults to WGS 84.
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": _CRS_NAME}},
        "features": features,
    }


@router.get("/{layer_name}", response_model=SuccessEnvelope[MapLayerData])
def get_layer(layer_name: str, request: Request) -> SuccessEnvelope[MapLayerData]:
    """Return a declared-CRS map layer or the shared named failure envelope."""
    if layer_name != "buses":
        raise NotFoundError(f"Unknown map layer '{layer_name}'.")

    settings: Settings = request.app.state.settings
    try:
        features = _read_buses(str(settings.duckdb_path))
    except duckdb.CatalogException as exc:
        raise UnavailableError(
            "The buses map-layer artifact is unavailable.",
            details={"artifact": "buses"},
        ) from exc
    except duckdb.IOException as exc:
        raise UnavailableError(
            "The configured database artifact is unavailable.",
            details={"artifact": "database"},
        ) from exc

    return success(
        MapLayerData(
            layer="buses",
            crs=_CRS_NAME,
            attributes=_BUS_ATTRIBUTES,
            feature_collection=_feature_collection(features),
        ),
        request_id=request_id_of(request),
        artifacts=(
            ArtifactRef(
                artifact_id="buses",
                artifact_version="fixture-read-v1",
                source_kind="fixture",
            ),
        ),
    )

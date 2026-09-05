"""Fixture-safe static map-layer reads: ``GET /layers/{name}``.

Per ``docs/specs/05-copilot.md`` §Layers and ``06-frontend.md`` (``api.ts``
parses GeoJSON with ``response.json()``), a GeoJSON layer is returned as a
bare ``FeatureCollection`` with ``Content-Type: application/geo+json``.  The
collection carries the legacy ``crs`` member (the contract requires an
explicit CRS), plus ``layer``, ``attributes`` (units/sources per property)
and ``provenance`` (read from the artifact's rows) as foreign members.

Only ``buses`` is built here.  Every other documented layer name is a known
target whose artifact has not been produced, so it is an *unavailable*
failure, not a missing route; an undocumented name is ``not_found``.  An
empty or unmappable table is never an empty success.
"""

from __future__ import annotations

from typing import Any, Final

import duckdb
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from copilot.api import NotFoundError, UnavailableError
from copilot.config import Settings
from copilot.routes.contract import BUILT_LAYERS, DOCUMENTED_LAYERS, LayerName

router = APIRouter(prefix="/layers", tags=["layers"])

GEOJSON_MEDIA_TYPE: Final = "application/geo+json"
CRS_NAME: Final = "EPSG:4326"
SYNTHETIC_TOPOLOGY_LABEL: Final = "synthetic (ACTIVSg2000)"
_FIXTURE_PREFIX: Final = "fixture:"
_ACTIVSG_MARKER: Final = "activsg"

BUS_ATTRIBUTES: Final[dict[str, dict[str, str | None]]] = {
    "bus_id": {"unit": None, "kind": "identifier", "source": "buses.bus_id"},
    "name": {"unit": None, "kind": "label", "source": "buses.name"},
    "kv": {"unit": "kV", "kind": "measure", "source": "buses.base_kv"},
    "county_fips": {"unit": None, "kind": "FIPS code", "source": "buses.county_fips"},
    "ba_code": {
        "unit": None,
        "kind": "balancing-authority code",
        "source": "buses.ba_code",
    },
    "coord_source": {
        "unit": None,
        "kind": "coordinate provenance",
        "source": "buses.coord_source",
    },
    "source_name": {
        "unit": None,
        "kind": "row provenance",
        "source": "buses.source_name",
    },
}

# Coordinates are cast in SQL so a non-numeric column is a named conversion
# failure rather than a Python ``float()`` 500.
_BUSES_SQL: Final = """
    SELECT bus_id, name, base_kv, CAST(lon AS DOUBLE), CAST(lat AS DOUBLE),
           county_fips, ba_code, coord_source, source_name, source_ref,
           source_version, fixture_batch_id
    FROM buses
    WHERE lon IS NOT NULL AND lat IS NOT NULL
    ORDER BY bus_id
"""


def _unavailable(
    reason: str, *, artifact: str = "buses", **extra: str
) -> UnavailableError:
    messages = {
        "missing": f"The {artifact} artifact is unavailable.",
        "no_rows": "The buses map-layer artifact has no mappable rows.",
        "schema_mismatch": "The buses artifact does not match the documented contract.",
        "invalid_geometry": "The buses artifact contains coordinates outside EPSG:4326.",
        "provenance_missing": "The buses artifact has rows without provenance.",
        "not_built": f"The '{artifact}' map layer has not been built.",
        "query_failed": "The buses artifact could not be read.",
    }
    return UnavailableError(
        messages[reason], details={"artifact": artifact, "reason": reason, **extra}
    )


def _derive_labels(*fields: str) -> tuple[str | None, str | None]:
    """Explicit rules only: ``fixture:`` prefix, or an ACTIVSg reference."""

    source_name = fields[0]
    if source_name.startswith(_FIXTURE_PREFIX):
        return "fixture", None
    if _ACTIVSG_MARKER in " ".join(fields).casefold():
        return "simulated", SYNTHETIC_TOPOLOGY_LABEL
    return None, None


def _bus_feature(
    row: tuple[Any, ...],
) -> tuple[dict[str, Any], tuple[str, str, str, str | None, str | None]]:
    (
        bus_id,
        name,
        kv,
        lon,
        lat,
        county_fips,
        ba_code,
        coord_source,
        source_name,
        source_ref,
        _source_version,
        fixture_batch_id,
    ) = row
    for label, value in (
        ("coord_source", coord_source),
        ("source_name", source_name),
        ("source_ref", source_ref),
        ("fixture_batch_id", fixture_batch_id),
    ):
        if not isinstance(value, str) or not value:
            raise _unavailable("provenance_missing", bus_id=str(bus_id), column=label)
    if not (-90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0):
        raise _unavailable("invalid_geometry", bus_id=str(bus_id))

    source_kind, topology = _derive_labels(source_name, source_ref, coord_source)
    feature = {
        "type": "Feature",
        "id": str(bus_id),
        "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
        "properties": {
            "bus_id": str(bus_id),
            "name": name,
            "kv": kv,
            "county_fips": county_fips,
            "ba_code": ba_code,
            "coord_source": coord_source,
            "source_name": source_name,
        },
    }
    return feature, (source_name, coord_source, fixture_batch_id, source_kind, topology)


def _read_buses(path: str) -> list[tuple[Any, ...]]:
    try:
        connection = duckdb.connect(path, read_only=True)
    except duckdb.Error as exc:
        raise _unavailable("missing", artifact="database") from exc
    try:
        return connection.execute(_BUSES_SQL).fetchall()
    except duckdb.CatalogException as exc:
        raise _unavailable("missing") from exc
    except duckdb.BinderException as exc:
        raise _unavailable("schema_mismatch") from exc
    except duckdb.ConversionException as exc:
        raise _unavailable("invalid_geometry") from exc
    except duckdb.Error as exc:
        raise _unavailable("query_failed") from exc
    finally:
        connection.close()


def _buses_collection(rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    source_names: set[str] = set()
    coord_sources: set[str] = set()
    batches: set[str] = set()
    kinds: set[str | None] = set()
    topologies: set[str] = set()
    for row in rows:
        feature, (source_name, coord_source, batch, kind, topology) = _bus_feature(row)
        features.append(feature)
        source_names.add(source_name)
        coord_sources.add(coord_source)
        batches.add(batch)
        kinds.add(kind)
        if topology is not None:
            topologies.add(topology)
    return {
        "type": "FeatureCollection",
        # GeoJSON's legacy CRS member is retained intentionally: the contract
        # requires an explicit CRS even though RFC 7946 defaults to WGS 84.
        "crs": {"type": "name", "properties": {"name": CRS_NAME}},
        "layer": "buses",
        "attributes": BUS_ATTRIBUTES,
        "provenance": {
            "source_kinds": sorted(kinds, key=lambda kind: kind or ""),
            "topology": next(iter(topologies)) if len(topologies) == 1 else None,
            "topologies": sorted(topologies),
            "source_names": sorted(source_names),
            "coord_sources": sorted(coord_sources),
            "fixture_batch_ids": sorted(batches),
        },
        "features": features,
    }


@router.get("/{layer_name}")
def get_layer(layer_name: LayerName, request: Request) -> JSONResponse:
    """Return a bare GeoJSON layer or the shared named failure envelope."""

    # Shape is validated by ``LayerName`` (422 invalid_input); this decides
    # documented-vs-not and built-vs-not for a well-formed name.
    if layer_name not in DOCUMENTED_LAYERS:
        raise NotFoundError(
            f"Unknown map layer '{layer_name}'.", details={"layer": layer_name}
        )
    if layer_name not in BUILT_LAYERS:
        raise _unavailable("not_built", artifact=layer_name)

    settings: Settings = request.app.state.settings
    rows = _read_buses(str(settings.duckdb_path))
    if not rows:
        raise _unavailable("no_rows")
    return JSONResponse(content=_buses_collection(rows), media_type=GEOJSON_MEDIA_TYPE)

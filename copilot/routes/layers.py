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

from typing import Annotated, Any, Final

import duckdb
from fastapi import APIRouter, Query, Request
from fastapi import Path as FastAPIPath
from fastapi.responses import JSONResponse

from copilot.api import NotFoundError, UnavailableError
from copilot.config import Settings
from pipelines.labels import SYNTHETIC_TOPOLOGY_LABEL
from pipelines.node_annotations import read_node_annotations

DOCUMENTED_LAYERS: Final = frozenset(
    {
        "buses",
        "lines",
        "gens",
        "counties",
        "critical_loads",
        "outage_risk",
        "cascade",
        "sites",
        "line_upgrades",
        "storm",
        "national_hex",
        "eaglei",
    }
)
BUILT_LAYERS: Final = frozenset({"buses"})
LayerName = Annotated[
    str,
    FastAPIPath(
        min_length=1,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Lowercase documented map-layer identifier.",
    ),
]

router = APIRouter(prefix="/layers", tags=["layers"])

GEOJSON_MEDIA_TYPE: Final = "application/geo+json"
CRS_NAME: Final = "EPSG:4326"
_FIXTURE_PREFIX: Final = "fixture:"
_FIXTURE_SOURCE: Final = "fixture"
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
    if source_name == _FIXTURE_SOURCE or source_name.startswith(_FIXTURE_PREFIX):
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


def _draws_for_hour(
    connection: duckdb.DuckDBPyConnection, scenario_id: str, hour: int
) -> dict[str, float | None]:
    """Return BA scaling factors, with ``None`` for an unavailable hour."""
    rows = connection.execute(
        """
        WITH scenario AS (SELECT ts_start FROM scenarios WHERE scenario_id = ?),
        baseline AS (
          SELECT ba_code, demand_mw FROM ba_load_hourly
          WHERE ts = (SELECT ts_start FROM scenario)
        ), current AS (
          SELECT ba_code, demand_mw FROM ba_load_hourly
          WHERE ts = (SELECT ts_start + (? * INTERVAL '1 hour') FROM scenario)
        )
        SELECT b.ba_code,
               CASE WHEN baseline.demand_mw > 0 AND current.demand_mw IS NOT NULL
                    THEN current.demand_mw / baseline.demand_mw ELSE NULL END
        FROM (SELECT DISTINCT ba_code FROM buses WHERE ba_code IS NOT NULL) AS b
        LEFT JOIN baseline USING (ba_code)
        LEFT JOIN current USING (ba_code)
        """,
        [scenario_id, hour],
    ).fetchall()
    return {
        str(code): None if factor is None else float(factor) for code, factor in rows
    }


def _annotated_buses_collection(
    rows: list[tuple[Any, ...]],
    connection: duckdb.DuckDBPyConnection,
    scenario_id: str,
    hour: int,
) -> dict[str, Any]:
    collection = _buses_collection(rows)
    annotations = {item.bus_id: item for item in read_node_annotations(connection)}
    factors = _draws_for_hour(connection, scenario_id, hour)
    for feature in collection["features"]:
        props = feature["properties"]
        annotation = annotations[int(props["bus_id"])]
        factor = factors.get(annotation.ba_code) if annotation.ba_code else None
        draw_mw = (
            None
            if annotation.nominal_draw_mw is None or factor is None
            else annotation.nominal_draw_mw * factor
        )
        props.update(
            {
                "base_kv": props["kv"],
                "role": annotation.role,
                "topology": annotation.topology,
                "generation_capacity_mw": annotation.generation_capacity_mw,
                "fuel_mix": list(annotation.fuel_mix),
                "nominal_draw_mw": annotation.nominal_draw_mw,
                "draw_mw": draw_mw,
                "draw_status": "available" if draw_mw is not None else "unavailable",
                "county_name": annotation.county_name,
                "critical_loads": list(annotation.critical_loads),
                "field_provenance": {
                    **annotation.field_provenance,
                    "lon": "synthetic",
                    "lat": "synthetic",
                    "base_kv": "synthetic",
                    "draw_mw": "derived" if draw_mw is not None else "unavailable",
                },
            }
        )
    collection["attributes"].update(
        {
            "base_kv": {"unit": "kV", "kind": "measure", "source": "buses.base_kv"},
            "role": {
                "unit": None,
                "kind": "derived classification",
                "source": "gens, loads",
            },
            "topology": {
                "unit": None,
                "kind": "truth label",
                "source": "pipelines.labels.SYNTHETIC_TOPOLOGY_LABEL",
            },
            "generation_capacity_mw": {
                "unit": "MW",
                "kind": "measure",
                "source": "gens.pmax_mw",
            },
            "draw_mw": {
                "unit": "MW",
                "kind": "hour-scaled measure",
                "source": "loads.p_mw_nominal, ba_load_hourly",
            },
            "field_provenance": {
                "unit": None,
                "kind": "truth label",
                "source": "derived adapter",
            },
        }
    )
    collection["scenario_id"] = scenario_id
    collection["hour"] = hour
    return collection


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
def get_layer(
    layer_name: LayerName,
    request: Request,
    scenario_id: str | None = Query(default=None, min_length=1, max_length=128),
    hour: int | None = Query(default=None, ge=0),
) -> JSONResponse:
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
    if (scenario_id is None) != (hour is None):
        raise _unavailable(
            "schema_mismatch", detail="scenario_id and hour must be supplied together"
        )
    rows = _read_buses(str(settings.duckdb_path))
    if not rows:
        raise _unavailable("no_rows")
    if scenario_id is None:
        return JSONResponse(
            content=_buses_collection(rows), media_type=GEOJSON_MEDIA_TYPE
        )
    try:
        connection = duckdb.connect(str(settings.duckdb_path), read_only=True)
        try:
            body = _annotated_buses_collection(rows, connection, scenario_id, hour)
        finally:
            connection.close()
    except duckdb.CatalogException as exc:
        raise _unavailable("missing") from exc
    except duckdb.BinderException as exc:
        raise _unavailable("schema_mismatch") from exc
    except duckdb.Error as exc:
        raise _unavailable("query_failed") from exc
    return JSONResponse(content=body, media_type=GEOJSON_MEDIA_TYPE)

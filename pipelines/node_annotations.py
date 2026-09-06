"""Read-only, deterministic annotations for synthetic-grid bus nodes.

This adapter intentionally derives presentation attributes from the persisted
tables.  It does not write a cache or turn a synthetic electrical model into a
source-backed physical-grid claim.

It lives under the Texas ACTIVSg2000 demo contract (`docs/specs/05-copilot.md`,
`GET /layers/buses`), not the Minnesota one, and every record carries
`topology = SYNTHETIC_TOPOLOGY_LABEL` so a caller that serialises a
`NodeAnnotation` on its own still ships the disclosure.

Two attributes are deliberately **not** labelled `source_backed` even though
their underlying facts are:

* ``county_name`` / ``county_fips`` — the county polygon and its name come from
  TIGER, but the *binding of this bus to that county* is
  ``pipelines.joins.join_bus_county``: a point-in-polygon test on a **synthetic**
  ACTIVSg2000 coordinate with a 30 km nearest-polygon fallback.  The binding is
  therefore ``synthetic``.
* ``critical_loads`` — the facility is source-backed, but ``critical_loads.bus_id``
  is written by ``pipelines.joins.join_critical_loads_to_bus``, a nearest-bus
  proximity match inside the county.  The binding is ``synthetic``, and each
  facility carries the receipt that join already persists in
  ``critical_load_bus_dist`` (``binding_method`` and ``binding_distance_km``)
  so the guess is auditable rather than implied.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pipelines.labels import (
    BINDING_RECEIPT_ABSENT,
    BINDING_RECEIPT_MISSING,
    NODE_ROLES,
    SYNTHETIC_TOPOLOGY_LABEL,
)

__all__ = [
    "NODE_ROLES",
    "SYNTHETIC_TOPOLOGY_LABEL",
    "NodeAnnotation",
    "read_node_annotations",
]


@dataclass(frozen=True)
class NodeAnnotation:
    bus_id: int
    role: str
    generation_capacity_mw: float
    fuel_mix: tuple[str, ...]
    nominal_draw_mw: float | None
    county_name: str | None
    county_fips: str | None
    ba_code: str | None
    critical_loads: tuple[dict[str, Any], ...]
    field_provenance: dict[str, str]
    topology: str = SYNTHETIC_TOPOLOGY_LABEL

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["fuel_mix"] = list(self.fuel_mix)
        value["critical_loads"] = list(self.critical_loads)
        return value


# ``critical_load_bus_dist`` is created by ``pipelines.joins`` rather than by the
# frozen DDL in ``pipelines.db``, so a database whose join step never ran does
# not have it.  That is a real, nameable state: the facilities below then report
# ``binding_method = 'receipt_table_absent'`` instead of a plausible default.
_ABSENT_RECEIPTS = (
    "SELECT NULL::BIGINT AS cl_id, NULL::BIGINT AS bus_id,"
    " NULL::DOUBLE AS distance_km, NULL::TEXT AS match_method WHERE FALSE"
)

# ``loads`` carries ``UNIQUE (bus_id)`` (``pipelines/db.py``), which is what makes
# the un-aggregated ``LEFT JOIN loads USING (bus_id)`` below safe from row
# fan-out.  ``read_node_annotations`` asserts the resulting one-row-per-bus
# invariant, because ``copilot/routes/layers.py`` indexes this list by bus id.
_ANNOTATIONS_SQL = """
WITH generation AS (
    SELECT bus_id, SUM(pmax_mw) AS generation_capacity_mw,
           list_sort(list(DISTINCT fuel)) AS fuel_mix
    FROM gens GROUP BY bus_id
), receipts AS (
    SELECT cl_id, bus_id AS receipt_bus_id, distance_km, match_method
    FROM ({receipts})
), facilities AS (
    SELECT c.bus_id,
           list(
             struct_pack(
               id := c.cl_id,
               name := c.name,
               kind := c.kind,
               bus_id := c.bus_id,
               binding_method := COALESCE(r.match_method, '{receipt_missing}'),
               binding_distance_km := r.distance_km
             )
             ORDER BY c.cl_id
           ) AS critical_loads
    FROM critical_loads AS c
    LEFT JOIN receipts AS r
      ON r.cl_id = c.cl_id AND r.receipt_bus_id = c.bus_id
    WHERE c.bus_id IS NOT NULL GROUP BY c.bus_id
)
SELECT b.bus_id,
       CASE WHEN g.bus_id IS NOT NULL AND l.bus_id IS NOT NULL AND l.p_mw_nominal > 0 THEN 'both'
            WHEN g.bus_id IS NOT NULL THEN 'producer'
            WHEN l.bus_id IS NOT NULL AND l.p_mw_nominal > 0 THEN 'consumer'
            ELSE 'transmission' END AS role,
       COALESCE(g.generation_capacity_mw, 0.0) AS generation_capacity_mw,
       COALESCE(g.fuel_mix, []) AS fuel_mix,
       CASE WHEN l.p_mw_nominal > 0 THEN l.p_mw_nominal ELSE NULL END AS nominal_draw_mw,
       l.bus_id IS NOT NULL AS has_load_record,
       c.name AS county_name, b.county_fips, b.ba_code,
       COALESCE(f.critical_loads, []) AS critical_loads
FROM buses AS b
LEFT JOIN generation AS g USING (bus_id)
LEFT JOIN loads AS l USING (bus_id)
LEFT JOIN counties AS c USING (county_fips)
LEFT JOIN facilities AS f USING (bus_id)
ORDER BY b.bus_id
"""


def _annotations_sql(con: Any) -> str:
    """Bind the receipt source, naming the absent-table state rather than hiding it."""
    present = con.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = 'critical_load_bus_dist'"
    ).fetchone()
    if present is None:
        return _ANNOTATIONS_SQL.format(
            receipts=_ABSENT_RECEIPTS, receipt_missing=BINDING_RECEIPT_ABSENT
        )
    return _ANNOTATIONS_SQL.format(
        receipts="SELECT cl_id, bus_id, distance_km, match_method FROM critical_load_bus_dist",
        receipt_missing=BINDING_RECEIPT_MISSING,
    )


def _county_name_provenance(county_fips: str | None, county_name: str | None) -> str:
    if county_name is not None:
        # TIGER supplies the name; ``join_bus_county`` supplies the binding to
        # this bus from a synthetic coordinate, so the pair is synthetic.
        return "synthetic"
    if county_fips is not None:
        # A FIPS on the bus with no ``counties`` row is a broken foreign key,
        # not an absent source: say so instead of reporting "unavailable".
        return "broken_reference"
    return "unavailable"


def read_node_annotations(con: Any) -> list[NodeAnnotation]:
    """Return all bus annotations in numeric bus-id order, one row per bus.

    The named table reads deliberately let callers surface a schema/artifact
    failure instead of replacing unavailable annotations with guessed values.
    """
    rows = con.execute(_annotations_sql(con)).fetchall()
    annotations = [
        NodeAnnotation(
            bus_id=int(bus_id),
            role=str(role),
            generation_capacity_mw=float(capacity),
            fuel_mix=tuple(fuel_mix),
            nominal_draw_mw=None if nominal_draw is None else float(nominal_draw),
            county_name=county_name,
            county_fips=county_fips,
            ba_code=ba_code,
            critical_loads=tuple(critical_loads),
            field_provenance={
                "role": "derived",
                "topology": "synthetic",
                "generation_capacity_mw": "synthetic",
                "fuel_mix": "synthetic",
                # A bus with a 0 MW ``loads`` row has no draw to report but is
                # not a bus without a load record; the label separates them.
                "nominal_draw_mw": "synthetic" if has_load else "unavailable",
                "county_name": _county_name_provenance(county_fips, county_name),
                "county_fips": "synthetic"
                if county_fips is not None
                else "unavailable",
                "ba_code": "synthetic" if ba_code is not None else "unavailable",
                "critical_loads": "synthetic" if critical_loads else "unavailable",
            },
        )
        for (
            bus_id,
            role,
            capacity,
            fuel_mix,
            nominal_draw,
            has_load,
            county_name,
            county_fips,
            ba_code,
            critical_loads,
        ) in rows
    ]
    bus_ids = {annotation.bus_id for annotation in annotations}
    expected = con.execute("SELECT count(*) FROM buses").fetchone()[0]
    if len(annotations) != expected or len(bus_ids) != expected:
        raise ValueError(
            "node annotations must be one row per bus: "
            f"{len(annotations)} rows / {len(bus_ids)} distinct bus ids for {expected} buses"
        )
    return annotations

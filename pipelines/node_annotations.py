"""Read-only, deterministic annotations for synthetic-grid bus nodes.

This adapter intentionally derives presentation attributes from the persisted
tables.  It does not write a cache or turn a synthetic electrical model into a
source-backed physical-grid claim.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


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

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["fuel_mix"] = list(self.fuel_mix)
        value["critical_loads"] = list(self.critical_loads)
        return value


_ANNOTATIONS_SQL = """
WITH generation AS (
    SELECT bus_id, SUM(pmax_mw) AS generation_capacity_mw,
           list_sort(list(DISTINCT fuel)) AS fuel_mix
    FROM gens GROUP BY bus_id
), facilities AS (
    SELECT bus_id,
           list(
             struct_pack(cl_id := cl_id, name := name, kind := kind)
             ORDER BY cl_id
           ) AS critical_loads
    FROM critical_loads WHERE bus_id IS NOT NULL GROUP BY bus_id
)
SELECT b.bus_id,
       CASE WHEN g.bus_id IS NOT NULL AND l.bus_id IS NOT NULL AND l.p_mw_nominal > 0 THEN 'both'
            WHEN g.bus_id IS NOT NULL THEN 'producer'
            WHEN l.bus_id IS NOT NULL AND l.p_mw_nominal > 0 THEN 'consumer'
            ELSE 'transmission' END AS role,
       COALESCE(g.generation_capacity_mw, 0.0) AS generation_capacity_mw,
       COALESCE(g.fuel_mix, []) AS fuel_mix,
       CASE WHEN l.p_mw_nominal > 0 THEN l.p_mw_nominal ELSE NULL END AS nominal_draw_mw,
       c.name AS county_name, b.county_fips, b.ba_code,
       COALESCE(f.critical_loads, []) AS critical_loads
FROM buses AS b
LEFT JOIN generation AS g USING (bus_id)
LEFT JOIN loads AS l USING (bus_id)
LEFT JOIN counties AS c USING (county_fips)
LEFT JOIN facilities AS f USING (bus_id)
ORDER BY b.bus_id
"""


def read_node_annotations(con: Any) -> list[NodeAnnotation]:
    """Return all bus annotations in numeric bus-id order.

    The named table reads deliberately let callers surface a schema/artifact
    failure instead of replacing unavailable annotations with guessed values.
    """
    rows = con.execute(_ANNOTATIONS_SQL).fetchall()
    return [
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
                "generation_capacity_mw": "synthetic",
                "fuel_mix": "synthetic",
                "nominal_draw_mw": "synthetic",
                "county_name": "source_backed"
                if county_name is not None
                else "unavailable",
                "county_fips": "source_backed"
                if county_fips is not None
                else "unavailable",
                "ba_code": "synthetic" if ba_code is not None else "unavailable",
                "critical_loads": "source_backed" if critical_loads else "unavailable",
            },
        )
        for (
            bus_id,
            role,
            capacity,
            fuel_mix,
            nominal_draw,
            county_name,
            county_fips,
            ba_code,
            critical_loads,
        ) in rows
    ]

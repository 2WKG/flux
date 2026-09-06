"""Test fixtures built through the real persisted contracts, never a shadow schema.

Every database here is created by ``pipelines.db.connect`` (the real
``ensure_schema`` DDL of ``SCHEMA_VERSION`` 2.1.0, with its primary keys,
foreign keys, CHECKs and NOT NULLs) and ``pipelines.minnesota_schema
.ensure_minnesota_schema`` (the ``mn_*`` namespace).  A column rename or
constraint change in either contract therefore fails the suites that use these
builders instead of leaving a hand-typed shadow schema green.

``copilot/test_tools_lines.py`` already stated that rule for the line-upgrade
reader; these helpers extend it to the HTTP read routes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from pipelines.db import connect
from pipelines.minnesota_schema import ensure_minnesota_schema

SHA256 = "a" * 64
PROVENANCE: dict[str, Any] = {
    "source_name": "fixture:site",
    "source_ref": "fixture-score.json",
    "source_version": "v1",
    "source_retrieved_at": datetime(2026, 1, 1),  # noqa: DTZ001 naive TIMESTAMP column
    "fixture_batch_id": "batch-1",
}
COUNTY_FIPS = "27001"
DEFAULT_SCENARIO = "mn_fixture"


def insert(con: duckdb.DuckDBPyConnection, table: str, row: dict[str, Any]) -> None:
    """Insert by named column so column-order drift cannot pass silently."""

    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    con.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", list(row.values())
    )


def site_intervention_id(site_id: int | str, unit_mw: float) -> str:
    """The persisted identity of one site outcome: ``site:<site_id>@<unit_mw>``."""

    return f"site:{site_id}@{int(unit_mw)}"


def _seed_county(con: duckdb.DuckDBPyConnection) -> None:
    insert(
        con,
        "counties",
        {
            "county_fips": COUNTY_FIPS,
            "name": "Fixture County",
            "state": "MN",
            "pop": 1000,
            "geom_wkb": b"\x00",
            **PROVENANCE,
        },
    )


def _seed_buses(con: duckdb.DuckDBPyConnection) -> None:
    for bus_id in (1, 2):
        insert(
            con,
            "buses",
            {
                "bus_id": bus_id,
                "name": f"bus-{bus_id}",
                "base_kv": 230.0,
                "lon": -93.0,
                "lat": 45.0,
                "county_fips": COUNTY_FIPS,
                "ba_code": "MISO",
                "coord_source": "fixture",
                "zone": None,
                "area": None,
                **PROVENANCE,
            },
        )


def add_site_candidate(
    con: duckdb.DuckDBPyConnection,
    *,
    site_id: int = 1,
    source_name: str = "fixture:site",
) -> None:
    insert(
        con,
        "site_candidates",
        {
            "site_id": site_id,
            "name": "fixture site",
            "kind": "coal_retired",
            "lon": -93.0,
            "lat": 45.0,
            "county_fips": COUNTY_FIPS,
            "bus_id": 1,
            "capacity_slot_mw": 300.0,
            "source_site_id": f"site-{site_id}",
            **PROVENANCE,
            "source_name": source_name,
        },
    )


def add_site_score(
    con: duckdb.DuckDBPyConnection,
    *,
    site_id: int = 1,
    scenario_id: str = DEFAULT_SCENARIO,
    unit_mw: float = 300.0,
    safety_flags: tuple[str, ...] = (),
    source_name: str = "fixture:site-score",
) -> None:
    """Insert one persisted site outcome.

    ``model_mode`` and ``limitations_json`` are deliberately absent: the real
    ``site_scores`` contract does not carry them, and the route reads them from
    the artifact manifest (see :func:`add_site_score_manifest`).
    """

    insert(
        con,
        "site_scores",
        {
            "site_id": site_id,
            "scenario_id": scenario_id,
            "unit_mw": unit_mw,
            "safety_score": 10.0,
            "safety_flags_json": json.dumps(list(safety_flags)),
            "grid_value_score": 2.0,
            "lol_reduction_mwh": 3.0,
            "congestion_relief_pct": 4.0,
            "blackstart_reach_mw": 5.0,
            **PROVENANCE,
            "source_name": source_name,
        },
    )


def add_site_score_manifest(
    con: duckdb.DuckDBPyConnection,
    *,
    artifact_id: str = "mn:score:site-1",
    site_id: int = 1,
    scenario_id: str = DEFAULT_SCENARIO,
    unit_mw: float = 300.0,
    model_mode: str = "topology",
    availability: str = "available",
    limitations: tuple[str, ...] = ("fixture limitation",),
    geography_id: str = "mn",
) -> str:
    """Persist the artifact manifest that owns a site outcome's model metadata."""

    identity = {
        "source_identity": {
            "family": "site_score",
            "scenario_id": scenario_id,
            "intervention_id": site_intervention_id(site_id, unit_mw),
        }
    }
    insert(
        con,
        "mn_artifact_manifests",
        {
            "artifact_id": artifact_id,
            "artifact_kind": "score",
            "contract_version": "1.0.0",
            "geography_id": geography_id,
            "availability": availability,
            "model_mode": model_mode,
            "identity_json": json.dumps(identity),
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "assumptions_json": json.dumps([]),
            "limitations_json": json.dumps(list(limitations)),
            "input_artifact_ids_json": json.dumps([]),
        },
    )
    return artifact_id


def persisted_site_database(
    path: Path,
    *,
    site_id: int = 1,
    scenario_id: str = DEFAULT_SCENARIO,
    unit_mw: float = 300.0,
    model_mode: str = "topology",
    availability: str = "available",
    limitations: tuple[str, ...] = ("fixture limitation",),
    safety_flags: tuple[str, ...] = (),
    with_manifest: bool = True,
    site_source_name: str = "fixture:site",
    score_source_name: str = "fixture:site-score",
) -> None:
    """A real-DDL database carrying one qualified persisted site outcome."""

    con = connect(path)
    try:
        ensure_minnesota_schema(con)
        _seed_county(con)
        _seed_buses(con)
        add_site_candidate(con, site_id=site_id, source_name=site_source_name)
        add_site_score(
            con,
            site_id=site_id,
            scenario_id=scenario_id,
            unit_mw=unit_mw,
            safety_flags=safety_flags,
            source_name=score_source_name,
        )
        if with_manifest:
            add_site_score_manifest(
                con,
                site_id=site_id,
                scenario_id=scenario_id,
                unit_mw=unit_mw,
                model_mode=model_mode,
                availability=availability,
                limitations=limitations,
            )
    finally:
        con.close()


def add_line(con: duckdb.DuckDBPyConnection, line_id: int) -> None:
    insert(
        con,
        "lines",
        {
            "line_id": line_id,
            "from_bus": 1,
            "to_bus": 2,
            "circuit": f"c{line_id}",
            "base_kv": 230.0,
            "r_pu": 0.01,
            "x_pu": 0.1,
            "rate_a_mw": 300.0,
            "length_km": 10.0,
            "geom_wkb": None,
            "is_transformer": False,
            **PROVENANCE,
        },
    )


def add_line_ranking(
    con: duckdb.DuckDBPyConnection,
    line_id: int,
    *,
    scenario_id: str = DEFAULT_SCENARIO,
    region: str = "MN",
    score: float = 20.0,
    dlr_cost: float = 1_000_000.0,
    reconductor_cost: float = 2_000_000.0,
    best_tech: str = "dlr",
    congestion_method: str = "exact",
    source_kind: str = "fixture",
) -> None:
    contract = {
        "ranking_version": "v1",
        "contract_version": "1.0.0",
        # Naive on purpose: the column is a naive TIMESTAMP.
        "computed_at": datetime(2026, 1, 1),  # noqa: DTZ001 naive TIMESTAMP column
        "simulation_run_id": None,
        "grid_input_sha256": SHA256,
        "weather_input_sha256": None,
        "cost_params_sha256": SHA256,
        "source_kind": source_kind,
    }
    insert(
        con,
        "line_upgrade_scores",
        {
            "line_id": line_id,
            "scenario_id": scenario_id,
            "congestion_usd_yr": 100.0,
            "dlr_uplift_mw": 20.0,
            "reconductor_uplift_mw": 10.0,
            "dlr_cost_usd": dlr_cost,
            "reconductor_cost_usd": reconductor_cost,
            "mw_per_musd": score,
            "ferc_screen_pass": True,
            "spark_eligible": False,
            **contract,
            **PROVENANCE,
        },
    )
    insert(
        con,
        "line_upgrade_detail",
        {
            "line_id": line_id,
            "scenario_id": scenario_id,
            "static_rating_mw": 400.0,
            "best_tech": best_tech,
            "congestion_method": congestion_method,
            "region": region,
            **contract,
            **PROVENANCE,
        },
    )


def persisted_lines_database(
    path: Path,
    rows: tuple[tuple[int, float, float], ...] = (
        (10, 20.0, 2_000_000.0),
        (11, 20.0, 1_000_000.0),
        (12, 10.0, 1_000_000.0),
    ),
    *,
    scenario_id: str = DEFAULT_SCENARIO,
    region: str = "MN",
) -> None:
    """A real-DDL database carrying a persisted line-upgrade ranking."""

    con = connect(path)
    try:
        _seed_county(con)
        _seed_buses(con)
        for line_id, score, dlr_cost in rows:
            add_line(con, line_id)
            add_line_ranking(
                con,
                line_id,
                scenario_id=scenario_id,
                region=region,
                score=score,
                dlr_cost=dlr_cost,
            )
    finally:
        con.close()

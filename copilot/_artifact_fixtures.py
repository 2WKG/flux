"""Shared DuckDB fixture builders for the persisted-artifact route tests.

Owned here rather than in a test module so that
``copilot/test_predictions.py`` and ``copilot/test_persisted_read_routes.py``
share one definition instead of one reaching into the other's privates.
Every builder writes the real ``pipelines.db`` 2.1.0 DDL plus the
``models.outage.persistence`` companion tables and the
``pipelines.minnesota_schema`` namespace, so the fixtures cannot drift from the
columns the routes read.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

import pipelines.db as pdb
from copilot.app import create_app
from copilot.config import Settings
from models.outage.persistence import ensure_persistence_schema
from pipelines.minnesota_schema import SCHEMA_VERSION, ensure_minnesota_schema

SCENARIO = "mn_winter_2023_snow"
OTHER_SCENARIO = "mn_spring_2024_flood"
FIXTURE_PROVENANCE = (
    "fixture:flux-demo",
    "fixture://minnesota",
    "1.0.0",
    "2026-01-01 00:00:00",
    "fixture:flux-demo@1.0.0",
)
ACTIVSG_PROVENANCE = (
    "twin.cascade",
    "data/raw/activsg2000/scenarios_ACTIVSg2000.m",
    "2018",
    "2026-09-05 12:00:00",
    "activsg2000@2018",
)
UNLABELLED_PROVENANCE = (
    "vendor.export",
    "s3://bucket/export.parquet",
    "1",
    "2026-09-05 12:00:00",
    "vendor@1",
)


def client(path: Path) -> TestClient:
    return TestClient(create_app(Settings(duckdb_path=path)))


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def evaluation_sha(index: int) -> str:
    return f"{index:064x}"


def real_database(path: Path, *, scenarios: tuple[str, ...] = (SCENARIO,)) -> None:
    """Create the shared 2.1.0 contract with the scenarios the fixtures reference."""
    con = pdb.connect(path)
    try:
        for scenario_id in scenarios:
            con.execute(
                "INSERT INTO scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    scenario_id,
                    "Minnesota winter storm",
                    "historical",
                    "2023-01-01 00:00:00",
                    "2023-01-08 00:00:00",
                    *FIXTURE_PROVENANCE,
                ],
            )
    finally:
        con.close()


@dataclass(frozen=True)
class Prediction:
    county_fips: str
    qualified: bool | None = True  # None: heuristic row, no evaluation cited
    scenario_id: str = SCENARIO
    hour: int = 0


def prediction_database(path: Path, rows: tuple[Prediction, ...]) -> None:
    """Persist prediction rows on the real DDL; the routes only read them."""
    scenarios = tuple(dict.fromkeys(row.scenario_id for row in rows)) or (SCENARIO,)
    real_database(path, scenarios=scenarios)
    con = duckdb.connect(str(path))
    try:
        ensure_persistence_schema(con)
        for county in dict.fromkeys(row.county_fips for row in rows):
            con.execute(
                "INSERT INTO counties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [county, f"County {county}", "MN", 1000, b"\x00", *FIXTURE_PROVENANCE],
            )
        for index, row in enumerate(rows):
            ts = f"2023-01-01 {row.hour:02}:00:00"
            con.execute(
                "INSERT INTO outage_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    row.scenario_id,
                    row.county_fips,
                    ts,
                    0.4,
                    100,
                    "ice",
                    *FIXTURE_PROVENANCE,
                ],
            )
            if row.qualified is None:
                con.execute(
                    """INSERT INTO prediction_provenance
                       (scenario_id, county_fips, ts, model_kind, rule_id, rule_version,
                        persisted_at)
                       VALUES (?, ?, ?, 'heuristic', 'rule-1', 'r1', ?)""",
                    [row.scenario_id, row.county_fips, ts, "2026-09-05 00:00:00"],
                )
                continue
            evaluation = evaluation_sha(index)
            con.execute(
                """INSERT INTO evaluation_artifacts VALUES
                   (?, 'ready', ?, ?, ?, 'model-v1', 'holdout-v1', NULL, '{}', '{}',
                    NULL, 'not_applicable', NULL, NULL, ?)""",
                [
                    evaluation,
                    row.qualified,
                    None if row.qualified else "brier_above_acceptance",
                    "a" * 64,
                    "2026-09-05 00:00:00",
                ],
            )
            con.execute(
                """INSERT INTO prediction_provenance
                   (scenario_id, county_fips, ts, model_kind, model_version,
                    artifact_sha256, split_id, feature_set_version, evaluation_sha256,
                    persisted_at)
                   VALUES (?, ?, ?, 'lightgbm', 'model-v1', ?, 'holdout-v1',
                           'features-v1', ?, ?)""",
                [
                    row.scenario_id,
                    row.county_fips,
                    ts,
                    "a" * 64,
                    evaluation,
                    "2026-09-05 00:00:00",
                ],
            )
    finally:
        con.close()


@dataclass(frozen=True)
class Run:
    """One persisted cascade run and the Minnesota artifact that qualifies it."""

    run_id: str
    created_at: str = "2026-09-05 00:00:00"
    hours: tuple[int, ...] = (0,)
    scenario_id: str = SCENARIO
    provenance: tuple[str, str, str | None, str | None, str] = ACTIVSG_PROVENANCE
    # None: a bare cascade row with no Minnesota artifact at all.
    model_mode: str | None = "topology"
    availability: str = "available"
    validation_status: str = "validated"
    with_provenance: bool = True
    limitations: str = '["Fixture topology evidence only."]'
    # Two available topology manifests can cite one ``model_run_id``; the suffix
    # builds that tie without a second cascade_runs row.
    artifact_suffix: str = ""
    artifact_id_override: str | None = None
    cascade_rows: bool = True
    # None: a model result exists exactly when the manifest is available.  Set it
    # explicitly to persist a result for a manifest the route must still refuse,
    # so the WHERE clause that refuses it is the only thing standing in the way.
    with_model_result: bool | None = None

    @property
    def artifact_id(self) -> str:
        if self.artifact_id_override is not None:
            return self.artifact_id_override
        return f"mn:model:{self.run_id}{self.artifact_suffix}"


def cascade_database(path: Path, runs: tuple[Run, ...]) -> None:
    real_database(path)
    con = duckdb.connect(str(path))
    try:
        ensure_minnesota_schema(con)
        for run in runs:
            for hour in run.hours if run.cascade_rows else ():
                con.execute(
                    "INSERT INTO cascade_runs VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)",
                    [
                        run.run_id,
                        run.scenario_id,
                        hour,
                        '[{"element_id": "line-7", "kind": "line", "stage": 1, "cause": "weather"}]',
                        12.5 * (hour + 1),
                        '["27000"]',
                        '["cl-1"]',
                        run.provenance[0],
                        run.provenance[1],
                        run.provenance[2],
                        run.provenance[3],
                        run.provenance[4],
                    ],
                )
            if run.model_mode is None:
                continue
            con.execute(
                "INSERT INTO mn_artifact_manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run.artifact_id,
                    "model_result",
                    SCHEMA_VERSION,
                    "mn",
                    run.availability,
                    run.model_mode,
                    "{}",
                    run.created_at,
                    "[]",
                    run.limitations,
                    "[]",
                ],
            )
            if run.with_provenance:
                con.execute(
                    "INSERT INTO mn_artifact_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        run.artifact_id,
                        0,
                        run.provenance[0],
                        run.provenance[1],
                        run.provenance[2] or "v1",
                        run.provenance[3] or "2026-09-05 00:00:00",
                        "test fixture",
                        run.run_id,
                        "b" * 64,
                        False,
                    ],
                )
            if not (
                run.availability == "available"
                if run.with_model_result is None
                else run.with_model_result
            ):
                continue
            topology = run.model_mode == "topology"
            con.execute(
                "INSERT INTO mn_model_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run.artifact_id,
                    "fixture-cascade",
                    "v1",
                    run.run_id,
                    "a" * 64,
                    run.validation_status,
                    "lost_load_mw",
                    1.0,
                    "MW",
                    None if topology else "regional sum",
                    100.0 if topology else None,
                    "pandapower" if topology else None,
                    "fixture-converter" if topology else None,
                ],
            )
    finally:
        con.close()


def details(response) -> dict[str, str]:  # type: ignore[no-untyped-def]
    body = response.json()
    assert body["status"] in {"unavailable", "error"}
    return body["error"]["details"]


HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)


def registered_routes() -> frozenset[tuple[str, str]]:
    """The live registered ``(METHOD, path)`` surface from the OpenAPI document.

    One definition so the route inventories that pin it cannot drift apart; the
    non-method keys of an OpenAPI path item are filtered out rather than being
    read as phantom operations.
    """
    return frozenset(
        (method.upper(), path)
        for path, operations in create_app().openapi()["paths"].items()
        for method in operations
        if method.lower() in HTTP_METHODS
    )

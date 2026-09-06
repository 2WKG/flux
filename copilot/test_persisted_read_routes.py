"""Regression coverage for persisted artifact reads (2WKG-171).

The routes have no prediction or cascade computation implementation to call:
they must serve the existing DuckDB records through HTTP.  In particular, the
prediction-generation entry points below are tripwired so this HTTP test fails
if a future read route starts calculating a result rather than querying its
persisted artifact.  Cascade has no compute entry point in this codebase; its
read-only connection and unchanged database file are the applicable boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest

from copilot.test_predictions import (
    SCENARIO,
    _cascade_database,
    _client,
    _file_sha256,
    _Prediction,
    _prediction_database,
    _Run,
)
from models.outage import evaluate, prediction_paths


def _compute_must_not_run(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("persisted artifact reads must not invoke computation")


def test_http_persisted_artifact_reads_do_not_compute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both GET routes return seeded DuckDB records without recomputing them."""
    prediction_database = tmp_path / "predictions.duckdb"
    cascade_database = tmp_path / "cascade.duckdb"
    _prediction_database(prediction_database, (_Prediction("27000"),))
    run = _Run("mn_winter_2023_snow-s0-0badf00d")
    _cascade_database(cascade_database, (run,))

    monkeypatch.setattr(prediction_paths, "trained_prediction", _compute_must_not_run)
    monkeypatch.setattr(prediction_paths, "heuristic_prediction", _compute_must_not_run)
    monkeypatch.setattr(evaluate, "evaluate_holdout_predictions", _compute_must_not_run)
    prediction_before = _file_sha256(prediction_database)
    cascade_before = _file_sha256(cascade_database)

    predictions = _client(prediction_database).get(
        "/predictions", params={"scenario_id": SCENARIO}
    )
    cascade = _client(cascade_database).get(
        "/cascade", params={"scenario_id": SCENARIO, "run_id": run.run_id}
    )

    assert predictions.status_code == 200
    assert predictions.json()[0]["county_fips"] == "27000"
    assert predictions.json()[0]["evaluation_sha256"] == "0" * 64
    assert cascade.status_code == 200
    assert cascade.json()["run_id"] == run.run_id
    assert cascade.json()["hours"] == [
        {
            "hour": 0,
            "tripped_element_ids": [
                {"element_id": "line-7", "kind": "line", "stage": 1, "cause": "weather"}
            ],
            "lost_load_mw": 12.5,
            "counties_dark": ["27000"],
            "critical_loads_lost": ["cl-1"],
        }
    ]
    assert _file_sha256(prediction_database) == prediction_before
    assert _file_sha256(cascade_database) == cascade_before

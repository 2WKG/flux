"""Behavioral checks for the concrete nine-tool deployment registry."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import duckdb

from copilot._artifact_fixtures import Prediction, prediction_database, real_database
from copilot.non_interactive_tool_handlers import (
    NonInteractiveToolServices,
    non_interactive_tool_handlers,
)
from copilot.retrieval.chunking import CorpusChunk
from copilot.retrieval.search import SparseIndex
from copilot.tools.schemas import TOOL_REGISTRY, validate_tool_input


def _call(handler, name: str, values: dict[str, object]) -> dict[str, object]:
    result = asyncio.run(handler(validate_tool_input(name, values), {}))
    return dict(result)


def test_registry_has_all_nine_concrete_names() -> None:
    handlers = non_interactive_tool_handlers(
        NonInteractiveToolServices(database_path=Path("missing.duckdb"))
    )

    interactive_names = {"scenario_edit", "cascade", "balance", "redundancy"}
    assert set(handlers) == {
        item.name for item in TOOL_REGISTRY if item.name not in interactive_names
    }
    assert len({id(handler) for handler in handlers.values()}) == len(handlers)


def test_unavailable_reasons_name_the_missing_capability_not_a_generic_stub(
    tmp_path: Path,
) -> None:
    handlers = non_interactive_tool_handlers(
        NonInteractiveToolServices(database_path=tmp_path / "missing.duckdb")
    )
    cases = {
        "predict_outage": {"county_fips": "48453", "scenario_id": "uri_2021"},
        "run_cascade": {
            "element_ids": ["line:1"],
            "scenario_id": "uri_2021",
            "hour": 0,
        },
        "score_site": {"site_id": "site-1", "unit_mw": 300, "scenario_id": "uri_2021"},
        "top_lines": {"region": "ERCOT", "tech": "any"},
        "sql": {"query": "SELECT * FROM mn_scores"},
        "cite": {"query": "nuclear safety"},
        "compare_interventions": {
            "scenario_id": "uri_2021",
            "intervention_ids": ["site:1"],
        },
        "top_critical_elements": {"region": "ERCOT"},
        "causal_query": {"kind": "effect", "treatment": "hardening_saidi"},
    }

    results = {
        name: _call(handlers[name], name, values) for name, values in cases.items()
    }

    assert all(result["status"] == "unavailable" for result in results.values())
    reasons = {
        name: result["unavailable"]["reason"] for name, result in results.items()
    }
    assert "outage prediction database" in reasons["predict_outage"]
    assert "cascade" in reasons["run_cascade"]
    assert "site-score" in reasons["score_site"]
    assert "line-ranking database" in reasons["top_lines"]
    assert "SQL-view registry" in reasons["sql"]
    assert "retrieval index" in reasons["cite"]
    assert "comparison" in reasons["compare_interventions"]
    assert "critical-elements" in reasons["top_critical_elements"]
    assert "causal artifact bindings" in reasons["causal_query"]


def test_cite_executes_against_a_local_sparse_index(tmp_path: Path) -> None:
    del tmp_path
    index = SparseIndex(
        (
            CorpusChunk(
                chunk_id="nrc-100-1",
                document_id="10-cfr-100",
                version="2026-01-01",
                source_uri="https://example.test/10-cfr-100",
                text="Nuclear reactor siting safety evidence.",
                chunk_index=0,
                content_kind="source",
                provenance={"source": "NRC"},
                title="10 CFR Part 100",
                page=1,
            ),
        )
    )
    handlers = non_interactive_tool_handlers(
        NonInteractiveToolServices(
            database_path=Path("missing.duckdb"), retrieval_index=index
        )
    )

    result = _call(handlers["cite"], "cite", {"query": "reactor safety", "k": 1})

    assert result["status"] == "available"
    assert result["hits"][0]["doc"] == "10-cfr-100"
    assert result["provenance"][0]["source_kind"] == "retrieval"


def test_prediction_honors_the_requested_horizon_and_downsamples_the_series(
    tmp_path: Path,
) -> None:
    path = tmp_path / "predictions.duckdb"
    prediction_database(
        path,
        tuple(
            Prediction("48453", scenario_id="uri_2021", hour=hour) for hour in range(25)
        ),
    )
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "UPDATE outage_predictions SET p_out = EXTRACT(hour FROM ts) / 100.0"
        )
        connection.execute(
            """UPDATE outage_predictions SET p_out = 0.24
                 WHERE ts = TIMESTAMP '2023-01-02 00:00:00'"""
        )
    handlers = non_interactive_tool_handlers(
        NonInteractiveToolServices(database_path=path)
    )

    result = _call(
        handlers["predict_outage"],
        "predict_outage",
        {"county_fips": "48453", "scenario_id": "uri_2021", "horizon_h": 25},
    )

    assert result["status"] == "available"
    assert result["peak_p_out"] == 0.24
    assert len(result["series"]) == 24
    assert result["series"][0]["ts"].endswith("00:00:00Z")
    assert result["series"][-1]["ts"].endswith("00:00:00Z")


def test_persisted_cascade_keeps_the_critical_load_evidence(tmp_path: Path) -> None:
    path = tmp_path / "cascade.duckdb"
    real_database(path, scenarios=("uri_2021",))
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """INSERT INTO cascade_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                "run-1",
                "uri_2021",
                0,
                json.dumps(
                    [
                        {
                            "element_id": "line:1",
                            "kind": "line",
                            "stage": 1,
                            "cause": "weather",
                        }
                    ]
                ),
                12.5,
                json.dumps(["27000"]),
                json.dumps(
                    [
                        {
                            "cl_id": "load-1",
                            "kind": "hospital",
                            "name": "Fixture hospital",
                        }
                    ]
                ),
                None,
                "fixture:cascade",
                "fixture://cascade",
                "v1",
                "2026-01-01 00:00:00",
                "fixture-cascade@v1",
            ],
        )
    handlers = non_interactive_tool_handlers(
        NonInteractiveToolServices(database_path=path)
    )

    result = _call(
        handlers["run_cascade"],
        "run_cascade",
        {"element_ids": ["line:1"], "scenario_id": "uri_2021", "hour": 0},
    )

    assert result["status"] == "available"
    assert result["critical_loads_lost"] == [
        {"id": "load-1", "name": "Fixture hospital", "kind": "hospital", "hour_lost": 0}
    ]


def test_executor_output_is_revalidated_before_it_reaches_the_dispatcher(
    tmp_path: Path,
) -> None:
    async def malformed_cascade(_: object) -> dict[str, object]:
        return {"status": "available", "provenance": []}

    handlers = non_interactive_tool_handlers(
        NonInteractiveToolServices(
            database_path=tmp_path / "missing.duckdb",
            cascade_executor=malformed_cascade,
        )
    )

    result = _call(
        handlers["run_cascade"],
        "run_cascade",
        {"element_ids": ["line:1"], "scenario_id": "uri_2021", "hour": 0},
    )

    assert result == {
        "status": "unavailable",
        "provenance": [],
        "unavailable": {
            "code": "invalid_prerequisite",
            "reason": "the local cascade executor did not return a contract-valid result",
            "retryable": False,
        },
    }

"""Actual HTTP contracts for the opt-in interactive simulation router."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType

import pandas as pd
from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.interactive_routes import (
    CascadeRequest,
    ScenarioEditRequest,
    create_interactive_router,
    create_interactive_service,
)


class _Net(dict):
    def __init__(self) -> None:
        super().__init__()
        self.bus = pd.DataFrame(
            {"flux_source_bus_id": [1001, 1004]}, index=[1000, 1003]
        )


def _client(monkeypatch) -> TestClient:
    core = ModuleType("twin.cascade")
    core.immutable_scenario_net = lambda net, ids: net
    core.scenario_identity = lambda ids, scenario, hour, **kwargs: {"scenario_hash": "a" * 16, "element_ids": ids}
    core.feasibility_report = lambda net: {"status": "solved"}
    core.run_cascade = lambda *args, **kwargs: {"run_id": "run", "synthetic": True} if kwargs["write"] is False else None
    core.balance_report = lambda net: {"served_load_mw": 1.0}
    core.redundancy_report = lambda net, ids: [{"bus_id": ids[0], "source_hops": 1}]
    core.rank_candidate_placements = lambda net, ids: [{"bus_id": value} for value in ids]
    core.placement_counterfactual = lambda *args, **kwargs: {"site_bus": kwargs["site_bus"]}
    monkeypatch.setitem(sys.modules, "twin.cascade", core)
    build = ModuleType("twin.build")
    build.cached_base_network = lambda case_path, db_path: _Net()
    monkeypatch.setitem(sys.modules, "twin.build", build)
    settings = Settings(duckdb_path=Path("/tmp/grid.duckdb"), cors_origins=("http://localhost:5173",))
    app = create_app(settings)
    service = create_interactive_service(
        duckdb_path=settings.duckdb_path, case_path=Path("/tmp/case.m")
    )
    app.state.interactive_service = service
    app.include_router(create_interactive_router(service=service))
    return TestClient(app)


def _assert_labels(body):
    assert body["model_fidelity"] == "dc_screening"
    assert body["network_provenance"] == "synthetic_activsg2000"
    assert body["limitations"]


def test_all_ticket_436_routes_are_http_and_nonpersisting(monkeypatch):
    client = _client(monkeypatch)
    edit = client.post("/interactive/scenario/edit", json={"base_scenario_id": "uri_2021", "ops": [{"op": "outage", "element_id": "line:7"}]})
    assert edit.status_code == 200
    edit_hash = edit.json()["data"]["edit_hash"]
    responses = [
        edit,
        client.post("/interactive/cascade", json={"element_ids": ["line:7"], "scenario_id": "uri_2021", "hour": 0, "edit_hash": edit_hash}),
        client.get("/interactive/balance", params={"scope": "edit", "edit_hash": edit_hash}),
        client.get("/interactive/redundancy", params={"bus_id": 1001, "scenario_id": "uri_2021", "hour": 0}),
        client.post("/interactive/siting/search", json={"kind": "synthetic_generation", "unit_mw": 300, "scenario_id": "uri_2021", "n": 1}),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        _assert_labels(response.json())
    assert responses[3].json()["data"]["source_bus_id"] == 1001
    assert responses[3].json()["data"]["pp_bus_index"] == 1000


def test_unknown_or_malformed_edits_fail_explicitly(monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/interactive/balance", params={"scope": "edit", "edit_hash": "a" * 16}).status_code == 404
    assert client.post("/interactive/scenario/edit", json={"base_scenario_id": "uri", "ops": []}).status_code == 422


def test_edit_hash_cannot_be_replayed_with_a_different_seed(monkeypatch):
    client = _client(monkeypatch)
    edit = client.post(
        "/interactive/scenario/edit",
        json={
            "base_scenario_id": "uri",
            "seed": 1,
            "ops": [{"op": "outage", "element_id": "line:7"}],
        },
    )
    replay = client.post(
        "/interactive/cascade",
        json={
            "element_ids": ["line:7"],
            "scenario_id": "uri",
            "hour": 0,
            "seed": 0,
            "edit_hash": edit.json()["data"]["edit_hash"],
        },
    )
    assert replay.status_code == 422
    assert replay.json()["error"]["code"] == "invalid_input"


def test_service_and_router_share_an_immutable_edit_registry(monkeypatch):
    client = _client(monkeypatch)
    service = client.app.state.interactive_service
    edit = asyncio.run(service.scenario_edit(
        ScenarioEditRequest.model_validate({
            "base_scenario_id": "uri", "ops": [{"op": "outage", "element_id": "line:7"}]
        })
    ))
    result = client.post(
        "/interactive/cascade",
        json={
            "element_ids": ["line:7"],
            "scenario_id": "uri",
            "hour": 0,
            "edit_hash": edit["data"]["edit_hash"],
        },
    )
    assert result.status_code == 200
    direct = asyncio.run(service.cascade(
        CascadeRequest.model_validate(
            {"element_ids": ["line:7"], "scenario_id": "uri", "hour": 0, "edit_hash": edit["data"]["edit_hash"]}
        )
    ))
    assert direct["data"]["run_id"] == "run"


def test_core_unavailability_is_never_a_plausible_default(monkeypatch):
    client = _client(monkeypatch)
    class SimulationUnavailableError(Exception): pass
    def unavailable(*args, **kwargs): raise SimulationUnavailableError()
    sys.modules["twin.cascade"].run_cascade = unavailable
    response = client.post("/interactive/cascade", json={"element_ids": ["line:7"], "scenario_id": "uri", "hour": 0})
    assert response.status_code == 503

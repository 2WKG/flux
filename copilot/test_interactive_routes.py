"""HTTP contracts for the mounted, non-persisting interactive routes."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings


def _client(monkeypatch) -> TestClient:
    net = {"synthetic": True}
    build = ModuleType("twin.build")
    build.build_network = lambda path: net
    monkeypatch.setitem(sys.modules, "twin.build", build)

    edits = ModuleType("twin.edits")
    edits.outage = lambda element_id: {"element_id": element_id}
    edits.edit_hash = lambda values: "f" * 16
    monkeypatch.setitem(sys.modules, "twin.edits", edits)

    feasibility = ModuleType("twin.feasibility")
    feasibility.evaluate_feasibility = lambda net, edit: {"status": "valid"}
    monkeypatch.setitem(sys.modules, "twin.feasibility", feasibility)

    cascade = ModuleType("twin.cascade")
    cascade.run_cascade = lambda net, edits: {"lost_load_mw": 2.0}
    monkeypatch.setitem(sys.modules, "twin.cascade", cascade)

    balance = ModuleType("twin.balance")
    balance.balance_report = lambda net, edits=(): {"served_load_mw": 1.0}
    monkeypatch.setitem(sys.modules, "twin.balance", balance)

    redundancy = ModuleType("siting.redundancy")
    redundancy.score_redundancy = lambda net, bus_id, **kwargs: {
        "bus_id": bus_id,
        "score": 75.0,
    }
    monkeypatch.setitem(sys.modules, "siting.redundancy", redundancy)

    search = ModuleType("siting.search")
    search.search_locations = lambda net, **kwargs: [
        {"rank": 1, "candidate_id": "bus-7"}
    ]
    monkeypatch.setitem(sys.modules, "siting.search", search)

    app = create_app(Settings(duckdb_path=Path("/tmp/grid.duckdb")))
    return TestClient(app)


def _assert_envelope(body: dict) -> None:
    assert body["model_fidelity"] == "dc_screening"
    assert body["network_provenance"] == "synthetic_activsg2000"
    assert body["limitations"]


def test_all_ticket_436_routes_are_mounted_at_the_public_root(monkeypatch) -> None:
    client = _client(monkeypatch)
    edit = client.post(
        "/scenario/edit",
        json={
            "base_scenario_id": "interactive",
            "ops": [{"op": "outage", "element_id": "line:7"}],
        },
    )
    assert edit.status_code == 200
    edit_hash = edit.json()["data"]["edit_hash"]
    responses = [
        edit,
        client.post(
            "/cascade",
            json={
                "element_ids": ["line:7"],
                "scenario_id": "interactive",
                "hour": 0,
                "edit_hash": edit_hash,
            },
        ),
        client.get("/balance", params={"scope": "edit", "edit_hash": edit_hash}),
        client.get(
            "/redundancy", params={"bus_id": 7, "scenario_id": "interactive", "hour": 0}
        ),
        client.post(
            "/siting/search",
            json={
                "kind": "synthetic_generation",
                "unit_mw": 300,
                "scenario_id": "interactive",
                "n": 1,
            },
        ),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        _assert_envelope(response.json())
    assert responses[1].json()["data"]["lost_load_mw"] == 2.0
    assert responses[3].json()["data"]["bus_id"] == 7
    assert responses[4].json()["data"]["candidates"][0]["candidate_id"] == "bus-7"
    assert "/interactive/cascade" not in client.get("/openapi.json").json()["paths"]


def test_unknown_and_malformed_edits_fail_explicitly(monkeypatch) -> None:
    client = _client(monkeypatch)
    missing = client.get("/balance", params={"scope": "edit", "edit_hash": "f" * 16})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    malformed = client.post(
        "/scenario/edit", json={"base_scenario_id": "interactive", "ops": []}
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_input"


def test_unapplied_seed_fails_closed(monkeypatch) -> None:
    client = _client(monkeypatch)
    edit = client.post(
        "/scenario/edit",
        json={
            "base_scenario_id": "interactive",
            "seed": 1,
            "ops": [{"op": "outage", "element_id": "line:7"}],
        },
    )
    assert edit.status_code == 422
    assert edit.json()["error"]["code"] == "invalid_input"


def test_missing_core_is_an_explicit_unavailable_error(monkeypatch) -> None:
    client = _client(monkeypatch)

    class SimulationUnavailableError(Exception):
        pass

    def unavailable(path):
        raise SimulationUnavailableError()

    sys.modules["twin.build"].build_network = unavailable
    response = client.post(
        "/cascade",
        json={"element_ids": ["line:7"], "scenario_id": "interactive", "hour": 0},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "unavailable"


def test_unknown_scenario_and_cross_context_edit_reuse_fail_closed(monkeypatch) -> None:
    client = _client(monkeypatch)
    unknown = client.post(
        "/scenario/edit",
        json={
            "base_scenario_id": "no_such_scenario",
            "ops": [{"op": "outage", "element_id": "line:7"}],
        },
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "invalid_input"

    edit = client.post(
        "/scenario/edit",
        json={
            "base_scenario_id": "interactive",
            "ops": [{"op": "outage", "element_id": "line:7"}],
        },
    )
    assert edit.status_code == 200
    edit_hash = edit.json()["data"]["edit_hash"]
    for response in (
        client.post(
            "/cascade",
            json={
                "element_ids": ["line:7"],
                "scenario_id": "interactive",
                "hour": 1,
                "edit_hash": edit_hash,
            },
        ),
        client.get(
            "/balance",
            params={
                "scope": "edit",
                "scenario_id": "interactive",
                "hour": 1,
                "edit_hash": edit_hash,
            },
        ),
        client.get(
            "/redundancy",
            params={"bus_id": 7, "scenario_id": "no_such_scenario"},
        ),
    ):
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "invalid_input"


def test_cascade_carries_a_stable_request_identity(monkeypatch) -> None:
    client = _client(monkeypatch)
    payload = {
        "element_ids": ["line:7"],
        "scenario_id": "interactive",
        "hour": 0,
        "seed": 0,
    }

    first = client.post("/cascade", json=payload)
    second = client.post("/cascade", json=payload)

    assert first.status_code == second.status_code == 200
    cascade_id = first.json()["data"]["cascade_id"]
    assert cascade_id.startswith("cascade-")
    assert cascade_id == second.json()["data"]["cascade_id"]

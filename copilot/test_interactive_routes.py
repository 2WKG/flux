"""HTTP contracts for the mounted, non-persisting interactive routes."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.interactive_routes import INTERACTIVE_LIMITATIONS
from pipelines.labels import SYNTHETIC_TOPOLOGY_LABEL


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
    assert body["network_provenance"] == SYNTHETIC_TOPOLOGY_LABEL
    assert body["limitations"]


def test_all_ticket_436_routes_are_mounted_under_the_interactive_prefix(
    monkeypatch,
) -> None:
    client = _client(monkeypatch)
    edit = client.post(
        "/interactive/scenario/edit",
        json={
            "base_scenario_id": "interactive",
            "ops": [{"op": "outage", "element_id": "line:7"}],
        },
    )
    assert edit.status_code == 200
    edit_hash = edit.json()["edit_hash"]
    responses = [
        edit,
        client.post(
            "/interactive/cascade",
            json={
                "element_ids": ["line:7"],
                "scenario_id": "interactive",
                "hour": 0,
                "edit_hash": edit_hash,
            },
        ),
        client.get(
            "/interactive/balance", params={"scope": "edit", "edit_hash": edit_hash}
        ),
        client.get(
            "/interactive/redundancy",
            params={"bus_id": 7, "scenario_id": "interactive", "hour": 0},
        ),
        client.post(
            "/interactive/siting/search",
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
    assert responses[1].json()["lost_load_mw"] == 2.0
    assert responses[3].json()["bus_id"] == 7
    assert responses[4].json()["candidates"][0]["candidate_id"] == "bus-7"
    paths = client.get("/openapi.json").json()["paths"]
    # D-3: the interactive compute routes live under /interactive so that
    # POST /cascade never shares a path with the persisted read GET /cascade.
    for path in (
        "/interactive/scenario/edit",
        "/interactive/cascade",
        "/interactive/balance",
        "/interactive/redundancy",
        "/interactive/siting/search",
    ):
        assert path in paths, path
    assert "post" not in paths.get("/cascade", {})


def test_unknown_and_malformed_edits_fail_explicitly(monkeypatch) -> None:
    client = _client(monkeypatch)
    missing = client.get(
        "/interactive/balance", params={"scope": "edit", "edit_hash": "f" * 16}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    malformed = client.post(
        "/interactive/scenario/edit",
        json={"base_scenario_id": "interactive", "ops": []},
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_input"


def test_unapplied_seed_fails_closed(monkeypatch) -> None:
    client = _client(monkeypatch)
    edit = client.post(
        "/interactive/scenario/edit",
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
        "/interactive/cascade",
        json={"element_ids": ["line:7"], "scenario_id": "interactive", "hour": 0},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "unavailable"


def test_unknown_scenario_and_cross_context_edit_reuse_fail_closed(monkeypatch) -> None:
    client = _client(monkeypatch)
    unknown = client.post(
        "/interactive/scenario/edit",
        json={
            "base_scenario_id": "no_such_scenario",
            "ops": [{"op": "outage", "element_id": "line:7"}],
        },
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "invalid_input"

    edit = client.post(
        "/interactive/scenario/edit",
        json={
            "base_scenario_id": "interactive",
            "ops": [{"op": "outage", "element_id": "line:7"}],
        },
    )
    assert edit.status_code == 200
    edit_hash = edit.json()["edit_hash"]
    for response in (
        client.post(
            "/interactive/cascade",
            json={
                "element_ids": ["line:7"],
                "scenario_id": "interactive",
                "hour": 1,
                "edit_hash": edit_hash,
            },
        ),
        client.get(
            "/interactive/balance",
            params={
                "scope": "edit",
                "scenario_id": "interactive",
                "hour": 1,
                "edit_hash": edit_hash,
            },
        ),
        client.get(
            "/interactive/redundancy",
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

    first = client.post("/interactive/cascade", json=payload)
    second = client.post("/interactive/cascade", json=payload)

    assert first.status_code == second.status_code == 200
    cascade_id = first.json()["cascade_id"]
    assert cascade_id.startswith("cascade-")
    assert cascade_id == second.json()["cascade_id"]


def test_the_synthetic_disclosure_is_present_verbatim(monkeypatch) -> None:
    """P3: the limitations list is checked by content, not truthiness.

    A truthiness assertion lets the synthetic-topology disclosure vanish while
    the other two limitations keep the list non-empty.
    """

    client = _client(monkeypatch)
    body = client.post(
        "/interactive/scenario/edit",
        json={
            "base_scenario_id": "interactive",
            "ops": [{"op": "outage", "element_id": "line:7"}],
        },
    ).json()
    assert body["limitations"] == list(INTERACTIVE_LIMITATIONS)
    assert any("Synthetic ACTIVSg2000 topology" in item for item in body["limitations"])
    assert any("DC screening excludes" in item for item in body["limitations"])
    assert any("no route writes DuckDB" in item for item in body["limitations"])


def test_success_bodies_are_unwrapped(monkeypatch) -> None:
    """`copilot/api/envelope.py`: only the FAILURE envelope is wrapped."""

    client = _client(monkeypatch)
    body = client.post(
        "/interactive/cascade",
        json={"element_ids": ["line:7"], "scenario_id": "interactive", "hour": 0},
    ).json()
    assert "data" not in body
    assert body["lost_load_mw"] == 2.0
    assert body["network_provenance"] == SYNTHETIC_TOPOLOGY_LABEL


def test_input_bounds_are_enforced_at_the_http_layer(monkeypatch) -> None:
    """P4: a 65-element `ops` or `element_ids` list is a 422, not a run."""

    client = _client(monkeypatch)
    too_many_ops = client.post(
        "/interactive/scenario/edit",
        json={
            "base_scenario_id": "interactive",
            "ops": [
                {"op": "outage", "element_id": f"line:{index}"} for index in range(65)
            ],
        },
    )
    assert too_many_ops.status_code == 422, too_many_ops.text
    assert too_many_ops.json()["error"]["code"] == "invalid_input"

    too_many_elements = client.post(
        "/interactive/cascade",
        json={
            "element_ids": [f"line:{index}" for index in range(65)],
            "scenario_id": "interactive",
            "hour": 0,
        },
    )
    assert too_many_elements.status_code == 422, too_many_elements.text
    assert too_many_elements.json()["error"]["code"] == "invalid_input"

    at_the_bound = client.post(
        "/interactive/scenario/edit",
        json={
            "base_scenario_id": "interactive",
            "ops": [
                {"op": "outage", "element_id": f"line:{index}"} for index in range(64)
            ],
        },
    )
    assert at_the_bound.status_code == 200, at_the_bound.text


def test_every_route_refuses_a_context_it_cannot_apply(monkeypatch) -> None:
    """The base-context guard: a free `hour` is refused, never silently ignored.

    Ported from the closed #261.  The HTTP layer accepts `hour` in 0..8760 for
    schema reasons; only hour 0 of the static interactive scenario exists, so
    every other hour must be a 422 rather than a Texas answer wearing the
    caller's hour.
    """

    client = _client(monkeypatch)
    refusals = [
        client.post(
            "/interactive/scenario/edit",
            json={
                "base_scenario_id": "interactive",
                "hour": 5,
                "ops": [{"op": "outage", "element_id": "line:7"}],
            },
        ),
        client.post(
            "/interactive/cascade",
            json={
                "element_ids": ["line:7"],
                "scenario_id": "interactive",
                "hour": 5,
            },
        ),
        client.get("/interactive/balance", params={"hour": 5}),
        client.get("/interactive/redundancy", params={"bus_id": 7, "hour": 5}),
        client.post(
            "/interactive/siting/search",
            json={
                "kind": "synthetic_generation",
                "unit_mw": 300,
                "scenario_id": "interactive",
                "hour": 5,
                "n": 1,
            },
        ),
    ]
    for response in refusals:
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "invalid_input"


def test_every_route_reports_a_missing_core_as_unavailable(monkeypatch) -> None:
    client = _client(monkeypatch)

    class SimulationUnavailableError(Exception):
        pass

    def unavailable(path):
        raise SimulationUnavailableError()

    sys.modules["twin.build"].build_network = unavailable
    responses = [
        client.post(
            "/interactive/scenario/edit",
            json={
                "base_scenario_id": "interactive",
                "ops": [{"op": "outage", "element_id": "line:7"}],
            },
        ),
        client.post(
            "/interactive/cascade",
            json={"element_ids": ["line:7"], "scenario_id": "interactive", "hour": 0},
        ),
        client.get("/interactive/balance"),
        client.get("/interactive/redundancy", params={"bus_id": 7}),
        client.post(
            "/interactive/siting/search",
            json={
                "kind": "synthetic_generation",
                "unit_mw": 300,
                "scenario_id": "interactive",
                "n": 1,
            },
        ),
    ]
    for response in responses:
        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "unavailable"


def test_siting_search_rejects_invalid_input(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post(
        "/interactive/siting/search",
        json={
            "kind": "not_a_kind",
            "unit_mw": 300,
            "scenario_id": "interactive",
            "n": 1,
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_input"


def test_cascade_with_an_unknown_edit_hash_is_not_found(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post(
        "/interactive/cascade",
        json={
            "element_ids": ["line:7"],
            "scenario_id": "interactive",
            "hour": 0,
            "edit_hash": "a" * 16,
        },
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"

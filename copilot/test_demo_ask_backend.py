"""Real HTTP proof for the injected demo cascade backend and existing ``/ask`` SSE."""

from __future__ import annotations

import json
from gzip import open as gzip_open
from pathlib import Path

from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.demo.ask_backend import CoreCascadeEvidence, DemoAskBackend
from copilot.demo.inventory import PhysicalInventoryReader
from copilot.tools.schemas import ArtifactRef, CascadeData, TrippedElement

ATTEMPT = "demo_cascade_0123456789"


class _ActualRunner:
    """A strict core-shaped test adapter, never a route-level fake response."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def run(
        self, *, element_ids: list[str], scenario_id: str, hour: int
    ) -> CascadeData:
        self.calls.append(
            {"element_ids": element_ids, "scenario_id": scenario_id, "hour": hour}
        )
        return CascadeData(
            status="available",
            provenance=[
                ArtifactRef(
                    artifact_id="tx:synthetic:cascade:fixture",
                    artifact_version="v1",
                    source_kind="simulated",
                    source_ref="twin.tools.run_cascade",
                )
            ],
            run_id="cascade-fixture-1",
            scenario_id="uri_2021",
            hour=4,
            tripped_element_ids=[
                TrippedElement(
                    element_id="line-7", kind="line", stage=1, cause="forced"
                )
            ],
            lost_load_mw=12.5,
            counties_dark=[],
            critical_loads_lost=[],
            steps=1,
        )


class _CoreRunner:
    async def run(
        self, *, element_ids: list[str], scenario_id: str, hour: int
    ) -> CoreCascadeEvidence:
        return CoreCascadeEvidence(
            result={
                "run_id": "actual-core-run",
                "scenario_id": scenario_id,
                "hour": hour,
                "synthetic": True,
                "topology": "synthetic (ACTIVSg2000)",
                "tripped_element_ids": [
                    {
                        "element_id": element_ids[0],
                        "kind": "impedance",
                        "stage": 0,
                        "cause": "forced",
                    }
                ],
                "lost_load_mw": 12.5,
                "counties_dark": [],
                "critical_loads_lost": [],
                "solver": "pandapower.rundcpp",
                "loading_by_element": {},
            },
            provenance=[
                ArtifactRef(
                    artifact_id="tx:synthetic:activsg2000",
                    artifact_version="current",
                    source_kind="simulated",
                    source_ref="case_ACTIVSg2000.m",
                )
            ],
            limitations=("Synthetic topology only.",),
        )


def _events(response) -> list[tuple[str, dict[str, object]]]:
    assert response.headers["content-type"].startswith("text/event-stream")
    result = []
    for block in response.text.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if ": " in line
        )
        if "event" in fields:
            result.append((fields["event"], json.loads(fields["data"])))
    return result


def _client(
    runner: _ActualRunner,
    *,
    jepa_artifact_path: Path | None = None,
    inventory_reader: PhysicalInventoryReader | None = None,
) -> TestClient:
    backend = DemoAskBackend(
        runner,
        **({"jepa_artifact_path": jepa_artifact_path} if jepa_artifact_path else {}),
        **({"inventory_reader": inventory_reader} if inventory_reader else {}),
    )
    return TestClient(
        create_app(Settings(duckdb_path="data/duck/grid.duckdb"), ask_backend=backend)
    )


def _physical_inventory_reader() -> PhysicalInventoryReader:
    return PhysicalInventoryReader(Path("data/artifacts/physical_inventory"))


def _first_tx_asset_id() -> str:
    path = Path("data/artifacts/physical_inventory/tx/physical-inventory-1.1.0.json.gz")
    with gzip_open(path, "rt", encoding="utf-8") as stream:
        release = json.load(stream)
    return str(release["assets"][0]["asset_id"])


def test_inventory_questions_use_the_verified_physical_release_not_cascade() -> None:
    runner = _ActualRunner()
    response = _client(runner, inventory_reader=_physical_inventory_reader()).post(
        "/ask",
        json={
            "attempt_id": ATTEMPT,
            "question": "What energy infrastructure is here?",
            "context": {"region": "texas", "view_mode": "physical_inventory"},
            "history": [],
        },
    )

    events = _events(response)
    assert [event for event, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "text",
        "done",
    ]
    assert runner.calls == []
    assert events[1][1]["tool"] == "physical_inventory"
    result = events[2][1]["result"]
    assert result["region"] == "texas"
    assert result["artifact_id"] == "tx:physical-inventory:1.1.0"
    assert result["artifact_version"] == "1.1.0"
    assert result["asset_count"] == 11_949
    assert result["source_records"]
    assert result["selected_asset"] is None


def test_selected_physical_asset_is_resolved_from_the_verified_release() -> None:
    response = _client(
        _ActualRunner(), inventory_reader=_physical_inventory_reader()
    ).post(
        "/ask",
        json={
            "attempt_id": ATTEMPT,
            "question": "Tell me about this asset.",
            "context": {
                "region": "texas",
                "view_mode": "physical_inventory",
                "selected_physical_asset_id": _first_tx_asset_id(),
            },
            "history": [],
        },
    )

    result = _events(response)[2][1]["result"]
    selected = result["selected_asset"]
    assert selected["asset_id"] == _first_tx_asset_id()
    assert selected["source"]["source_ref"]


def test_inventory_tool_uses_the_same_verified_release_as_the_map_endpoint() -> None:
    client = _client(_ActualRunner(), inventory_reader=_physical_inventory_reader())
    layer = client.get("/api/v1/grid/layers/all?state=tx&version=1.1.0&limit=1")
    answer = client.post(
        "/ask",
        json={
            "attempt_id": ATTEMPT,
            "question": "What source-backed inventory is visible here?",
            "context": {"region": "texas", "view_mode": "physical_inventory"},
            "history": [],
        },
    )

    assert layer.status_code == 200
    result = _events(answer)[2][1]["result"]
    map_release = layer.json()
    assert result["artifact_id"] == map_release["artifact_id"]
    assert result["artifact_version"] == map_release["artifact_version"]
    assert result["release_sha256"] == map_release["release_sha256"]
    assert result["asset_count"] == map_release["page"]["total"]


def test_existing_ask_http_path_runs_a_provenanced_cascade_tool_and_streams_plain_text() -> (
    None
):
    runner = _ActualRunner()
    response = _client(runner).post(
        "/ask",
        json={
            "attempt_id": ATTEMPT,
            "question": "Run the cascade for this line outage.",
            "context": {
                "scenario_id": "uri_2021",
                "hour": 4,
                "selected_element_id": "line-7",
            },
            "history": [],
        },
    )

    assert runner.calls == [
        {"element_ids": ["line-7"], "scenario_id": "uri_2021", "hour": 4}
    ]
    events = _events(response)
    assert [event for event, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "text",
        "done",
    ]
    tool_result = events[2][1]
    assert tool_result["tool"] == "run_cascade"
    assert tool_result["result"]["lost_load_mw"] == 12.5
    # The shared narrator carries provenance beside the tool evidence; its SSE
    # result payload intentionally contains only the evidence fields.
    assert "provenance" not in tool_result["result"]
    assert "12.5" not in events[3][1]["delta"]


def test_existing_ask_http_path_keeps_missing_selection_an_explicit_tool_unavailable() -> (
    None
):
    runner = _ActualRunner()
    response = _client(runner).post(
        "/ask",
        json={
            "attempt_id": ATTEMPT,
            "question": "Run a cascade.",
            "context": {"scenario_id": "uri_2021", "hour": 4},
            "history": [],
        },
    )

    assert runner.calls == []
    events = _events(response)
    assert [event for event, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "error",
    ]
    assert events[2][1]["ok"] is False
    assert events[3][1]["error"]["code"] == "unavailable"


def test_existing_ask_http_path_exposes_jepa_as_an_explicitly_experimental_tool(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "jepa.json"
    artifact.write_text(
        json.dumps(
            {
                "artifact_kind": "experimental_jepa_count_forecast",
                "status": "experimental",
                "model_version": "jepa-count-v1",
                "source": {"sha256": "b" * 64},
                "scope": {"observed_county_fips": ["27053"]},
                "split": {"strategy": "chronological_by_window"},
                "metrics": {"holdout_count_mae": 1.0},
                "forecast": {
                    "county_fips": "27053",
                    "predicted_customers_out": [1],
                    "actual_customers_out": [1],
                },
                "limitations": ["Observed historical count forecast only."],
            }
        ),
        encoding="utf-8",
    )
    response = _client(_ActualRunner(), jepa_artifact_path=artifact).post(
        "/ask",
        json={
            "attempt_id": ATTEMPT,
            "question": "Show the JEPA count forecast.",
            "context": {"region": "minnesota", "county_fips": "27053"},
            "history": [],
        },
    )

    events = _events(response)
    assert [event for event, _ in events] == [
        "lifecycle",
        "tool_call",
        "tool_result",
        "text",
        "done",
    ]
    assert events[1][1]["tool"] == "experimental_forecast"
    assert events[2][1]["result"]["status"] == "experimental"
    assert "not a weather forecast" in events[3][1]["delta"]


def test_existing_ask_http_path_preserves_real_core_event_vocabulary_without_relabelling() -> (
    None
):
    response = _client(_CoreRunner()).post(
        "/ask",
        json={
            "attempt_id": ATTEMPT,
            "question": "Run the cascade.",
            "context": {
                "scenario_id": "uri_2021",
                "hour": 4,
                "selected_element_id": "impedance:1",
            },
            "history": [],
        },
    )

    events = _events(response)
    assert events[1][1]["tool"] == "synthetic_cascade"
    event = events[2][1]["result"]["tripped_element_ids"][0]
    assert event == {
        "element_id": "impedance:1",
        "kind": "impedance",
        "stage": 0,
        "cause": "forced",
    }

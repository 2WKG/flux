from __future__ import annotations

from collections.abc import Mapping

from fastapi.testclient import TestClient

from copilot.app import create_app
from copilot.config import Settings
from copilot.demo.interactive import InteractiveAskBackend, InteractiveEvidence
from copilot.tools.schemas import ArtifactRef


class _Bridge:
    async def execute(
        self, intent: str, payload: Mapping[str, object]
    ) -> InteractiveEvidence:
        return InteractiveEvidence(
            status="available",
            result={"intent": intent, "selected": payload.get("selected_element_id")},
            provenance=(
                ArtifactRef(
                    artifact_id="tx:synthetic:test",
                    artifact_version="v1",
                    source_kind="simulated",
                    source_ref="core",
                ),
            ),
        )


def test_balance_prompt_uses_existing_ask_sse_with_raw_tool_output() -> None:
    client = TestClient(
        create_app(Settings(), ask_backend=InteractiveAskBackend(_Bridge()))
    )
    response = client.post(
        "/ask",
        json={
            "attempt_id": "interactive_0123456789",
            "question": "Check balance for this component",
            "context": {"selected_element_id": "line:973"},
            "history": [],
        },
    )
    assert response.status_code == 200
    assert "event: tool_call" in response.text
    assert '"tool":"balance"' in response.text
    assert '"selected":"line:973"' in response.text


class _CascadeBridge:
    async def execute(
        self, intent: str, payload: Mapping[str, object]
    ) -> InteractiveEvidence:
        return InteractiveEvidence(
            status="available",
            result={
                "scene_action": {
                    "kind": "synthetic_cascade_current",
                    "persisted": False,
                    "timeline": [{"element_id": "line:973", "stage": 0}],
                }
            },
            provenance=(
                ArtifactRef(
                    artifact_id="tx:synthetic:test",
                    artifact_version="v1",
                    source_kind="simulated",
                    source_ref="core",
                ),
            ),
        )


def test_cascade_tool_result_keeps_structured_current_scene_action() -> None:
    client = TestClient(
        create_app(Settings(), ask_backend=InteractiveAskBackend(_CascadeBridge()))
    )
    response = client.post(
        "/ask",
        json={
            "attempt_id": "interactive_0123456789",
            "question": "Run cascade",
            "context": {"selected_element_id": "line:973"},
            "history": [],
        },
    )
    assert response.status_code == 200
    assert '"kind":"synthetic_cascade_current"' in response.text
    assert '"persisted":false' in response.text

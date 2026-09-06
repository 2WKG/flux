import pytest

from pipelines.physical_connectivity import (
    ConnectivityEvidenceError,
    blocked_readiness_receipt,
    normalized_receipt,
)


def _terminals():
    return [
        {"terminal_id": "SUB-A:BUS-1", "source_record_id": "terminal-1"},
        {"terminal_id": "SUB-B:BUS-2", "source_record_id": "terminal-2"},
    ]


def test_authoritative_native_terminal_references_are_normalized_deterministically():
    receipt = normalized_receipt(
        state="MN",
        source_name="authorized test release",
        source_url="https://example.test/release",
        source_version="2026-09",
        assessed_at="2026-09-06T12:00:00Z",
        terminals=reversed(_terminals()),
        edges=[
            {
                "edge_id": "line-7",
                "from_terminal_id": "SUB-A:BUS-1",
                "to_terminal_id": "SUB-B:BUS-2",
                "source_record_id": "line-record-7",
                "circuit_id": "1",
            }
        ],
    )

    assert receipt["status"] == "ready_for_contract_integration"
    assert receipt["accepted_terminal_count"] == 2
    assert receipt["edges"] == [
        {
            "edge_id": "line-7",
            "from_terminal_id": "SUB-A:BUS-1",
            "to_terminal_id": "SUB-B:BUS-2",
            "source_record_id": "line-record-7",
            "circuit_id": "1",
        }
    ]


@pytest.mark.parametrize(
    "edge, message",
    [
        (
            {
                "edge_id": "shape-only",
                "source_record_id": "line-1",
                "geometry": "LINESTRING(...)",
            },
            "from_terminal_id",
        ),
        (
            {
                "edge_id": "unknown-endpoint",
                "from_terminal_id": "SUB-A:BUS-1",
                "to_terminal_id": "nearby-plant",
                "source_record_id": "line-2",
            },
            "absent from this release",
        ),
    ],
)
def test_geometry_or_nearby_context_cannot_reconstruct_connectivity(edge, message):
    with pytest.raises(ConnectivityEvidenceError, match=message):
        normalized_receipt(
            state="TX",
            source_name="public geometry",
            source_url="https://example.test/geometry",
            source_version="v1",
            assessed_at="2026-09-06T12:00:00Z",
            terminals=_terminals(),
            edges=[edge],
        )


def test_blocked_receipt_carries_no_topology_or_coverage_claim():
    receipt = blocked_readiness_receipt(
        state="TX",
        source_name="ERCOT network-model access",
        source_url="https://www.ercot.com/gridinfo/modeling",
        source_version="public access check",
        assessed_at="2026-09-06T12:00:00Z",
        reason="Public materials describe the model, but no authorized release with terminals was obtained.",
    )

    assert receipt["status"] == "blocked"
    assert receipt["accepted_terminal_count"] == receipt["accepted_edge_count"] == 0
    assert "proximity" in receipt["prohibited_inferences"]

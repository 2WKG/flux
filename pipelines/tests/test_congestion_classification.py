"""Classification behavior for every supported congestion input state."""

import pytest

from pipelines.congestion import classify_congestion_input, parse_congestion_inputs
from pipelines.line_upgrade_contracts import (
    CongestionSource,
    ObservedCongestion,
    ProxyCongestion,
    SimulatedCongestion,
    UnattributedCongestion,
    UnavailableReason,
)

SHA = "a" * 64


@pytest.mark.parametrize(
    ("raw", "expected_type", "expected_source"),
    [
        (
            {
                "source": "observed",
                "usd_per_year": 1_250.0,
                "market": "ERCOT SCED",
                "input_sha256": SHA,
                "mapping_confidence": 1.0,
                "mapping_method": "exact",
            },
            ObservedCongestion,
            CongestionSource.OBSERVED,
        ),
        (
            {"source": "simulated", "usd_per_year": 5.0, "run_id": "run-1"},
            SimulatedCongestion,
            CongestionSource.SIMULATED,
        ),
        (
            {
                "source": "proxy",
                "usd_per_year": 4.0,
                "assumed_usd_per_mwh": 20.0,
                "assumption_note": "replay assumption",
            },
            ProxyCongestion,
            CongestionSource.PROXY,
        ),
        (
            {"source": "unattributed", "reason": "no_congestion_input"},
            UnattributedCongestion,
            CongestionSource.UNATTRIBUTED,
        ),
    ],
)
def test_classifies_each_declared_congestion_state(raw, expected_type, expected_source):
    classified = classify_congestion_input(raw)

    assert isinstance(classified, expected_type)
    assert classified.source is expected_source


def test_malformed_declared_input_fails_closed_to_unattributed():
    classified = classify_congestion_input(
        {
            "source": "observed",
            "usd_per_year": 1_250.0,
            "market": "ERCOT SCED",
            "input_sha256": "not-a-sha256",
            "mapping_confidence": 2.0,
            "mapping_method": "approximate",
        }
    )

    assert isinstance(classified, UnattributedCongestion)
    assert classified.source is CongestionSource.UNATTRIBUTED
    assert classified.reason is UnavailableReason.NO_CONGESTION_INPUT


def test_repeated_mixed_inputs_keep_classification_and_caller_order():
    inputs = [
        {
            "source": "observed",
            "usd_per_year": 1_250.0,
            "market": "ERCOT SCED",
            "input_sha256": SHA,
            "mapping_confidence": 1.0,
            "mapping_method": "exact",
        },
        {"source": "simulated", "usd_per_year": 5.0, "run_id": "run-1"},
        {
            "source": "proxy",
            "usd_per_year": 4.0,
            "assumed_usd_per_mwh": 20.0,
            "assumption_note": "replay assumption",
        },
        {"source": "unattributed", "reason": "unmapped_constraint"},
        {"source": "simulated", "usd_per_year": 5.0},
    ]

    first = parse_congestion_inputs(inputs)
    second = parse_congestion_inputs(inputs)

    assert first == second
    assert [item.input_index for item in first] == [0, 1, 2, 3, 4]
    assert [type(item.congestion) for item in first] == [
        ObservedCongestion,
        SimulatedCongestion,
        ProxyCongestion,
        UnattributedCongestion,
        UnattributedCongestion,
    ]
    assert [item.source for item in first] == [
        CongestionSource.OBSERVED,
        CongestionSource.SIMULATED,
        CongestionSource.PROXY,
        CongestionSource.UNATTRIBUTED,
        CongestionSource.UNATTRIBUTED,
    ]

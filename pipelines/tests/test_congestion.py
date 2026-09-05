from pipelines.congestion import classify_congestion_input, parse_congestion_inputs
from pipelines.line_upgrade_contracts import (
    CongestionSource,
    ObservedCongestion,
    UnavailableReason,
)

SHA = "a" * 64


def _observed() -> dict[str, object]:
    return {
        "source": "observed",
        "usd_per_year": 1250.0,
        "market": "ERCOT SCED",
        "input_sha256": SHA,
        "mapping_confidence": 1.0,
        "mapping_method": "exact",
    }


def test_only_complete_explicit_market_provenance_becomes_observed():
    observed = classify_congestion_input(_observed())

    assert isinstance(observed, ObservedCongestion)
    assert observed.source is CongestionSource.OBSERVED

    raw_sced = classify_congestion_input(
        {"Constraint Name": "A-B 345", "Shadow Price": 42.0}
    )
    incomplete_observed = classify_congestion_input(
        {"source": "observed", "usd_per_year": 1250.0, "market": "ERCOT SCED"}
    )

    assert raw_sced.source is CongestionSource.UNATTRIBUTED
    assert incomplete_observed.source is CongestionSource.UNATTRIBUTED
    assert raw_sced.reason is UnavailableReason.NO_CONGESTION_INPUT
    assert incomplete_observed.reason is UnavailableReason.NO_CONGESTION_INPUT


def test_unmapped_and_explicit_unavailable_inputs_remain_explicit():
    unmapped = classify_congestion_input(
        {"source": "observed", "mapping_method": "unmapped", "usd_per_year": 99.0}
    )
    unavailable = classify_congestion_input(
        {"source": "unattributed", "reason": "no_congestion_input"}
    )

    assert unmapped.source is CongestionSource.UNATTRIBUTED
    assert unmapped.reason is UnavailableReason.UNMAPPED_CONSTRAINT
    assert unavailable.source is CongestionSource.UNATTRIBUTED
    assert unavailable.reason is UnavailableReason.NO_CONGESTION_INPUT


def test_repeated_inputs_have_identical_classification_in_input_order():
    inputs = [
        _observed(),
        {"source": "simulated", "usd_per_year": 5.0, "run_id": "run-1"},
        {"source": "proxy", "usd_per_year": 4.0, "assumed_usd_per_mwh": 20.0, "assumption_note": "replay"},
        {"Constraint Name": "unclassified raw row"},
    ]

    first = parse_congestion_inputs(inputs)
    second = parse_congestion_inputs(inputs)

    assert first == second
    assert [item.input_index for item in first] == [0, 1, 2, 3]
    assert [item.source for item in first] == [
        CongestionSource.OBSERVED,
        CongestionSource.SIMULATED,
        CongestionSource.PROXY,
        CongestionSource.UNATTRIBUTED,
    ]

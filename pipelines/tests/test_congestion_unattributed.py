from pipelines.congestion import parse_congestion_inputs
from pipelines.line_upgrade_contracts import (
    CongestionSource,
    UnattributedCongestion,
    UnavailableReason,
)


def test_insufficient_declared_provenance_is_unattributed_with_a_next_action():
    classified = parse_congestion_inputs(
        [
            {
                "source": "observed",
                "usd_per_year": 1_250.0,
                "market": "ERCOT SCED",
                # Missing input_sha256, mapping_confidence, and mapping_method.
            }
        ]
    )[0]

    assert isinstance(classified.congestion, UnattributedCongestion)
    assert classified.source is CongestionSource.UNATTRIBUTED
    assert classified.unavailable_reason is UnavailableReason.NO_CONGESTION_INPUT
    assert classified.is_unavailable is True
    assert classified.required_action == (
        "Provide an explicit source and that source's required provenance fields."
    )

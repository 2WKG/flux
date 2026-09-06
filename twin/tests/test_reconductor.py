import pytest

from pipelines.line_upgrade_contracts import ReconductorIntervention, UnavailableReason
from twin.reconductor import (
    build_reconductor_intervention,
    reconductor_cost_usd,
    reconductor_multiplier,
    reconductor_uplift_mw,
)

COSTS = {
    "138": {"value": 900_000.0, "source": "fixture"},
    "230": {"value": 1_300_000.0, "source": "fixture"},
}


def test_reconductoring_uses_the_specified_multiplier_table():
    assert reconductor_multiplier("ACSR", 795) == 1.8
    assert reconductor_multiplier("ACSR", 954) == 1.6
    assert reconductor_multiplier("ACSS", 795) == 1.2
    assert reconductor_uplift_mw(100.0, "ACSR", 795) == 80.0


def test_reconductoring_cost_includes_sourced_per_mile_cost_and_terminals():
    assert reconductor_cost_usd(1.609344, 230.0, COSTS) == 1_495_000.0


def test_reconductoring_returns_the_shared_scoring_contract():
    intervention = build_reconductor_intervention(
        rate_a_mw=100.0,
        material="ACSR",
        kcmil=795,
        length_km=1.609344,
        base_kv=230.0,
        costs=COSTS,
    )

    assert isinstance(intervention, ReconductorIntervention)
    assert intervention.uplift_mw == 80.0
    assert intervention.cost_usd == 1_495_000.0


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"rate_a_mw": None}, UnavailableReason.NO_RATING),
        ({"material": None}, UnavailableReason.NO_CONDUCTOR),
        ({"costs": {}}, UnavailableReason.COST_UNKNOWN),
    ],
)
def test_missing_prerequisites_return_shared_unavailable_reasons(kwargs, reason):
    inputs = {
        "rate_a_mw": 100.0,
        "material": "ACSR",
        "kcmil": 795,
        "length_km": 1.0,
        "base_kv": 230.0,
        "costs": COSTS,
    }
    inputs.update(kwargs)

    assert build_reconductor_intervention(**inputs) is reason

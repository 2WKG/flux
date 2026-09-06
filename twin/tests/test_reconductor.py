import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from copilot.tools.schemas import Unavailable
from pipelines.line_upgrade_contracts import (
    InterventionType,
    LineKey,
    LineUpgradeProvenance,
    ProxyCongestion,
    ReconductorIntervention,
    ScoredLine,
    StorageProvenance,
    UnavailableReason,
)
from twin.reconductor import (
    MAX_MULTIPLIER,
    ReconductorArtifact,
    UnavailableReconductorArtifact,
    build_reconductor_artifact,
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


# --------------------------------------------------------------------------
# Review follow-ups on #116: line identity, shared envelope, pinned guards,
# hand-computed spec 08 section 4 cases.
# --------------------------------------------------------------------------

KEY = LineKey(line_id=4711, region="ERCOT", scenario_id="uri_2021")
ONE_MILE_KM = 1.609344
FULL_COSTS = {
    **COSTS,
    "345": {"value": 2_000_000.0, "source": "fixture"},
}


def _build(**overrides):
    kwargs = {
        "key": KEY,
        "scenario_id": "uri_2021",
        "rate_a_mw": 100.0,
        "material": "ACSR",
        "kcmil": 795,
        "length_km": ONE_MILE_KM,
        "base_kv": 138.0,
        "costs": FULL_COSTS,
    }
    kwargs.update(overrides)
    return build_reconductor_artifact(**kwargs)


@pytest.mark.parametrize(
    ("material", "kcmil", "expected"),
    [
        ("ACSR", 795, 1.8),  # ACSR <= 795 kcmil
        ("ACSR", 1, 1.8),
        ("ACSR", 796, 1.6),  # larger ACSR
        ("ACSR", 1590, 1.6),
        ("ACSS", None, 1.2),  # already HTLS
        ("ACCC", 1020, 1.2),
        ("acsr", 795, 1.8),  # case and whitespace do not change the class
        ("  accc ", None, 1.2),
    ],
)
def test_multiplier_table_matches_spec_08_section_4(material, kcmil, expected):
    assert reconductor_multiplier(material, kcmil) == expected


def test_multiplier_never_exceeds_the_terminal_equipment_cap():
    for material, kcmil in [
        ("ACSR", 100),
        ("ACSR", 2000),
        ("ACSS", None),
        ("ACCC", None),
    ]:
        m = reconductor_multiplier(material, kcmil)
        assert 1.0 < m <= MAX_MULTIPLIER == 2.0


@pytest.mark.parametrize(
    ("material", "kcmil"),
    [
        ("ACSR", None),  # size unknown: the table branches on size, no guess
        ("ACSR", 0),
        ("ACSR", -795),
        ("ACSR", True),
        ("COPPER", 795),
        ("", 795),
        ("   ", 795),
    ],
)
def test_multiplier_refuses_conductors_outside_the_table(material, kcmil):
    with pytest.raises(ValueError):
        reconductor_multiplier(material, kcmil)


@pytest.mark.parametrize(
    ("rating", "material", "kcmil", "expected"),
    [
        (100.0, "ACSR", 795, 80.0),  # 100 x (1.8 - 1)
        (100.0, "ACSR", 796, 60.0),  # 100 x (1.6 - 1)
        (250.0, "ACSR", 1590, 150.0),  # 250 x 0.6
        (100.0, "ACSS", None, 20.0),  # 100 x (1.2 - 1)
        (37.5, "ACCC", 500, 7.5),  # 37.5 x 0.2
    ],
)
def test_uplift_is_static_rating_times_multiplier_minus_one(
    rating, material, kcmil, expected
):
    assert reconductor_uplift_mw(rating, material, kcmil) == pytest.approx(
        expected, rel=1e-12
    )


@pytest.mark.parametrize(
    "rating", [float("nan"), float("inf"), -float("inf"), 0.0, -5.0, "145", True]
)
def test_uplift_refuses_unusable_ratings(rating):
    with pytest.raises(ValueError):
        reconductor_uplift_mw(rating, "ACSR", 795)


def test_uplift_refuses_non_mw_units():
    with pytest.raises(ValueError):
        reconductor_uplift_mw(100.0, "ACSR", 795, unit="A")


def test_cost_is_per_mile_table_times_length_plus_terminal_share():
    # one mile at 138 kV: 900 k x 1.15
    assert reconductor_cost_usd(ONE_MILE_KM, 138.0, FULL_COSTS) == pytest.approx(
        1_035_000.0, rel=1e-12
    )
    # ten miles at 345 kV: 10 x 2.0 M x 1.15
    assert reconductor_cost_usd(10 * ONE_MILE_KM, 345, FULL_COSTS) == pytest.approx(
        23_000_000.0, rel=1e-12
    )
    # kilometres are converted, not treated as miles: 1 km < 1 mile
    assert reconductor_cost_usd(1.0, 138.0, FULL_COSTS) == pytest.approx(
        1_035_000.0 / ONE_MILE_KM, rel=1e-12
    )


@pytest.mark.parametrize(
    ("length_km", "base_kv", "costs"),
    [
        (ONE_MILE_KM, 500.0, FULL_COSTS),  # voltage not in the table
        (0.0, 138.0, FULL_COSTS),  # zero cost would make mw_per_musd undefined
        (-1.0, 138.0, FULL_COSTS),
        (float("nan"), 138.0, FULL_COSTS),
        (float("inf"), 138.0, FULL_COSTS),
        (None, 138.0, FULL_COSTS),
        (ONE_MILE_KM, None, FULL_COSTS),
        (ONE_MILE_KM, 138.0, {"138": {"value": 0.0, "source": "x"}}),
        (ONE_MILE_KM, 138.0, {"138": {"value": float("nan"), "source": "x"}}),
        (ONE_MILE_KM, 138.0, {"138": {"value": 900_000.0}}),  # no source
        (ONE_MILE_KM, 138.0, {"138": {"value": 900_000.0, "source": " "}}),
        (ONE_MILE_KM, 138.0, {"138": 900_000.0}),  # bare number, no source
        (ONE_MILE_KM, 138.0, {}),
    ],
)
def test_cost_refuses_to_guess(length_km, base_kv, costs):
    with pytest.raises((TypeError, ValueError)):
        reconductor_cost_usd(length_km, base_kv, costs)


def test_ready_artifact_is_masters_intervention_keyed_to_the_line():
    artifact = _build()

    assert isinstance(artifact, ReconductorArtifact)
    assert artifact.key == KEY
    assert artifact.scenario_id == "uri_2021"
    assert artifact.static_rating_mw == 100.0
    assert artifact.multiplier == 1.8
    assert isinstance(artifact.intervention, ReconductorIntervention)
    assert artifact.intervention.intervention is InterventionType.RECONDUCTOR
    assert artifact.intervention.uplift_mw == pytest.approx(80.0, rel=1e-12)
    assert artifact.intervention.cost_usd == pytest.approx(1_035_000.0, rel=1e-12)
    assert artifact.intervention.conductor_material == "ACSR"
    assert artifact.intervention.conductor_kcmil == 795


def test_conductor_material_is_persisted_as_the_class_the_multiplier_used():
    artifact = _build(material="  acsr ")
    assert isinstance(artifact, ReconductorArtifact)
    assert artifact.intervention.conductor_material == "ACSR"
    intervention = build_reconductor_intervention(
        rate_a_mw=100.0,
        material="accc",
        kcmil=None,
        length_km=ONE_MILE_KM,
        base_kv=138.0,
        costs=FULL_COSTS,
    )
    assert isinstance(intervention, ReconductorIntervention)
    assert intervention.conductor_material == "ACCC"


def test_ready_artifact_feeds_scored_line_and_line_upgrade_rows():
    artifact = _build()
    storage = StorageProvenance(
        source_name="test", source_ref="test", fixture_batch_id="test"
    )
    scored = ScoredLine(
        key=artifact.key,
        provenance=LineUpgradeProvenance(
            ranking_version="test",
            computed_at=datetime(2026, 1, 1, tzinfo=UTC),
            grid_input_sha256="0" * 64,
            cost_params_sha256="1" * 64,
        ),
        congestion=ProxyCongestion(
            usd_per_year=1.0, assumed_usd_per_mwh=20.0, assumption_note="test"
        ),
        best=artifact.intervention,
        static_rating_mw=artifact.static_rating_mw,
        mw_per_musd=round(80.0 / (1_035_000.0 / 1e6), 3),
    )

    row = scored.to_score_row(storage)
    assert row["line_id"] == 4711
    assert row["reconductor_uplift_mw"] == pytest.approx(80.0, rel=1e-12)
    assert row["reconductor_cost_usd"] == pytest.approx(1_035_000.0, rel=1e-12)
    assert row["dlr_uplift_mw"] is None
    detail = scored.to_detail_row(storage)
    assert detail["conductor_material"] == "ACSR"
    assert detail["conductor_kcmil"] == 795
    assert detail["best_tech"] == "reconductor"


def test_artifact_is_deterministic():
    assert _build() == _build()
    assert _build().model_dump() == _build().model_dump()


def test_reconductoring_module_never_imports_dlr():
    repo_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, twin.reconductor; "
                "assert 'twin.dlr' not in sys.modules, sorted(sys.modules)"
            ),
        ],
        check=False,
        cwd=repo_root,
        env={"PYTHONPATH": str(repo_root), "PATH": ""},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_ready_artifact_cannot_be_read_as_dlr():
    artifact = _build()
    assert artifact.intervention.intervention is not InterventionType.DLR
    assert "hours_above_static" not in ReconductorIntervention.model_fields
    assert "weather_input_sha256" not in ReconductorArtifact.model_fields


def _assert_unavailable(artifact, reason: UnavailableReason):
    assert isinstance(artifact, UnavailableReconductorArtifact), artifact
    assert artifact.key == KEY
    assert artifact.scenario_id == "uri_2021"
    assert artifact.intervention_type is InterventionType.RECONDUCTOR
    assert artifact.reason is reason
    assert isinstance(artifact.unavailable, Unavailable)
    assert artifact.unavailable.code == "invalid_prerequisite"
    assert artifact.unavailable.reason == reason.value
    assert artifact.unavailable.retryable is False
    assert artifact.detail
    assert not hasattr(artifact, "intervention")
    assert not hasattr(artifact, "uplift_mw")
    assert not hasattr(artifact, "cost_usd")


@pytest.mark.parametrize(
    "overrides",
    [
        {"rate_a_mw": None},
        {"rate_a_mw": float("nan")},
        {"rate_a_mw": float("inf")},
        {"rate_a_mw": -float("inf")},
        {"rate_a_mw": 0.0},
        {"rate_a_mw": -5.0},
        {"rate_a_mw": "145"},
        {"rate_a_mw": True},
        {"unit": "A"},
        {"unit": "kW"},
    ],
    ids=str,
)
def test_unusable_static_rating_is_no_rating_not_a_nan_artifact(overrides):
    _assert_unavailable(_build(**overrides), UnavailableReason.NO_RATING)
    plain = build_reconductor_intervention(
        rate_a_mw=overrides.get("rate_a_mw", 100.0),
        material="ACSR",
        kcmil=795,
        length_km=ONE_MILE_KM,
        base_kv=138.0,
        costs=FULL_COSTS,
        unit=overrides.get("unit", "MW"),
    )
    assert plain is UnavailableReason.NO_RATING


@pytest.mark.parametrize(
    "overrides",
    [
        {"material": None},
        {"material": ""},
        {"material": "   "},
        {"material": "COPPER"},
        {"material": "ACSR", "kcmil": None},
        {"material": "ACSR", "kcmil": 0},
        {"material": "ACSR", "kcmil": -795},
    ],
    ids=str,
)
def test_unsupported_conductor_is_no_conductor(overrides):
    _assert_unavailable(_build(**overrides), UnavailableReason.NO_CONDUCTOR)


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_kv": 500.0},
        {"length_km": 0.0},
        {"length_km": None},
        {"length_km": float("nan")},
        {"costs": {}},
        {"costs": {"138": {"value": 900_000.0}}},  # unsourced
    ],
    ids=str,
)
def test_missing_cost_inputs_are_cost_unknown(overrides):
    _assert_unavailable(_build(**overrides), UnavailableReason.COST_UNKNOWN)


def test_guards_are_checked_in_rating_conductor_cost_order():
    everything_wrong = _build(rate_a_mw=float("nan"), material=None, costs={})
    assert everything_wrong.reason is UnavailableReason.NO_RATING
    no_conductor = _build(material=None, costs={})
    assert no_conductor.reason is UnavailableReason.NO_CONDUCTOR


def test_empty_scenario_id_is_an_identity_error_not_an_unavailable_line():
    with pytest.raises(ValueError):
        _build(scenario_id="")


def test_artifact_scenario_id_must_match_the_line_key_scenario_id():
    with pytest.raises(ValueError, match="must match the line key scenario_id"):
        _build(scenario_id="annual_2024")
    with pytest.raises(ValueError, match="must match the line key scenario_id"):
        _build(scenario_id="annual_2024", material=None)
    artifact = _build(
        key=LineKey(line_id=4711, region="ERCOT", scenario_id="x1"), scenario_id="x1"
    )
    assert artifact.key.scenario_id == artifact.scenario_id == "x1"


def test_ready_artifact_never_carries_a_non_finite_number():
    artifact = _build(rate_a_mw=1e-300, material="ACSS")
    assert isinstance(artifact, ReconductorArtifact)
    assert math.isfinite(artifact.intervention.uplift_mw)
    assert math.isfinite(artifact.intervention.cost_usd)

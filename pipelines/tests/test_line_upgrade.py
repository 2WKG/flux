from datetime import UTC, datetime

from pipelines.line_upgrade import persist_ranking, rank_results, score_line
from pipelines.line_upgrade_contracts import (
    DlrIntervention,
    LineKey,
    LineUpgradeProvenance,
    ReconductorIntervention,
    SimulatedCongestion,
    StorageProvenance,
    UnavailableLine,
    UnavailableReason,
)


H = "a" * 64
PROVENANCE = LineUpgradeProvenance(
    ranking_version="v1",
    computed_at=datetime(2024, 1, 1, tzinfo=UTC),
    grid_input_sha256=H,
    weather_input_sha256=H,
    cost_params_sha256=H,
)
STORAGE = StorageProvenance(
    source_name="fixture", source_ref="test", source_version="1", fixture_batch_id="batch-1"
)
CONGESTION = SimulatedCongestion(usd_per_year=1_000_000, run_id="run-1")


def _result(line_id: int, uplift: float):
    return score_line(
        key=LineKey(line_id=line_id, region="ERCOT"),
        provenance=PROVENANCE,
        congestion=CONGESTION,
        static_rating_mw=100,
        interventions=(
            DlrIntervention(uplift_mw=uplift, hours_above_static=20, cost_usd=1_000_000),
            ReconductorIntervention(uplift_mw=uplift / 2, cost_usd=1_000_000, conductor_material="ACSS"),
        ),
    )


def test_scoring_selects_best_intervention_and_persists_components():
    result = _result(2, 30)
    artifact = persist_ranking((result,), STORAGE)

    assert artifact.score_rows[0]["dlr_uplift_mw"] == 30
    assert artifact.score_rows[0]["reconductor_uplift_mw"] == 15
    assert artifact.detail_rows[0]["best_tech"] == "dlr"
    assert artifact.score_rows[0]["mw_per_musd"] == 30


def test_missing_prerequisites_are_unavailable_not_partial_scores():
    result = score_line(
        key=LineKey(line_id=2, region="ERCOT"),
        provenance=PROVENANCE,
        congestion=None,
        static_rating_mw=100,
        interventions=(),
    )

    assert isinstance(result, UnavailableLine)
    assert result.reason is UnavailableReason.NO_CONGESTION_INPUT
    assert persist_ranking((result,), STORAGE).score_rows == ()


def test_ranking_and_serialization_are_deterministic():
    first = (_result(2, 20), _result(1, 20), _result(3, 30))
    second = tuple(reversed(first))

    first_artifact = persist_ranking(first, STORAGE)
    second_artifact = persist_ranking(second, STORAGE)
    assert [result.key.line_id for result in rank_results(first)] == [3, 1, 2]
    assert first_artifact.canonical_json() == second_artifact.canonical_json()

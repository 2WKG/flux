from datetime import UTC, datetime

import duckdb

from pipelines.db import ensure_schema
from pipelines.line_upgrade import (
    persist_ranking,
    rank_results,
    score_line,
    write_ranking,
)
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
    source_name="fixture",
    source_ref="test",
    source_version="1",
    fixture_batch_id="batch-1",
)
CONGESTION = SimulatedCongestion(usd_per_year=1_000_000, run_id="run-1")


def _result(line_id: int, uplift: float):
    return score_line(
        key=LineKey(line_id=line_id, region="ERCOT"),
        provenance=PROVENANCE,
        congestion=CONGESTION,
        static_rating_mw=100,
        interventions=(
            DlrIntervention(
                uplift_mw=uplift, hours_above_static=20, cost_usd=1_000_000
            ),
            ReconductorIntervention(
                uplift_mw=uplift / 2, cost_usd=1_000_000, conductor_material="ACSS"
            ),
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


def test_missing_weather_returns_an_unavailable_record():
    result = score_line(
        key=LineKey(line_id=2, region="ERCOT"),
        provenance=PROVENANCE.model_copy(update={"weather_input_sha256": None}),
        congestion=CONGESTION,
        static_rating_mw=100,
        interventions=(
            DlrIntervention(uplift_mw=30, hours_above_static=20, cost_usd=1_000_000),
        ),
    )

    assert isinstance(result, UnavailableLine)
    assert result.reason is UnavailableReason.NO_WEATHER


def test_write_ranking_persists_score_and_detail_rows():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    provenance = STORAGE.model_dump()
    con.execute(
        "INSERT INTO counties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ["48001", "Example", "TX", 1, b"county", *provenance.values()],
    )
    for bus_id in (1, 2):
        con.execute(
            "INSERT INTO buses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                bus_id,
                f"Bus {bus_id}",
                345.0,
                -97.0,
                30.0,
                "48001",
                "ERCOT",
                "fixture",
                None,
                None,
                *provenance.values(),
            ],
        )
    con.execute(
        "INSERT INTO lines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [2, 1, 2, "1", 345.0, 0.1, 0.2, 400.0, 10.0, None, False, *provenance.values()],
    )

    ranking = persist_ranking((_result(2, 30),), STORAGE)
    assert write_ranking(con, ranking, STORAGE) == (1, 1)
    assert con.execute("SELECT mw_per_musd FROM line_upgrade_scores").fetchone() == (
        30.0,
    )
    assert con.execute("SELECT best_tech FROM line_upgrade_detail").fetchone() == (
        "dlr",
    )


def test_ranking_and_serialization_are_deterministic():
    first = (_result(2, 20), _result(1, 20), _result(3, 30))
    second = tuple(reversed(first))

    first_artifact = persist_ranking(first, STORAGE)
    second_artifact = persist_ranking(second, STORAGE)
    assert [result.key.line_id for result in rank_results(first)] == [3, 1, 2]
    assert first_artifact.canonical_json() == second_artifact.canonical_json()

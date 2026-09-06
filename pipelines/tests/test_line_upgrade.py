import json
import subprocess
import sys
from datetime import UTC, datetime

import duckdb
import pytest

from pipelines import db
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
    ScoredLine,
    SimulatedCongestion,
    StorageProvenance,
    UnavailableLine,
    UnavailableReason,
)

H = "a" * 64
SCENARIO = "uri_2021"
PROVENANCE = LineUpgradeProvenance(
    ranking_version="v1",
    computed_at=datetime(2024, 1, 1, tzinfo=UTC),
    grid_input_sha256=H,
    weather_input_sha256=H,
    cost_params_sha256=H,
)
PROVENANCE_NO_WEATHER = LineUpgradeProvenance(
    ranking_version="v1",
    computed_at=datetime(2024, 1, 1, tzinfo=UTC),
    grid_input_sha256=H,
    cost_params_sha256=H,
)
STORAGE = StorageProvenance(
    source_name="fixture",
    source_ref="test",
    source_version="1",
    fixture_batch_id="batch-1",
)


def _key(line_id: int, region: str = "ERCOT", scenario_id: str = SCENARIO) -> LineKey:
    return LineKey(line_id=line_id, region=region, scenario_id=scenario_id)


def _congestion(scenario_id: str = SCENARIO) -> SimulatedCongestion:
    return SimulatedCongestion(
        usd_per_year=1_000_000, scenario_id=scenario_id, run_id=f"run-{scenario_id}"
    )


def _score(
    line_id: int,
    interventions,
    *,
    region: str = "ERCOT",
    scenario_id: str = SCENARIO,
    provenance: LineUpgradeProvenance = PROVENANCE,
    static_rating_mw: float | None = 100,
    congestion=None,
):
    return score_line(
        key=_key(line_id, region, scenario_id),
        provenance=provenance,
        congestion=_congestion(scenario_id) if congestion is None else congestion,
        static_rating_mw=static_rating_mw,
        interventions=interventions,
    )


def _result(line_id: int, uplift: float, **kw):
    return _score(
        line_id,
        (
            DlrIntervention(
                uplift_mw=uplift, hours_above_static=20, cost_usd=1_000_000
            ),
            ReconductorIntervention(
                uplift_mw=uplift / 2, cost_usd=1_000_000, conductor_material="ACSS"
            ),
        ),
        **kw,
    )


def _dlr(uplift: float, cost: float = 1_000_000, hours: int = 20) -> DlrIntervention:
    return DlrIntervention(uplift_mw=uplift, hours_above_static=hours, cost_usd=cost)


def _reconductor(uplift: float, cost: float = 1_000_000) -> ReconductorIntervention:
    return ReconductorIntervention(
        uplift_mw=uplift, cost_usd=cost, conductor_material="ACSS"
    )


# --- scoring -----------------------------------------------------------------


def test_scoring_selects_best_intervention_and_persists_components():
    result = _result(2, 30)
    artifact = persist_ranking((result,), STORAGE)

    assert artifact.score_rows[0]["dlr_uplift_mw"] == 30
    assert artifact.score_rows[0]["reconductor_uplift_mw"] == 15
    assert artifact.detail_rows[0]["best_tech"] == "dlr"
    assert artifact.score_rows[0]["mw_per_musd"] == 30
    assert artifact.score_rows[0]["scenario_id"] == SCENARIO


def test_missing_prerequisites_are_unavailable_not_partial_scores():
    result = score_line(
        key=_key(2),
        provenance=PROVENANCE,
        congestion=None,
        static_rating_mw=100,
        interventions=(),
    )

    assert isinstance(result, UnavailableLine)
    assert result.reason is UnavailableReason.NO_CONGESTION_INPUT
    assert persist_ranking((result,), STORAGE).score_rows == ()


@pytest.mark.parametrize("rating", [None, 0, -5.0, float("inf"), float("nan")])
def test_no_usable_static_rating_is_named_no_rating(rating):
    result = _score(1, (_dlr(10),), static_rating_mw=rating)

    assert isinstance(result, UnavailableLine)
    assert result.reason is UnavailableReason.NO_RATING


@pytest.mark.parametrize(
    "interventions",
    [
        (),
        (_dlr(10, cost=0),),
        (_dlr(10, cost=0), _reconductor(10, cost=0)),
        (_reconductor(10, cost=float("inf")),),
    ],
)
def test_no_costed_intervention_is_named_cost_unknown(interventions):
    result = _score(1, interventions)

    assert isinstance(result, UnavailableLine)
    assert result.reason is UnavailableReason.COST_UNKNOWN


def test_dlr_without_weather_provenance_is_named_no_weather_not_a_crash():
    result = _score(1, (_dlr(10),), provenance=PROVENANCE_NO_WEATHER)

    assert isinstance(result, UnavailableLine)
    assert result.reason is UnavailableReason.NO_WEATHER


def test_dlr_without_weather_provenance_falls_through_to_reconductor():
    result = _score(1, (_dlr(50), _reconductor(10)), provenance=PROVENANCE_NO_WEATHER)

    assert isinstance(result, ScoredLine)
    assert isinstance(result.best, ReconductorIntervention)
    assert result.alternative is None
    assert result.mw_per_musd == 10


def test_infinite_uplift_is_unavailable_and_never_ranks_first():
    alone = _score(1, (_dlr(float("inf")),))
    assert isinstance(alone, UnavailableLine)
    assert alone.reason is UnavailableReason.NO_RATING

    with_finite = _score(1, (_dlr(float("inf")), _reconductor(10)))
    assert isinstance(with_finite, ScoredLine)
    assert isinstance(with_finite.best, ReconductorIntervention)
    assert with_finite.mw_per_musd == 10


# --- intra-line tie-breaker: score, cost, type, uplift, canonical form --------


def test_intra_line_tie_on_score_prefers_the_cheaper_intervention():
    # Equal rounded score (10 MW/M$); the cheaper one is the reconductor, so a
    # name-only tie-breaker ("dlr" < "reconductor") would pick the wrong one.
    result = _score(1, (_dlr(20, cost=2_000_000), _reconductor(10, cost=1_000_000)))

    assert isinstance(result, ScoredLine)
    assert isinstance(result.best, ReconductorIntervention)
    assert result.best.cost_usd == 1_000_000
    assert isinstance(result.alternative, DlrIntervention)


def test_intra_line_tie_on_score_and_cost_prefers_dlr_by_type_name():
    result = _score(1, (_reconductor(10), _dlr(10)))

    assert isinstance(result, ScoredLine)
    assert isinstance(result.best, DlrIntervention)
    assert isinstance(result.alternative, ReconductorIntervention)


def test_same_type_tie_is_total_and_input_order_independent():
    a = _dlr(10, hours=5)
    b = _dlr(10, hours=9)

    forward = _score(1, (a, b))
    reverse = _score(1, (b, a))

    assert isinstance(forward, ScoredLine) and isinstance(reverse, ScoredLine)
    assert forward.best == reverse.best
    assert forward.alternative is None and reverse.alternative is None


def test_same_type_and_cost_tie_prefers_the_higher_uplift():
    # Both round to 10.000 MW/M$ at equal cost; the larger uplift wins (and
    # the canonical-form fallback would order these the other way).
    low = _dlr(10.0001, cost=1_000_000)
    high = _dlr(10.0004, cost=1_000_000)

    assert _score(1, (low, high)).best == high
    assert _score(1, (high, low)).best == high


# --- ranking across lines ----------------------------------------------------


def test_ranking_and_serialization_are_deterministic():
    first = (_result(2, 20), _result(1, 20), _result(3, 30))
    second = tuple(reversed(first))

    first_artifact = persist_ranking(first, STORAGE)
    second_artifact = persist_ranking(second, STORAGE)
    assert [result.key.line_id for result in rank_results(first)] == [3, 1, 2]
    assert first_artifact.canonical_json() == second_artifact.canonical_json()


def test_canonical_json_is_key_sorted_and_compact():
    artifact = persist_ranking((_result(2, 20), _result(1, 30)), STORAGE)
    raw = artifact.canonical_json()

    canonical = json.dumps(
        json.loads(raw), sort_keys=True, separators=(",", ":")
    ).encode()
    assert raw == canonical
    assert raw.startswith(b'{"detail_rows":[{"aar_rating_mw":null,')


def test_unavailable_records_rank_after_every_scored_record():
    unavailable_low_id = score_line(
        key=_key(1),
        provenance=PROVENANCE,
        congestion=None,
        static_rating_mw=100,
        interventions=(),
    )
    no_rating = _score(2, (_dlr(10),), static_rating_mw=None)
    scored = (_result(9, 5), _result(8, 50))

    ranked = rank_results((unavailable_low_id, *scored, no_rating))

    assert [type(r).__name__ for r in ranked] == [
        "ScoredLine",
        "ScoredLine",
        "UnavailableLine",
        "UnavailableLine",
    ]
    assert [r.key.line_id for r in ranked] == [8, 9, 1, 2]


def test_ranking_refuses_to_interleave_regions():
    ercot = _score(1, (_reconductor(10),), region="ERCOT")
    pjm = _score(1, (_reconductor(20),), region="PJM")

    with pytest.raises(ValueError, match="one scenario_id and one region"):
        rank_results((pjm, ercot))
    with pytest.raises(ValueError, match="one scenario_id and one region"):
        persist_ranking((ercot, pjm), STORAGE)


def test_ranking_refuses_to_interleave_scenarios():
    winter = _score(1, (_reconductor(10),), scenario_id="uri_2021")
    annual = _score(2, (_reconductor(20),), scenario_id="annual_2024")

    with pytest.raises(ValueError):
        rank_results((winter, annual))


def test_ranking_refuses_mixed_partition_even_when_only_unavailables_differ():
    scored = _score(1, (_reconductor(10),), region="ERCOT")
    unavailable = score_line(
        key=_key(1, region="PJM"),
        provenance=PROVENANCE,
        congestion=None,
        static_rating_mw=100,
        interventions=(),
    )

    with pytest.raises(ValueError):
        rank_results((scored, unavailable))


# --- persistence through the real DuckDB contract ----------------------------


def _seed_lines(con: duckdb.DuckDBPyConnection, line_ids: tuple[int, ...]) -> None:
    provenance = list(STORAGE.model_dump().values())
    con.execute(
        """INSERT INTO counties (
            county_fips, name, state, pop, geom_wkb,
            source_name, source_ref, source_version, source_retrieved_at, fixture_batch_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ["48001", "Example", "TX", 1, b"county", *provenance],
    )
    for bus_id in (1, 2):
        con.execute(
            """INSERT INTO buses (
                bus_id, name, base_kv, lon, lat, county_fips, ba_code, coord_source, zone, area,
                source_name, source_ref, source_version, source_retrieved_at, fixture_batch_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                bus_id,
                f"Bus {bus_id}",
                345.0,
                -97.0 + bus_id,
                30.0,
                "48001",
                "ERCOT",
                "fixture",
                None,
                None,
                *provenance,
            ],
        )
    for line_id in line_ids:
        con.execute(
            """INSERT INTO lines (
                line_id, from_bus, to_bus, circuit, base_kv, r_pu, x_pu, rate_a_mw, length_km,
                geom_wkb, is_transformer,
                source_name, source_ref, source_version, source_retrieved_at, fixture_batch_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [line_id, 1, 2, str(line_id), 345.0, 0.1, 0.2, 400.0, 10.0, None, False]
            + provenance,
        )


def _identities(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple]:
    return con.execute(
        f"SELECT line_id, scenario_id, simulation_run_id FROM {table} "
        "ORDER BY scenario_id, line_id"
    ).fetchall()


def test_write_ranking_round_trips_two_scenarios_through_a_real_database(tmp_path):
    path = tmp_path / "grid.duckdb"
    con = db.connect(path)
    _seed_lines(con, (1, 2))

    winter = persist_ranking(
        (
            _result(1, 20, scenario_id="uri_2021"),
            _result(2, 30, scenario_id="uri_2021"),
        ),
        STORAGE,
    )
    annual = persist_ranking((_result(1, 25, scenario_id="annual_2024"),), STORAGE)
    assert write_ranking(con, winter) == 2
    assert write_ranking(con, annual) == 1
    con.close()

    reopened = db.connect(path, read_only=True)
    expected = [
        (1, "annual_2024", "run-annual_2024"),
        (1, "uri_2021", "run-uri_2021"),
        (2, "uri_2021", "run-uri_2021"),
    ]
    assert _identities(reopened, "line_upgrade_scores") == expected
    assert _identities(reopened, "line_upgrade_detail") == expected
    assert reopened.execute(
        "SELECT mw_per_musd FROM line_upgrade_scores "
        "WHERE line_id = 1 AND scenario_id = 'annual_2024'"
    ).fetchone() == (25.0,)
    assert reopened.execute(
        "SELECT best_tech, region, dlr_p50_mw FROM line_upgrade_detail "
        "WHERE line_id = 2 AND scenario_id = 'uri_2021'"
    ).fetchone() == ("dlr", "ERCOT", 130.0)
    reopened.close()


def test_write_ranking_rejects_a_duplicate_identity_and_writes_nothing(tmp_path):
    con = db.connect(tmp_path / "grid.duckdb")
    _seed_lines(con, (1, 2, 3))
    write_ranking(con, persist_ranking((_result(1, 20), _result(2, 20)), STORAGE))
    before = _identities(con, "line_upgrade_scores")

    # Line 3 ranks first (higher score) and would be inserted before the
    # duplicate line 1 trips the primary key; the write must roll it back.
    with pytest.raises(duckdb.ConstraintException):
        write_ranking(con, persist_ranking((_result(3, 40), _result(1, 20)), STORAGE))

    assert _identities(con, "line_upgrade_scores") == before
    assert _identities(con, "line_upgrade_detail") == before
    assert (3, SCENARIO, "run-uri_2021") not in before
    con.close()


def test_write_ranking_skips_unavailables_and_reports_scored_count():
    con = duckdb.connect(":memory:")
    db.ensure_schema(con)
    _seed_lines(con, (1,))
    unavailable = score_line(
        key=_key(7),
        provenance=PROVENANCE,
        congestion=None,
        static_rating_mw=100,
        interventions=(),
    )
    ranking = persist_ranking((unavailable, _result(1, 20)), STORAGE)

    assert write_ranking(con, ranking) == 1
    assert con.execute("SELECT count(*) FROM line_upgrade_scores").fetchone() == (1,)
    assert ranking.unavailable == (unavailable,)


# --- CLI ---------------------------------------------------------------------


def test_module_cli_refuses_loudly_instead_of_exiting_zero():
    completed = subprocess.run(
        [sys.executable, "-m", "pipelines.line_upgrade", "--region", "ERCOT"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "not implemented" in completed.stderr

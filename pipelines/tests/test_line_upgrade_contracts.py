"""Behavioural checks for the 2WKG-107 line-upgrade contract.

Each test pins one "Done when" clause from 2WKG-179/180/181/182.
"""

from datetime import UTC, datetime

import duckdb
import pytest
from pydantic import ValidationError

from pipelines.db import ensure_schema
from pipelines.line_upgrade_contracts import (
    CONTRACT_VERSION,
    CongestionSource,
    DlrIntervention,
    InterventionType,
    LineKey,
    LineUpgradeProvenance,
    ObservedCongestion,
    ProxyCongestion,
    ReconductorIntervention,
    ScoredLine,
    SimulatedCongestion,
    StorageProvenance,
    UnattributedCongestion,
    UnavailableLine,
    UnavailableReason,
    mw_per_musd,
    rank,
)

H = "b" * 64
SCENARIO_ID = "uri_2021"
KEY = LineKey(line_id=1, region="ERCOT", scenario_id=SCENARIO_ID)


def _prov(weather: str | None = H) -> LineUpgradeProvenance:
    return LineUpgradeProvenance(
        ranking_version="r1",
        computed_at=datetime(2026, 9, 5, tzinfo=UTC),
        grid_input_sha256=H,
        weather_input_sha256=weather,
        cost_params_sha256=H,
    )


def _dlr(uplift: float = 50.0, cost: float = 1_000_000.0) -> DlrIntervention:
    return DlrIntervention(uplift_mw=uplift, hours_above_static=1200, cost_usd=cost)


def _storage() -> StorageProvenance:
    return StorageProvenance(
        source_name="line_upgrade",
        source_ref="case-2026-09",
        source_version="r1",
        source_retrieved_at=datetime(2026, 9, 5, tzinfo=UTC),
        fixture_batch_id="fixture-1",
    )


def _scored(**kw) -> ScoredLine:
    base = {
        "key": KEY,
        "provenance": _prov(),
        "congestion": SimulatedCongestion(
            usd_per_year=1e6, scenario_id=SCENARIO_ID, run_id="run-1"
        ),
        "best": _dlr(),
        "static_rating_mw": 400.0,
        "mw_per_musd": 50.0,
    }
    return ScoredLine(**(base | kw))


# --- 2WKG-179: identity and provenance --------------------------------------


def test_line_identity_requires_a_scenario_scope_without_claiming_simulation():
    key = LineKey(line_id=1, region="ERCOT", scenario_id="annual_2024")
    assert key.model_dump() == {
        "line_id": 1,
        "region": "ERCOT",
        "scenario_id": "annual_2024",
    }
    with pytest.raises(ValidationError):
        LineKey(line_id=1, region="ERCOT", scenario_id="")


def test_simulated_run_must_name_the_same_scenario_as_the_artifact():
    with pytest.raises(ValidationError, match="must match"):
        _scored(
            congestion=SimulatedCongestion(
                usd_per_year=1e6,
                scenario_id="beryl_2024",
                run_id="beryl-s0-abc12345",
            )
        )


def test_simulated_congestion_requires_a_nonempty_scenario():
    with pytest.raises(ValidationError):
        SimulatedCongestion(usd_per_year=1e6, scenario_id="", run_id="run-1")


def test_provenance_requires_utc():
    with pytest.raises(ValidationError, match="UTC"):
        LineUpgradeProvenance(
            ranking_version="r1",
            computed_at=datetime.fromisoformat("2026-09-05"),
            grid_input_sha256=H,
            cost_params_sha256=H,
        )


def test_dlr_figure_requires_weather_provenance():
    """No field may imply measured conditions the inputs cannot support."""
    with pytest.raises(ValidationError, match="weather_input_sha256"):
        _scored(provenance=_prov(weather=None))


def test_dlr_alternative_requires_weather_provenance():
    with pytest.raises(ValidationError, match="weather_input_sha256"):
        _scored(
            provenance=_prov(weather=None),
            best=ReconductorIntervention(
                uplift_mw=120.0, cost_usd=1_000_000.0, conductor_material="ACSS"
            ),
            alternative=_dlr(uplift=50.0, cost=1_000_000.0),
            mw_per_musd=120.0,
        )


def test_contract_version_is_independent_of_the_storage_schema():
    assert CONTRACT_VERSION == "1.0.0"


# --- 2WKG-180: enumerations --------------------------------------------------


def test_four_congestion_classes_are_distinct():
    assert {s.value for s in CongestionSource} == {
        "observed",
        "simulated",
        "proxy",
        "unattributed",
    }


def test_only_observed_congestion_carries_market_provenance():
    obs = ObservedCongestion(
        usd_per_year=1e6,
        market="ERCOT SCED",
        input_sha256=H,
        mapping_confidence=0.9,
        mapping_method="fuzzy",
    )
    assert obs.market
    for other in (
        SimulatedCongestion(usd_per_year=1e6, scenario_id=SCENARIO_ID, run_id="r"),
        ProxyCongestion(
            usd_per_year=1e6,
            assumed_usd_per_mwh=20.0,
            assumption_note="twin overload x $20/MWh",
        ),
    ):
        assert not hasattr(other, "market")
        assert not hasattr(other, "mapping_confidence")


def test_non_simulated_congestion_cannot_claim_a_twin_run_or_scenario():
    with pytest.raises(ValidationError):
        ObservedCongestion.model_validate(
            {
                "usd_per_year": 1e6,
                "market": "ERCOT SCED",
                "input_sha256": H,
                "mapping_confidence": 1.0,
                "mapping_method": "exact",
                "run_id": "uri_2021-s0-abc12345",
            }
        )
    with pytest.raises(ValidationError):
        ProxyCongestion.model_validate(
            {
                "usd_per_year": 1e6,
                "assumed_usd_per_mwh": 20.0,
                "assumption_note": "declared proxy",
                "scenario_id": SCENARIO_ID,
            }
        )


def test_proxy_cannot_forge_market_fields():
    with pytest.raises(ValidationError):
        ProxyCongestion.model_validate(
            {
                "source": "proxy",
                "usd_per_year": 1.0,
                "assumed_usd_per_mwh": 20.0,
                "assumption_note": "x",
                "market": "ERCOT SCED",
            }
        )


def test_unattributed_carries_no_dollar_figure():
    u = UnattributedCongestion(reason=UnavailableReason.UNMAPPED_CONSTRAINT)
    assert not hasattr(u, "usd_per_year")


def test_dlr_and_reconductor_cannot_collide_in_one_record():
    with pytest.raises(ValidationError, match="different intervention type"):
        _scored(alternative=_dlr(uplift=10.0, cost=2_000_000.0))


def test_alternative_may_be_the_other_type():
    line = _scored(
        alternative=ReconductorIntervention(
            uplift_mw=120.0, cost_usd=8_000_000.0, conductor_material="ACSS"
        )
    )
    assert line.best.intervention is InterventionType.DLR
    assert line.alternative.intervention is InterventionType.RECONDUCTOR


# --- 2WKG-181: score semantics -----------------------------------------------


def test_score_is_uplift_per_million_and_rounds_to_three_dp():
    assert mw_per_musd(50.0, 1_000_000.0) == 50.0
    assert mw_per_musd(1.0, 3_000_000.0) == 0.333


def test_unknown_cost_gives_none_not_infinity():
    assert mw_per_musd(50.0, 0.0) is None


def test_score_must_match_the_best_intervention():
    with pytest.raises(ValidationError, match="mw_per_musd"):
        _scored(mw_per_musd=999.0)


def test_aar_rating_is_optional_when_hourly_weather_is_unavailable():
    assert _scored().aar_rating_mw is None


def test_best_must_score_at_least_as_high_as_alternative():
    with pytest.raises(ValidationError, match="higher-scoring"):
        _scored(
            alternative=ReconductorIntervention(
                uplift_mw=100.0, cost_usd=1_000_000.0, conductor_material="ACSS"
            )
        )


def test_ferc_screen_is_none_not_false_when_congestion_is_unattributed():
    line = _scored(
        congestion=UnattributedCongestion(reason=UnavailableReason.UNMAPPED_CONSTRAINT),
        ferc_screen_pass=None,
    )
    assert line.ferc_screen_pass is None
    with pytest.raises(ValidationError, match="must be None"):
        _scored(
            congestion=UnattributedCongestion(
                reason=UnavailableReason.UNMAPPED_CONSTRAINT
            ),
            ferc_screen_pass=False,
        )


def test_ranking_is_deterministic_and_breaks_ties_by_cost_then_id():
    cheap = ScoredLine(
        key=LineKey(line_id=2, region="ERCOT", scenario_id=SCENARIO_ID),
        provenance=_prov(),
        congestion=SimulatedCongestion(
            usd_per_year=1.0, scenario_id=SCENARIO_ID, run_id="r"
        ),
        best=_dlr(50.0, 1_000_000.0),
        static_rating_mw=1.0,
        aar_rating_mw=1.0,
        mw_per_musd=50.0,
    )
    dearer = ScoredLine(
        key=LineKey(line_id=1, region="ERCOT", scenario_id=SCENARIO_ID),
        provenance=_prov(),
        congestion=SimulatedCongestion(
            usd_per_year=1.0, scenario_id=SCENARIO_ID, run_id="r"
        ),
        best=_dlr(100.0, 2_000_000.0),
        static_rating_mw=1.0,
        aar_rating_mw=1.0,
        mw_per_musd=50.0,
    )
    top = ScoredLine(
        key=LineKey(line_id=3, region="ERCOT", scenario_id=SCENARIO_ID),
        provenance=_prov(),
        congestion=SimulatedCongestion(
            usd_per_year=1.0, scenario_id=SCENARIO_ID, run_id="r"
        ),
        best=_dlr(200.0, 1_000_000.0),
        static_rating_mw=1.0,
        aar_rating_mw=1.0,
        mw_per_musd=200.0,
    )
    order = [line.key.line_id for line in rank([cheap, dearer, top])]
    assert order == [3, 2, 1]
    assert rank([dearer, top, cheap]) == rank([cheap, dearer, top])


def test_ranking_rejects_mixed_scenarios():
    with pytest.raises(ValueError, match="exactly one scenario_id"):
        rank(
            [
                _scored(),
                _scored(
                    key=LineKey(line_id=2, region="ERCOT", scenario_id="beryl_2024"),
                    congestion=SimulatedCongestion(
                        usd_per_year=1e6,
                        scenario_id="beryl_2024",
                        run_id="beryl_2024-s0-abc12345",
                    ),
                ),
            ]
        )


def test_every_unavailable_outcome_names_a_reason():
    u = UnavailableLine(key=KEY, provenance=_prov(), reason=UnavailableReason.NO_RATING)
    assert u.reason in set(UnavailableReason)
    assert not hasattr(u, "mw_per_musd")


@pytest.mark.parametrize(
    ("congestion", "method"),
    [
        (
            SimulatedCongestion(
                usd_per_year=1.0, scenario_id=SCENARIO_ID, run_id="run-1"
            ),
            "twin_proxy",
        ),
        (
            ProxyCongestion(
                usd_per_year=1.0,
                assumed_usd_per_mwh=20.0,
                assumption_note="declared proxy",
            ),
            "twin_proxy",
        ),
        (
            UnattributedCongestion(reason=UnavailableReason.UNMAPPED_CONSTRAINT),
            "unmapped",
        ),
    ],
)
def test_detail_row_maps_non_market_congestion_to_a_legal_schema_value(
    congestion, method
):
    assert (
        _scored(congestion=congestion).to_detail_row(_storage())["congestion_method"]
        == method
    )


def test_scored_line_rows_round_trip_through_the_canonical_duckdb_schema():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    storage = _storage()
    provenance = storage.model_dump()
    con.execute(
        """INSERT INTO counties (
            county_fips, name, state, pop, geom_wkb,
            source_name, source_ref, source_version, source_retrieved_at, fixture_batch_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ["48001", "Example", "TX", 1, b"county", *provenance.values()],
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
                *provenance.values(),
            ],
        )
    con.execute(
        """INSERT INTO lines (
            line_id, from_bus, to_bus, circuit, base_kv, r_pu, x_pu, rate_a_mw, length_km, geom_wkb,
            is_transformer, source_name, source_ref, source_version, source_retrieved_at, fixture_batch_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [1, 1, 2, "1", 345.0, 0.1, 0.2, 400.0, 10.0, None, False, *provenance.values()],
    )
    line = _scored(
        congestion=ObservedCongestion(
            usd_per_year=1_000_000.0,
            market="ERCOT SCED",
            input_sha256=H,
            mapping_confidence=0.9,
            mapping_method="fuzzy",
        ),
        alternative=ReconductorIntervention(
            uplift_mw=120.0,
            cost_usd=8_000_000.0,
            conductor_material="ACSS",
            conductor_kcmil=795,
        ),
        aar_rating_mw=425.0,
        owner="Example Transmission",
        payback_yr=4.5,
    )
    score_row = line.to_score_row(storage)
    detail_row = line.to_detail_row(storage)
    contract_provenance = line.provenance.model_dump()
    expected_identity_and_contract = {
        "scenario_id": SCENARIO_ID,
        **contract_provenance,
    }
    assert expected_identity_and_contract.items() <= score_row.items()
    assert expected_identity_and_contract.items() <= detail_row.items()
    assert score_row["simulation_run_id"] is None
    assert detail_row["simulation_run_id"] is None
    con.execute(
        f"INSERT INTO line_upgrade_scores ({', '.join(score_row)}) VALUES ({', '.join('?' for _ in score_row)})",
        list(score_row.values()),
    )
    con.execute(
        f"INSERT INTO line_upgrade_detail ({', '.join(detail_row)}) VALUES ({', '.join('?' for _ in detail_row)})",
        list(detail_row.values()),
    )
    assert con.execute(
        """SELECT scenario_id, congestion_usd_yr, dlr_uplift_mw, reconductor_uplift_mw,
                  mw_per_musd, ranking_version, contract_version, simulation_run_id, grid_input_sha256,
                  weather_input_sha256, cost_params_sha256
           FROM line_upgrade_scores"""
    ).fetchone() == (
        SCENARIO_ID,
        1_000_000.0,
        50.0,
        120.0,
        50.0,
        "r1",
        CONTRACT_VERSION,
        None,
        H,
        H,
        H,
    )
    assert con.execute(
        """SELECT scenario_id, owner, conductor_material, conductor_kcmil, static_rating_mw, aar_rating_mw,
                  dlr_p50_mw, dlr_hours_above_static, best_tech, payback_yr, congestion_method, region
           FROM line_upgrade_detail"""
    ).fetchone() == (
        SCENARIO_ID,
        "Example Transmission",
        "ACSS",
        795.0,
        400.0,
        425.0,
        450.0,
        1200,
        "dlr",
        4.5,
        "fuzzy",
        "ERCOT",
    )


def test_simulated_rows_persist_the_twin_run_without_reclassifying_other_sources():
    line = _scored()
    assert line.to_score_row(_storage())["simulation_run_id"] == "run-1"
    assert line.to_detail_row(_storage())["simulation_run_id"] == "run-1"

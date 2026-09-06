from __future__ import annotations

import duckdb
import pytest

from gnn.contracts import (
    HourPoint,
    PlannedSample,
    SamplingError,
    TrainingSample,
    derive_seed,
)
from gnn.hours import demand_provenance, hourly_demand_profile, select_hours
from twin.contracts import SYNTHETIC_TOPOLOGY_LABEL, SimulationUnavailableError


def _demand_db(tmp_path, rows: list[tuple[str, str, object]]) -> str:
    path = tmp_path / "demand.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(
            "CREATE TABLE ba_load_hourly (ba_code TEXT, ts TIMESTAMP, demand_mw DOUBLE)"
        )
        con.executemany("INSERT INTO ba_load_hourly VALUES (?, ?, ?)", rows)
    return str(path)


def test_derive_seed_is_stable_across_calls():
    assert derive_seed(7, "hours", "stress") == derive_seed(7, "hours", "stress")
    assert derive_seed(7, "hours", "stress") != derive_seed(7, "hours", "calm")


def test_hourly_demand_profile_drops_missing_demand_and_never_defaults(tmp_path):
    path = _demand_db(
        tmp_path,
        [
            ("ERCO", "2021-02-01 00:00:00", 100.0),
            ("ERCO", "2021-02-01 01:00:00", None),
            ("ERCO", "2021-02-01 02:00:00", 0.0),
            ("ERCO", "2021-02-01 03:00:00", 150.0),
        ],
    )
    profile = hourly_demand_profile(path)
    assert [point.hour for point in profile] == [0, 3]
    assert profile[0].scale == pytest.approx(1.0)
    assert profile[1].scale == pytest.approx(1.5)


def test_hourly_demand_profile_fails_closed_when_demand_is_unavailable(tmp_path):
    with pytest.raises(SimulationUnavailableError, match="unavailable"):
        hourly_demand_profile(tmp_path / "missing.duckdb")
    empty = tmp_path / "empty.duckdb"
    with duckdb.connect(str(empty)) as con:
        con.execute("CREATE TABLE buses(bus_id BIGINT)")
    with pytest.raises(SimulationUnavailableError, match="ba_load_hourly"):
        hourly_demand_profile(empty)


def test_select_hours_is_seeded_and_does_not_invent_hours():
    profile = [
        HourPoint(hour=i, ts=f"h{i}", demand_mw=float(i + 1), scale=1.0, band=band)
        for i, band in enumerate(["calm", "calm", "mid", "stress", "stress"])
    ]
    first = select_hours(profile, count=3, seed=11)
    assert first == select_hours(profile, count=3, seed=11)
    assert {point.hour for point in first} <= {point.hour for point in profile}
    with pytest.raises(SamplingError, match="at least one"):
        select_hours(profile, count=0, seed=11)


def test_failed_training_sample_keeps_labels_missing_and_names_synthetic_topology():
    point = HourPoint(hour=3, ts="h3", demand_mw=100.0, scale=1.0, band="mid")
    payload = TrainingSample(
        sample_id="s0",
        plan=PlannedSample(
            sample_index=0,
            kind="n1",
            hour=3,
            element_ids=("line:1",),
            primary_element_id="line:1",
            group_key="line:1",
        ),
        status="failed",
        seed=1,
        scenario_id="interactive",
        scenario_identity={"scenario_hash": "abc"},
        demand=demand_provenance(point, ba_code="ERCO", scale_dispatch=True),
        failure_kind="solver_failed",
        failure_message="dc solve failed",
    ).json()
    assert payload["labels"] is None
    assert payload["synthetic"] is True
    assert payload["topology"] == SYNTHETIC_TOPOLOGY_LABEL
    assert payload["demand"]["per_bus_ba_code"] == "unavailable"

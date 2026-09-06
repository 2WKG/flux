from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from models.jepa import experiment as experiment_module
from models.jepa.experiment import (
    EXPERIMENT_KIND,
    FIXED_HOLDOUT_END_UTC,
    FIXED_HOLDOUT_START_UTC,
    JepaConfig,
    TemporalSplit,
    Window,
    _membership_sha256,
    fixed_temporal_split,
    run_experiment,
    verify_temporal_holdout,
)


def utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def make_window(start: datetime, *, fips: str = "27031") -> Window:
    step = timedelta(minutes=15)
    return Window(
        county_fips=fips,
        county_name=f"County {fips}",
        context_start_utc=utc(start),
        context_end_utc=utc(start + step),
        target_start_utc=utc(start + 2 * step),
        target_end_utc=utc(start + 3 * step),
        context=(1.0, 2.0),
        target=(3.0, 4.0),
    )


def split_config(**kwargs: object) -> JepaConfig:
    values: dict[str, object] = {
        "context_steps": 2,
        "target_steps": 2,
        "embedding_dim": 3,
        "epochs": 2,
        "max_windows": None,
        "holdout_start_utc": "2024-02-01T00:00:00Z",
        "holdout_end_utc": "2024-02-29T23:45:00Z",
    }
    values.update(kwargs)
    return JepaConfig(**values)  # type: ignore[arg-type]


def enough_pre_holdout_windows() -> list[Window]:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    return [make_window(origin + timedelta(hours=index)) for index in range(40)]


def write_source(
    path: Path,
    *,
    fips_codes: tuple[str, ...] = ("27031",),
    days: int = 75,
    origin: datetime | None = None,
) -> Path:
    origin = origin or datetime(2024, 1, 1, tzinfo=UTC)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "fips_code",
                "county",
                "state",
                "customers_out",
                "run_start_time",
                "total_customers",
            ],
        )
        writer.writeheader()
        for step in range(days * 24 * 4):
            timestamp = origin + timedelta(minutes=15 * step)
            for fips in fips_codes:
                writer.writerow(
                    {
                        "fips_code": fips,
                        "county": f"County {fips}",
                        "state": "Minnesota",
                        "customers_out": str((step + int(fips[-1])) % 19),
                        "run_start_time": timestamp.replace(tzinfo=None).isoformat(
                            sep=" "
                        ),
                        "total_customers": "1000",
                    }
                )
    return path


def test_equal_multicounty_timestamps_have_identical_temporal_membership() -> None:
    windows = enough_pre_holdout_windows() + [
        make_window(datetime(2024, 2, 1, tzinfo=UTC), fips="27031"),
        make_window(datetime(2024, 2, 1, tzinfo=UTC), fips="27053"),
    ]
    split = fixed_temporal_split(reversed(windows), split_config())
    assert {window.county_fips for window in split.holdout} == {"27031", "27053"}
    assert len(split.train) == 40
    assert _membership_sha256(split) == _membership_sha256(
        fixed_temporal_split(windows, split_config())
    )


def test_boundary_crossing_context_is_discarded_and_cannot_become_evaluation() -> None:
    boundary = make_window(datetime(2024, 1, 31, 23, 30, tzinfo=UTC))
    holdout = make_window(datetime(2024, 2, 1, tzinfo=UTC), fips="27053")
    split = fixed_temporal_split(
        enough_pre_holdout_windows() + [boundary, holdout], split_config()
    )
    assert split.discarded_boundary_windows == 1
    assert boundary not in split.train
    assert boundary not in split.holdout
    assert split.holdout == (holdout,)
    verify_temporal_holdout(split)


def test_temporal_verifier_rejects_train_eval_context_intersection() -> None:
    train = make_window(datetime(2024, 1, 31, 23, 30, tzinfo=UTC))
    holdout = make_window(datetime(2024, 2, 1, tzinfo=UTC))
    corrupt = TemporalSplit(
        train=(train,),
        holdout=(holdout,),
        candidate_train_windows=1,
        candidate_holdout_windows=1,
        discarded_boundary_windows=0,
        discarded_outside_interval_windows=0,
        holdout_start_utc="2024-02-01T00:00:00Z",
        holdout_end_utc="2024-02-29T23:45:00Z",
    )
    with pytest.raises(
        ValueError, match="training window reaches the fixed holdout interval"
    ):
        verify_temporal_holdout(corrupt)


def test_run_emits_fixed_bounds_timestamped_targets_and_deterministic_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = write_source(tmp_path / "eaglei.csv", fips_codes=("27031", "27053"))
    monkeypatch.setattr(
        experiment_module,
        "EXPECTED_EAGLEI_2024_SHA256",
        experiment_module.sha256_file(source),
    )
    config = split_config(max_windows=2_000)
    first = json.loads(
        run_experiment(
            source=source,
            output_dir=tmp_path / "first",
            county_fips=("27031", "27053"),
            config=config,
        ).read_text()
    )
    second = json.loads(
        run_experiment(
            source=source,
            output_dir=tmp_path / "second",
            county_fips=("27031", "27053"),
            config=config,
        ).read_text()
    )
    assert first["artifact_kind"] == EXPERIMENT_KIND
    assert first["split"]["strategy"] == "fixed_temporal_holdout_interval"
    assert first["split"]["holdout_start_utc"] == "2024-02-01T00:00:00Z"
    assert first["split"]["holdout_end_utc"] == "2024-02-29T23:45:00Z"
    assert first["split"]["membership_sha256"] == second["split"]["membership_sha256"]
    assert (
        first["split"]["train_time_bounds"]["target_end_utc"]
        < first["split"]["holdout_start_utc"]
    )
    assert (
        first["split"]["holdout_time_bounds"]["context_start_utc"]
        >= first["split"]["holdout_start_utc"]
    )
    assert (
        first["split"]["candidate_holdout_windows"] == first["split"]["holdout_windows"]
    )
    forecast = first["county_forecasts"][0]
    assert {
        "context_start_utc",
        "context_end_utc",
        "target_start_utc",
        "target_end_utc",
    } <= set(forecast)
    assert forecast["context_start_utc"] >= first["split"]["holdout_start_utc"]
    assert Path(first["weights"]["path"]).exists()


def test_pinned_production_source_refuses_an_unverified_csv(tmp_path: Path) -> None:
    source = write_source(tmp_path / "eaglei.csv")
    with pytest.raises(ValueError, match="pinned EAGLE-I 2024 source"):
        run_experiment(
            source=source,
            output_dir=tmp_path / "out",
            county_fips=("27031",),
            config=JepaConfig(epochs=1),
        )


def test_rejects_unequal_encoder_dimensions_before_source_processing(
    tmp_path: Path,
) -> None:
    source = tmp_path / "empty.csv"
    source.write_text(
        "fips_code,county,state,customers_out,run_start_time,total_customers\n"
    )
    with pytest.raises(ValueError, match="context_steps and target_steps must match"):
        run_experiment(
            source=source,
            output_dir=tmp_path / "out",
            config=JepaConfig(context_steps=2, target_steps=3),
        )


def test_production_holdout_interval_is_the_advertised_late_2024_quarter() -> None:
    """The interval the title, body and README advertise, pinned to the constants."""
    assert FIXED_HOLDOUT_START_UTC == "2024-10-01T00:00:00Z"
    assert FIXED_HOLDOUT_END_UTC == "2024-12-31T23:45:00Z"
    assert JepaConfig().holdout_start_utc == "2024-10-01T00:00:00Z"
    assert JepaConfig().holdout_end_utc == "2024-12-31T23:45:00Z"


def test_default_config_run_records_the_advertised_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that does NOT override the holdout must stamp 2024-10-01..2024-12-31."""
    source = write_source(
        tmp_path / "eaglei.csv",
        days=40,
        origin=datetime(2024, 9, 1, tzinfo=UTC),
    )
    monkeypatch.setattr(
        experiment_module,
        "EXPECTED_EAGLEI_2024_SHA256",
        experiment_module.sha256_file(source),
    )
    artifact = json.loads(
        run_experiment(
            source=source,
            output_dir=tmp_path / "out",
            county_fips=("27031",),
            config=JepaConfig(epochs=2),
        ).read_text()
    )
    assert artifact["split"]["holdout_start_utc"] == "2024-10-01T00:00:00Z"
    assert artifact["split"]["holdout_end_utc"] == "2024-12-31T23:45:00Z"
    assert artifact["split"]["holdout_windows"] > 0
    assert (
        artifact["split"]["train_time_bounds"]["target_end_utc"]
        < "2024-10-01T00:00:00Z"
    )
    assert (
        artifact["split"]["holdout_time_bounds"]["context_start_utc"]
        >= "2024-10-01T00:00:00Z"
    )
    assert artifact["config"]["holdout_start_utc"] == "2024-10-01T00:00:00Z"
    assert artifact["config"]["holdout_end_utc"] == "2024-12-31T23:45:00Z"


def test_split_runs_the_verifier_on_the_partition_it_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behavioural cover for the ``verify_temporal_holdout(split)`` CALL SITE.

    The budget step is replaced with one that smuggles a post-boundary window
    into ``train``. Nothing else in ``fixed_temporal_split`` inspects the
    partition after that point, so the only thing that can reject it is the
    verifier call. Removing the call makes this test return a leaking split.
    """
    leaking = make_window(datetime(2024, 2, 5, tzinfo=UTC), fips="27099")

    def smuggle(split: TemporalSplit, config: JepaConfig) -> TemporalSplit:
        return TemporalSplit(
            train=split.train + (leaking,),
            holdout=split.holdout,
            candidate_train_windows=split.candidate_train_windows,
            candidate_holdout_windows=split.candidate_holdout_windows,
            discarded_boundary_windows=split.discarded_boundary_windows,
            discarded_outside_interval_windows=split.discarded_outside_interval_windows,
            holdout_start_utc=split.holdout_start_utc,
            holdout_end_utc=split.holdout_end_utc,
        )

    monkeypatch.setattr(experiment_module, "_select_window_budget", smuggle)
    windows = enough_pre_holdout_windows() + [
        make_window(datetime(2024, 2, 1, tzinfo=UTC), fips="27053")
    ]
    with pytest.raises(
        ValueError, match="training window reaches the fixed holdout interval"
    ):
        fixed_temporal_split(windows, split_config())


def test_an_empty_fixed_holdout_is_refused() -> None:
    """An empty holdout satisfies every leakage check vacuously; refuse it."""
    with pytest.raises(ValueError, match="fixed temporal holdout is empty"):
        fixed_temporal_split(enough_pre_holdout_windows(), split_config())


def test_holdout_forecast_beats_the_best_possible_flat_forecast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A trajectory predictor must beat every constant, not merely persistence.

    ``best_constant_baseline_count_mae`` is the MAE of the median holdout count,
    the MAE-minimising constant. No flat forecast can score below it, so the
    margin is derived from the holdout data rather than hardcoded.
    """
    source = write_source(tmp_path / "eaglei.csv", days=45)
    monkeypatch.setattr(
        experiment_module,
        "EXPECTED_EAGLEI_2024_SHA256",
        experiment_module.sha256_file(source),
    )
    artifact = json.loads(
        run_experiment(
            source=source,
            output_dir=tmp_path / "out",
            county_fips=("27031",),
            config=split_config(epochs=40),
        ).read_text()
    )
    metrics = artifact["metrics"]
    assert metrics["holdout_count_mae"] < metrics["best_constant_baseline_count_mae"]
    for forecast in artifact["county_forecasts"]:
        distinct = {round(value, 3) for value in forecast["predicted_customers_out"]}
        assert len(distinct) > 1, "the decoded forecast is flat, not a trajectory"


def test_artifact_keeps_every_metric_and_disclosure_the_web_consumer_requires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``web/src/explainer/jepa/recordedEvaluation.ts`` fails closed without these."""
    source = write_source(tmp_path / "eaglei.csv", days=45)
    monkeypatch.setattr(
        experiment_module,
        "EXPECTED_EAGLEI_2024_SHA256",
        experiment_module.sha256_file(source),
    )
    artifact = json.loads(
        run_experiment(
            source=source,
            output_dir=tmp_path / "out",
            county_fips=("27031",),
            config=split_config(),
        ).read_text()
    )
    for name in (
        "holdout_count_mae",
        "holdout_count_rmse",
        "persistence_baseline_count_mae",
        "persistence_baseline_count_rmse",
        "holdout_embedding_mse",
        "train_count_mae",
        "train_to_holdout_count_mae_ratio",
        "best_constant_baseline_count_mae",
        "best_constant_baseline_count",
        "train_actual_count_std",
        "holdout_actual_count_std",
    ):
        assert isinstance(artifact["metrics"][name], float), name
    for name in (
        "county_window_counts",
        "window_stride_steps",
        "target_context_overlap_steps",
        "overlap_verification",
    ):
        assert name in artifact["split"], name
    assert artifact["split"]["target_context_overlap_steps"] == 0
    assert any("Regime asymmetry" in entry for entry in artifact["limitations"]), (
        "the train/holdout regime gap must stay disclosed"
    )

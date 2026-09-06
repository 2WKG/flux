from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from models.jepa import experiment as experiment_module
from models.jepa.experiment import (
    EXPERIMENT_KIND,
    STRATEGY_CHRONOLOGICAL,
    JepaConfig,
    Window,
    chronological_split,
    load_windows,
    run_experiment,
    verify_target_context_disjoint,
)

TEST_CONFIG = JepaConfig(epochs=3, max_windows=80)


def write_sawtooth_source(
    path: Path, *, fips: str = "27031", rows: int = 2_000
) -> Path:
    """A deterministic 15-minute sawtooth: a flat forecast is provably bad on it."""
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
        for index in range(rows):
            hour, minute = divmod(index * 15, 60)
            writer.writerow(
                {
                    "fips_code": fips,
                    "county": "Test",
                    "state": "Minnesota",
                    "customers_out": index % 17,
                    "run_start_time": f"2024-01-{1 + hour // 24:02d} {hour % 24:02d}:{minute:02d}:00",
                    "total_customers": "1000",
                }
            )
    return path


def stub_source(path: Path) -> Path:
    """A real (empty) file, so the artifact can still hash its source."""
    path.write_text(
        "fips_code,county,state,customers_out,run_start_time,total_customers\n"
    )
    return path


def make_windows(count: int, *, stride_steps: int, config: JepaConfig) -> list[Window]:
    """Synthesise a chronological corpus whose stride is caller-controlled."""
    origin = datetime.fromisoformat("2024-03-01T00:00:00")
    step = timedelta(minutes=experiment_module.CADENCE_MINUTES)
    windows: list[Window] = []
    for index in range(count):
        start = origin + step * (index * stride_steps)
        context_end = start + step * (config.context_steps - 1)
        windows.append(
            Window(
                county_fips="27031",
                county_name="Test",
                context_end_utc=context_end.isoformat() + "Z",
                context=tuple(
                    float((index + offset) % 17)
                    for offset in range(config.context_steps)
                ),
                target=tuple(
                    float((index + offset) % 17)
                    for offset in range(config.target_steps)
                ),
            )
        )
    return windows


def test_trains_jepa_and_marks_count_forecast_experimental(tmp_path: Path) -> None:
    source = write_sawtooth_source(tmp_path / "eaglei.csv")
    artifact_path = run_experiment(
        source=source,
        output_dir=tmp_path / "out",
        county_fips=("27031",),
        config=TEST_CONFIG,
    )
    artifact = json.loads(artifact_path.read_text())
    assert artifact["artifact_kind"] == EXPERIMENT_KIND
    assert artifact["status"] == "experimental"
    assert artifact["scope"]["observed_county_fips"] == ["27031"]
    assert artifact["scope"]["unavailable_county_fips"] == []
    assert artifact["split"]["holdout_windows"] > 0
    assert artifact["split"]["holdout_counties"] == ["27031"]
    assert artifact["split"]["target_context_overlap_steps"] == 0
    assert artifact["county_forecasts"][0]["county_name"] == "Test"
    assert len(artifact["county_forecasts"][0]["actual_customers_out"]) == 24
    assert Path(artifact["weights"]["path"]).exists()


def test_holdout_forecast_beats_the_best_possible_flat_forecast(tmp_path: Path) -> None:
    """A trajectory predictor must beat every constant, not merely persistence.

    ``best_constant_baseline_count_mae`` is the MAE of the median holdout count,
    which is the MAE-minimising constant.  No flat forecast can score below it,
    so this margin is derived from the holdout data rather than hardcoded.
    """
    source = write_sawtooth_source(tmp_path / "eaglei.csv")
    artifact = json.loads(
        run_experiment(
            source=source,
            output_dir=tmp_path / "out",
            county_fips=("27031",),
            config=TEST_CONFIG,
        ).read_text()
    )
    metrics = artifact["metrics"]
    assert metrics["holdout_count_mae"] < metrics["best_constant_baseline_count_mae"]
    assert metrics["holdout_count_mae"] < metrics["persistence_baseline_count_mae"]
    for forecast in artifact["county_forecasts"]:
        distinct = {round(value, 3) for value in forecast["predicted_customers_out"]}
        assert len(distinct) > 1, "the decoded forecast is flat, not a trajectory"


def test_split_strategy_is_read_off_the_actual_ordering(tmp_path: Path) -> None:
    source = write_sawtooth_source(tmp_path / "eaglei.csv")
    artifact = json.loads(
        run_experiment(
            source=source,
            output_dir=tmp_path / "out",
            county_fips=("27031",),
            config=TEST_CONFIG,
        ).read_text()
    )
    windows = load_windows(source, county_fips=("27031",), config=TEST_CONFIG)
    split = chronological_split(windows, TEST_CONFIG)
    assert artifact["split"]["strategy"] == split.strategy == STRATEGY_CHRONOLOGICAL
    assert (
        artifact["split"]["boundary_context_end_utc"] == split.boundary_context_end_utc
    )
    assert artifact["split"]["train_windows"] == len(split.train)
    assert artifact["split"]["holdout_windows"] == len(split.holdout)
    assert max(window.context_end_utc for window in split.train) < min(
        window.context_end_utc for window in split.holdout
    )


def test_run_experiment_refuses_a_shuffled_corpus(tmp_path: Path, monkeypatch) -> None:
    """Destroying chronology must stop the run, not relabel it as chronological."""
    windows = make_windows(60, stride_steps=48, config=TEST_CONFIG)
    shuffled = windows[30:] + windows[:30]
    monkeypatch.setattr(experiment_module, "load_windows", lambda *a, **k: shuffled)
    with pytest.raises(ValueError, match="not a chronological window split"):
        run_experiment(
            source=stub_source(tmp_path / "stub.csv"),
            output_dir=tmp_path / "out",
            county_fips=("27031",),
            config=TEST_CONFIG,
        )


def test_run_experiment_rejects_overlapping_windows(
    tmp_path: Path, monkeypatch
) -> None:
    """Exercises the ``verify_target_context_disjoint`` CALL SITE in run_experiment.

    The corpus is otherwise trainable (60 chronological windows), so if the call
    site were removed the run would succeed and this test would fail.
    """
    overlapping = make_windows(60, stride_steps=1, config=TEST_CONFIG)
    monkeypatch.setattr(experiment_module, "load_windows", lambda *a, **k: overlapping)
    with pytest.raises(ValueError, match="target/context overlap for county 27031"):
        run_experiment(
            source=stub_source(tmp_path / "stub.csv"),
            output_dir=tmp_path / "out",
            county_fips=("27031",),
            config=TEST_CONFIG,
        )
    # The same corpus at the real stride trains, so the failure above is the
    # overlap guard rather than a generally unusable corpus.
    monkeypatch.setattr(
        experiment_module,
        "load_windows",
        lambda *a, **k: make_windows(60, stride_steps=48, config=TEST_CONFIG),
    )
    run_experiment(
        source=stub_source(tmp_path / "stub.csv"),
        output_dir=tmp_path / "out",
        county_fips=("27031",),
        config=TEST_CONFIG,
    )


def test_requested_county_without_windows_is_recorded_unavailable(
    tmp_path: Path,
) -> None:
    source = write_sawtooth_source(tmp_path / "eaglei.csv")
    artifact = json.loads(
        run_experiment(
            source=source,
            output_dir=tmp_path / "out",
            county_fips=("27031", "27053"),
            config=TEST_CONFIG,
        ).read_text()
    )
    assert artifact["scope"]["observed_county_fips"] == ["27031"]
    assert [
        entry["county_fips"] for entry in artifact["scope"]["unavailable_county_fips"]
    ] == ["27053"]
    reason = artifact["scope"]["unavailable_county_fips"][0]["reason"]
    assert "no contiguous" in reason and "48-step" in reason


def test_limitations_are_disclosed_in_full_including_the_regime_gap(
    tmp_path: Path,
) -> None:
    source = write_sawtooth_source(tmp_path / "eaglei.csv")
    artifact = json.loads(
        run_experiment(
            source=source,
            output_dir=tmp_path / "out",
            county_fips=("27031",),
            config=TEST_CONFIG,
        ).read_text()
    )
    limitations = artifact["limitations"]
    assert len(limitations) == 6
    assert limitations[0] == "Experimental observed-count forecast only."
    assert (
        limitations[1] == "Not an outage probability or qualified outage-model result."
    )
    assert (
        limitations[2]
        == "No customer-normalized label, weather forecast, topology, or cascade inference."
    )
    assert (
        limitations[3]
        == "Forecast target is held-out historical EAGLE-I customers_out."
    )
    assert limitations[4].startswith("A persistence baseline is recorded")
    metrics = artifact["metrics"]
    regime = limitations[5]
    assert regime.startswith("Regime asymmetry:")
    assert f"{metrics['train_count_mae']:.2f}" in regime
    assert f"{metrics['holdout_count_mae']:.2f}" in regime
    assert f"{metrics['train_to_holdout_count_mae_ratio']:.1f}x" in regime
    assert f"{metrics['train_actual_count_std']:.2f}" in regime
    assert f"{metrics['holdout_actual_count_std']:.2f}" in regime


def test_window_stride_keeps_targets_out_of_later_contexts(tmp_path: Path) -> None:
    source = write_sawtooth_source(tmp_path / "eaglei.csv")
    verify_target_context_disjoint(
        load_windows(source, county_fips=("27031",), config=TEST_CONFIG), TEST_CONFIG
    )


def test_rejects_unequal_encoder_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "empty.csv"
    source.write_text(
        "fips_code,county,state,customers_out,run_start_time,total_customers\n"
    )
    with pytest.raises(ValueError, match="context_steps and target_steps must match"):
        run_experiment(
            source=source,
            output_dir=tmp_path / "out",
            config=JepaConfig(context_steps=12, target_steps=24),
        )

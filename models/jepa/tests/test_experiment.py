from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from models.jepa import experiment as experiment_module
from models.jepa.experiment import (
    EXPERIMENT_KIND,
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
    path: Path, *, fips_codes: tuple[str, ...] = ("27031",), days: int = 75
) -> Path:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
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

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from models.jepa.experiment import (
    EXPERIMENT_KIND,
    JepaConfig,
    load_windows,
    run_experiment,
    verify_target_context_disjoint,
)


def test_trains_jepa_and_marks_count_forecast_experimental(tmp_path: Path) -> None:
    source = tmp_path / "eaglei.csv"
    with source.open("w", newline="") as handle:
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
        for index in range(2_000):
            hour, minute = divmod(index * 15, 60)
            writer.writerow(
                {
                    "fips_code": "27031",
                    "county": "Test",
                    "state": "Minnesota",
                    "customers_out": index % 17,
                    "run_start_time": f"2024-01-{1 + hour // 24:02d} {hour % 24:02d}:{minute:02d}:00",
                    "total_customers": "1000",
                }
            )
    artifact_path = run_experiment(
        source=source,
        output_dir=tmp_path / "out",
        county_fips=("27031",),
        config=JepaConfig(epochs=3, max_windows=80),
    )
    artifact = json.loads(artifact_path.read_text())
    assert artifact["artifact_kind"] == EXPERIMENT_KIND
    assert artifact["status"] == "experimental"
    assert artifact["scope"]["observed_county_fips"] == ["27031"]
    assert artifact["split"]["holdout_windows"] > 0
    assert artifact["split"]["holdout_counties"] == ["27031"]
    assert artifact["split"]["target_context_overlap_steps"] == 0
    assert "persistence_baseline_count_mae" in artifact["metrics"]
    assert artifact["county_forecasts"][0]["county_name"] == "Test"
    assert len(artifact["county_forecasts"][0]["actual_customers_out"]) == 24
    assert "outage probability" in " ".join(artifact["limitations"]).lower()
    assert Path(artifact["weights"]["path"]).exists()
    verify_target_context_disjoint(
        load_windows(source, county_fips=("27031",), config=JepaConfig(max_windows=80)),
        JepaConfig(max_windows=80),
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

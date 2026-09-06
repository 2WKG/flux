"""Artifact-only tests for the supplemental JEPA demo card loader."""

from __future__ import annotations

import json
from pathlib import Path

from copilot.demo.jepa import read_experimental_jepa_forecast


def _artifact() -> dict[str, object]:
    return {
        "artifact_kind": "experimental_jepa_count_forecast",
        "status": "experimental",
        "model_version": "jepa-count-v1",
        "source": {
            "path": "eaglei.json",
            "sha256": "a" * 64,
            "provider": "EAGLE-I",
            "year": 2024,
        },
        "scope": {"observed_county_fips": ["27053"]},
        "split": {"strategy": "chronological_by_window"},
        "metrics": {"holdout_count_mae": 1.0},
        "forecast": {
            "county_fips": "27053",
            "predicted_customers_out": [1, 2],
            "actual_customers_out": [2, 3],
        },
        "limitations": [
            "Observed historical count forecast only.",
            "Not a cascade prediction.",
        ],
    }


def _write(path: Path, value: dict[str, object]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_loader_preserves_the_experimental_artifact_and_its_named_provenance(tmp_path: Path) -> None:
    result = read_experimental_jepa_forecast(_write(tmp_path / "jepa.json", _artifact()))

    assert result.status == "available"
    assert result.label == "Experimental observed-count trajectory forecast"
    assert result.data["forecast"] == _artifact()["forecast"]
    assert result.provenance[0] == f"artifact:jepa:{'a' * 16}"
    assert result.limitations == (
        "Observed historical count forecast only.",
        "Not a cascade prediction.",
    )


def test_loader_rejects_county_outside_observed_coverage(tmp_path: Path) -> None:
    result = read_experimental_jepa_forecast(
        _write(tmp_path / "jepa.json", _artifact()), county_fips="27031"
    )

    assert result.status == "unavailable"
    assert result.reason == "No experimental JEPA forecast is available for the selected county."


def test_loader_selects_a_county_forecast_from_the_final_artifact_shape(tmp_path: Path) -> None:
    artifact = _artifact()
    artifact["scope"] = {"observed_county_fips": ["27053", "48201"]}
    artifact["county_forecasts"] = [
        artifact["forecast"],
        {
            "county_fips": "48201",
            "predicted_customers_out": [4, 5],
            "actual_customers_out": [5, 6],
        },
    ]
    result = read_experimental_jepa_forecast(
        _write(tmp_path / "jepa.json", artifact), county_fips="48201"
    )

    assert result.status == "available"
    assert result.data["forecast"]["county_fips"] == "48201"


def test_loader_rejects_bad_artifact_instead_of_creating_a_forecast(tmp_path: Path) -> None:
    artifact = _artifact()
    artifact["forecast"] = {"county_fips": "27053", "predicted_counts": [1]}
    result = read_experimental_jepa_forecast(_write(tmp_path / "jepa.json", artifact))

    assert result.status == "unavailable"
    assert result.reason == "The JEPA artifact has invalid forecast count arrays."

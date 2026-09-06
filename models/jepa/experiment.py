"""A small, reproducible joint-embedding predictive architecture.

The context encoder maps an observed 15-minute outage-count history to a latent
space.  A predictor maps that context embedding to the future embedding made by
an exponential-moving-average target encoder.  The target encoder is
stop-gradient, so this is a JEPA objective rather than a count regression.
After fitting it, a linear probe decodes the predicted embedding into count
trajectories for an explicitly chronological held-out window.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np

EXPERIMENT_KIND = "experimental_jepa_count_forecast"
CADENCE_MINUTES = 15


@dataclass(frozen=True)
class JepaConfig:
    context_steps: int = 24
    target_steps: int = 24
    embedding_dim: int = 12
    epochs: int = 80
    learning_rate: float = 0.02
    ema_momentum: float = 0.97
    holdout_fraction: float = 0.2
    max_windows: int = 2400
    seed: int = 7


@dataclass(frozen=True)
class Window:
    county_fips: str
    county_name: str
    context_end_utc: str
    context: tuple[float, ...]
    target: tuple[float, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_windows(
    source: Path,
    *,
    county_fips: Iterable[str],
    config: JepaConfig,
) -> list[Window]:
    """Stream verified EAGLE-I CSV rows into contiguous county trajectories."""
    selected = set(county_fips)
    series: dict[str, list[tuple[datetime, float]]] = {fips: [] for fips in selected}
    county_names: dict[str, str] = {}
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            fips = row["fips_code"].zfill(5)
            if fips not in selected:
                continue
            county_names.setdefault(fips, row["county"].strip())
            value = row["customers_out"]
            if value == "":
                continue
            try:
                timestamp = datetime.fromisoformat(row["run_start_time"])
                count = float(value)
            except ValueError:
                continue
            if count < 0:
                continue
            series[fips].append((timestamp, count))

    size = config.context_steps + config.target_steps
    windows: list[Window] = []
    for fips in sorted(series):
        values = sorted(series[fips])
        # The target of one example must never reappear in a later example's
        # context.  A stride of the full context+target span makes that
        # guarantee structural rather than an after-the-fact split filter.
        for start in range(0, len(values) - size + 1, size):
            segment = values[start : start + size]
            if any(
                (right[0] - left[0]).total_seconds() != CADENCE_MINUTES * 60
                for left, right in pairwise(segment)
            ):
                continue
            context = tuple(item[1] for item in segment[: config.context_steps])
            target = tuple(item[1] for item in segment[config.context_steps :])
            windows.append(
                Window(
                    county_fips=fips,
                    county_name=county_names[fips],
                    context_end_utc=segment[config.context_steps - 1][0].isoformat()
                    + "Z",
                    context=context,
                    target=target,
                )
            )
    windows.sort(key=lambda item: (item.context_end_utc, item.county_fips))
    return windows[: config.max_windows]


def _normalise(
    windows: list[Window], train_count: int
) -> tuple[np.ndarray, np.ndarray, float, float]:
    train_values = np.asarray(
        [
            value
            for window in windows[:train_count]
            for value in (*window.context, *window.target)
        ],
        dtype=np.float64,
    )
    mean = float(np.log1p(train_values).mean())
    scale = float(np.log1p(train_values).std()) or 1.0
    context = np.asarray([window.context for window in windows], dtype=np.float64)
    target = np.asarray([window.target for window in windows], dtype=np.float64)
    return (
        (np.log1p(context) - mean) / scale,
        (np.log1p(target) - mean) / scale,
        mean,
        scale,
    )


def verify_target_context_disjoint(windows: list[Window], config: JepaConfig) -> None:
    """Reject a corpus if a target timestamp can enter a later context."""
    target_duration = timedelta(minutes=config.target_steps * CADENCE_MINUTES)
    context_duration = timedelta(minutes=(config.context_steps - 1) * CADENCE_MINUTES)
    for fips in {window.county_fips for window in windows}:
        county_windows = sorted(
            (window for window in windows if window.county_fips == fips),
            key=lambda window: window.context_end_utc,
        )
        for earlier, later in pairwise(county_windows):
            earlier_target_end = (
                datetime.fromisoformat(earlier.context_end_utc.removesuffix("Z"))
                + target_duration
            )
            later_context_start = (
                datetime.fromisoformat(later.context_end_utc.removesuffix("Z"))
                - context_duration
            )
            if earlier_target_end >= later_context_start:
                raise ValueError(f"target/context overlap for county {fips}")


def run_experiment(
    *,
    source: Path,
    output_dir: Path,
    county_fips: tuple[str, ...] = ("27031", "27053", "48201", "48453"),
    config: JepaConfig | None = None,
    source_reference: str | None = None,
) -> Path:
    """Train the bounded numpy JEPA and write an inspectable artifact + weights."""
    config = config or JepaConfig()
    if config.context_steps != config.target_steps:
        raise ValueError(
            "context_steps and target_steps must match because the EMA target encoder "
            "copies context-encoder weights"
        )
    windows = load_windows(source, county_fips=county_fips, config=config)
    verify_target_context_disjoint(windows, config)
    if len(windows) < 40:
        raise ValueError(f"need at least 40 contiguous windows; found {len(windows)}")
    train_count = max(1, int(len(windows) * (1 - config.holdout_fraction)))
    if train_count >= len(windows):
        raise ValueError("chronological holdout is empty")
    x, y, mean, scale = _normalise(windows, train_count)
    x_train, y_train, x_hold, y_hold = (
        x[:train_count],
        y[:train_count],
        x[train_count:],
        y[train_count:],
    )
    rng = np.random.default_rng(config.seed)
    context_encoder = rng.normal(0, 0.12, (config.context_steps, config.embedding_dim))
    target_encoder = context_encoder.copy()
    predictor = rng.normal(0, 0.12, (config.embedding_dim, config.embedding_dim))

    for _ in range(config.epochs):
        context = x_train @ context_encoder
        target = y_train @ target_encoder  # stop-gradient target branch
        predicted = context @ predictor
        error = (predicted - target) / len(x_train)
        grad_predictor = context.T @ error * 2
        grad_context = x_train.T @ (error @ predictor.T) * 2
        predictor -= config.learning_rate * grad_predictor
        context_encoder -= config.learning_rate * grad_context
        target_encoder = (
            config.ema_momentum * target_encoder
            + (1 - config.ema_momentum) * context_encoder[: config.target_steps]
        )

    train_embedding = (x_train @ context_encoder) @ predictor
    hold_embedding = (x_hold @ context_encoder) @ predictor
    probe = (
        np.linalg.pinv(np.c_[train_embedding, np.ones(len(train_embedding))]) @ y_train
    )
    train_decoded = train_embedding @ probe[:-1] + probe[-1]
    hold_decoded = hold_embedding @ probe[:-1] + probe[-1]
    predicted_counts = np.maximum(np.expm1(hold_decoded * scale + mean), 0)
    actual_counts = np.maximum(np.expm1(y_hold * scale + mean), 0)
    persistence_counts = np.asarray(
        [window.context[-1] for window in windows[train_count:]], dtype=np.float64
    )[:, None]
    persistence_counts = np.repeat(persistence_counts, config.target_steps, axis=1)
    embedding_mse = float(np.mean((hold_embedding - y_hold @ target_encoder) ** 2))
    count_mae = float(np.mean(np.abs(predicted_counts - actual_counts)))
    count_rmse = float(math.sqrt(np.mean((predicted_counts - actual_counts) ** 2)))
    persistence_mae = float(np.mean(np.abs(persistence_counts - actual_counts)))
    persistence_rmse = float(
        math.sqrt(np.mean((persistence_counts - actual_counts) ** 2))
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    weights_path = output_dir / "jepa_count_forecast_weights.npz"
    np.savez(
        weights_path,
        context_encoder=context_encoder,
        target_encoder=target_encoder,
        predictor=predictor,
        probe=probe,
    )

    def forecast_at(index: int) -> dict[str, object]:
        window = windows[train_count + index]
        return {
            "county_fips": window.county_fips,
            "county_name": window.county_name,
            "context_end_utc": window.context_end_utc,
            "horizon_minutes": config.target_steps * CADENCE_MINUTES,
            "predicted_customers_out": [
                round(float(value), 3) for value in predicted_counts[index]
            ],
            "actual_customers_out": [
                round(float(value), 3) for value in actual_counts[index]
            ],
        }

    selected_holdout_indexes: dict[str, int] = {}
    for index, window in enumerate(windows[train_count:]):
        selected_holdout_indexes.setdefault(window.county_fips, index)
    county_forecasts = [
        forecast_at(selected_holdout_indexes[fips])
        for fips in sorted(selected_holdout_indexes)
    ]
    exemplar = 0
    artifact = {
        "artifact_kind": EXPERIMENT_KIND,
        "status": "experimental",
        "model_version": "numpy-jepa-count-v1",
        "architecture": {
            "context_encoder": "linear context encoder",
            "target_encoder": "EMA target encoder with stop-gradient",
            "predictor": "latent-to-latent linear predictor",
            "objective": "mean squared predicted-vs-target embedding error",
        },
        "source": {
            "path": source_reference or str(source),
            "sha256": sha256_file(source),
            "provider": "ORNL EAGLE-I",
            "year": 2024,
        },
        "scope": {
            "requested_county_fips": list(county_fips),
            "observed_county_fips": sorted({window.county_fips for window in windows}),
            "cadence_minutes": CADENCE_MINUTES,
            "context_steps": config.context_steps,
            "target_steps": config.target_steps,
        },
        "split": {
            "strategy": "chronological window split",
            "window_stride_steps": config.context_steps + config.target_steps,
            "target_context_overlap_steps": 0,
            "overlap_verification": "Each county advances by the full context-plus-target span; no target timestamp is reused as any later context timestamp.",
            "train_windows": train_count,
            "holdout_windows": len(windows) - train_count,
            "train_counties": sorted(
                {window.county_fips for window in windows[:train_count]}
            ),
            "holdout_counties": sorted(
                {window.county_fips for window in windows[train_count:]}
            ),
            "county_window_counts": {
                fips: sum(window.county_fips == fips for window in windows)
                for fips in sorted({window.county_fips for window in windows})
            },
        },
        "metrics": {
            "holdout_embedding_mse": embedding_mse,
            "holdout_count_mae": count_mae,
            "holdout_count_rmse": count_rmse,
            "persistence_baseline_count_mae": persistence_mae,
            "persistence_baseline_count_rmse": persistence_rmse,
            "train_count_mae": float(
                np.mean(
                    np.abs(
                        np.maximum(np.expm1(train_decoded * scale + mean), 0)
                        - np.maximum(np.expm1(y_train * scale + mean), 0)
                    )
                )
            ),
        },
        "forecast": forecast_at(exemplar),
        "county_forecasts": county_forecasts,
        "weights": {"path": str(weights_path), "sha256": sha256_file(weights_path)},
        "config": asdict(config),
        "limitations": [
            "Experimental observed-count forecast only.",
            "Not an outage probability or qualified outage-model result.",
            "No customer-normalized label, weather forecast, topology, or cascade inference.",
            "Forecast target is held-out historical EAGLE-I customers_out.",
            "A persistence baseline is recorded for comparison; experimental metrics do not establish operational usefulness.",
        ],
    }
    artifact_path = output_dir / "jepa_count_forecast_artifact.json"
    artifact_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return artifact_path

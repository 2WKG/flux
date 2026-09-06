"""A small, reproducible JEPA for historical EAGLE-I count trajectories.

This module evaluates a fixed late-2024 interval. It does not turn a row count,
county ordering, storm label, or contingency label into a split.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import numpy as np

EXPERIMENT_KIND = "experimental_jepa_count_forecast"
CADENCE_MINUTES = 15
EXPECTED_EAGLEI_2024_SHA256 = (
    "d5d75ea4ef3943446aaf0623e9b451cb4e7796d20cc379de9cf497106ebab2e6"
)
FIXED_HOLDOUT_START_UTC = "2024-10-01T00:00:00Z"
FIXED_HOLDOUT_END_UTC = "2024-12-31T23:45:00Z"
SPLIT_STRATEGY = "fixed_temporal_holdout_interval"


@dataclass(frozen=True)
class JepaConfig:
    context_steps: int = 24
    target_steps: int = 24
    embedding_dim: int = 12
    epochs: int = 80
    learning_rate: float = 0.02
    ema_momentum: float = 0.97
    max_windows: int | None = 2400
    seed: int = 7
    holdout_start_utc: str = FIXED_HOLDOUT_START_UTC
    holdout_end_utc: str = FIXED_HOLDOUT_END_UTC


@dataclass(frozen=True)
class Window:
    county_fips: str
    county_name: str
    context_start_utc: str
    context_end_utc: str
    target_start_utc: str
    target_end_utc: str
    context: tuple[float, ...]
    target: tuple[float, ...]


@dataclass(frozen=True)
class TemporalSplit:
    train: tuple[Window, ...]
    holdout: tuple[Window, ...]
    candidate_train_windows: int
    candidate_holdout_windows: int
    discarded_boundary_windows: int
    discarded_outside_interval_windows: int
    holdout_start_utc: str
    holdout_end_utc: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _window_time(window: Window, field: str) -> datetime:
    return _parse_utc(getattr(window, field))


def load_windows(
    source: Path, *, county_fips: Iterable[str], config: JepaConfig
) -> list[Window]:
    """Read contiguous, non-overlapping county trajectories from an EAGLE-I CSV."""
    selected = set(county_fips)
    series: dict[str, list[tuple[datetime, float]]] = {fips: [] for fips in selected}
    county_names: dict[str, str] = {}
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            fips = row["fips_code"].zfill(5)
            if fips not in selected or row["customers_out"] == "":
                continue
            try:
                timestamp = _parse_utc(row["run_start_time"])
                count = float(row["customers_out"])
            except (TypeError, ValueError):
                continue
            if count < 0:
                continue
            county_names.setdefault(fips, row["county"].strip())
            series[fips].append((timestamp, count))

    size = config.context_steps + config.target_steps
    cadence = timedelta(minutes=CADENCE_MINUTES)
    windows: list[Window] = []
    for fips in sorted(series):
        values = sorted(series[fips])
        # Full-span stride makes within-county examples disjoint. The split is
        # nevertheless global: tied timestamps across counties use time only.
        for start in range(0, len(values) - size + 1, size):
            segment = values[start : start + size]
            if any(right[0] - left[0] != cadence for left, right in pairwise(segment)):
                continue
            context_end_index = config.context_steps - 1
            windows.append(
                Window(
                    county_fips=fips,
                    county_name=county_names[fips],
                    context_start_utc=_format_utc(segment[0][0]),
                    context_end_utc=_format_utc(segment[context_end_index][0]),
                    target_start_utc=_format_utc(segment[config.context_steps][0]),
                    target_end_utc=_format_utc(segment[-1][0]),
                    context=tuple(item[1] for item in segment[: config.context_steps]),
                    target=tuple(item[1] for item in segment[config.context_steps :]),
                )
            )
    return sorted(windows, key=lambda item: (item.context_start_utc, item.county_fips))


def _select_window_budget(split: TemporalSplit, config: JepaConfig) -> TemporalSplit:
    """Cap the corpus without ever dropping fixed-interval evaluation windows."""
    if config.max_windows is None:
        return split
    if config.max_windows <= 0:
        raise ValueError("max_windows must be positive or None")
    if len(split.holdout) >= config.max_windows:
        raise ValueError(
            "holdout interval consumes max_windows; increase the limit so training is retained"
        )
    return TemporalSplit(
        train=split.train[-(config.max_windows - len(split.holdout)) :],
        holdout=split.holdout,
        candidate_train_windows=split.candidate_train_windows,
        candidate_holdout_windows=split.candidate_holdout_windows,
        discarded_boundary_windows=split.discarded_boundary_windows,
        discarded_outside_interval_windows=split.discarded_outside_interval_windows,
        holdout_start_utc=split.holdout_start_utc,
        holdout_end_utc=split.holdout_end_utc,
    )


def fixed_temporal_split(
    windows: Iterable[Window], config: JepaConfig
) -> TemporalSplit:
    """Assign fully pre-interval train and fully in-interval evaluation windows.

    Evaluation contexts are embargoed from pre-holdout observations. A window
    crossing the boundary is discarded rather than relabelled as evaluation.
    """
    holdout_start = _parse_utc(config.holdout_start_utc)
    holdout_end = _parse_utc(config.holdout_end_utc)
    if holdout_start > holdout_end:
        raise ValueError("holdout_start_utc must be on or before holdout_end_utc")
    train: list[Window] = []
    holdout: list[Window] = []
    boundary = outside = 0
    for window in windows:
        context_start = _window_time(window, "context_start_utc")
        target_end = _window_time(window, "target_end_utc")
        if target_end < holdout_start:
            train.append(window)
        elif context_start >= holdout_start and target_end <= holdout_end:
            holdout.append(window)
        elif context_start < holdout_start <= target_end:
            boundary += 1
        else:
            outside += 1
    split = TemporalSplit(
        train=tuple(
            sorted(train, key=lambda item: (item.context_start_utc, item.county_fips))
        ),
        holdout=tuple(
            sorted(holdout, key=lambda item: (item.context_start_utc, item.county_fips))
        ),
        candidate_train_windows=len(train),
        candidate_holdout_windows=len(holdout),
        discarded_boundary_windows=boundary,
        discarded_outside_interval_windows=outside,
        holdout_start_utc=_format_utc(holdout_start),
        holdout_end_utc=_format_utc(holdout_end),
    )
    split = _select_window_budget(split, config)
    verify_temporal_holdout(split)
    if len(split.train) < 40:
        raise ValueError(
            f"need at least 40 pre-holdout training windows; found {len(split.train)}"
        )
    if not split.holdout:
        raise ValueError("fixed temporal holdout is empty")
    return split


def verify_temporal_holdout(split: TemporalSplit) -> None:
    """Fail closed unless every train and evaluation timestamp is disjoint."""
    holdout_start = _parse_utc(split.holdout_start_utc)
    holdout_end = _parse_utc(split.holdout_end_utc)
    for window in split.train:
        if _window_time(window, "target_end_utc") >= holdout_start:
            raise ValueError("training window reaches the fixed holdout interval")
    for window in split.holdout:
        if _window_time(window, "context_start_utc") < holdout_start:
            raise ValueError("evaluation context crosses the fixed holdout boundary")
        if _window_time(window, "target_end_utc") > holdout_end:
            raise ValueError("evaluation target exceeds the fixed holdout interval")
    for train_window in split.train:
        for holdout_window in split.holdout:
            if _window_time(train_window, "context_start_utc") <= _window_time(
                holdout_window, "target_end_utc"
            ) and _window_time(holdout_window, "context_start_utc") <= _window_time(
                train_window, "target_end_utc"
            ):
                raise ValueError("training and evaluation windows share a timestamp")


def _membership_sha256(split: TemporalSplit) -> str:
    members = [
        {
            "partition": partition,
            "county_fips": window.county_fips,
            "context_start_utc": window.context_start_utc,
            "context_end_utc": window.context_end_utc,
            "target_start_utc": window.target_start_utc,
            "target_end_utc": window.target_end_utc,
        }
        for partition, windows in (("train", split.train), ("holdout", split.holdout))
        for window in windows
    ]
    return hashlib.sha256(
        json.dumps(members, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _bounds(windows: tuple[Window, ...]) -> dict[str, str] | None:
    if not windows:
        return None
    return {
        field: (min if field.endswith("start_utc") else max)(
            getattr(window, field) for window in windows
        )
        for field in (
            "context_start_utc",
            "context_end_utc",
            "target_start_utc",
            "target_end_utc",
        )
    }


def _normalise(
    train: tuple[Window, ...], all_windows: tuple[Window, ...]
) -> tuple[np.ndarray, np.ndarray, float, float]:
    train_values = np.asarray(
        [value for window in train for value in (*window.context, *window.target)],
        dtype=np.float64,
    )
    mean = float(np.log1p(train_values).mean())
    scale = float(np.log1p(train_values).std()) or 1.0
    context = np.asarray([window.context for window in all_windows], dtype=np.float64)
    target = np.asarray([window.target for window in all_windows], dtype=np.float64)
    return (
        (np.log1p(context) - mean) / scale,
        (np.log1p(target) - mean) / scale,
        mean,
        scale,
    )


def run_experiment(
    *,
    source: Path,
    output_dir: Path,
    county_fips: tuple[str, ...] = ("27031", "27053", "48201", "48453"),
    config: JepaConfig | None = None,
    source_reference: str | None = None,
) -> Path:
    """Train the bounded numpy JEPA and emit fresh weights plus an artifact."""
    config = config or JepaConfig()
    if config.context_steps != config.target_steps:
        raise ValueError(
            "context_steps and target_steps must match because the EMA target encoder copies context-encoder weights"
        )
    source_sha256 = sha256_file(source)
    if source_sha256 != EXPECTED_EAGLEI_2024_SHA256:
        raise ValueError("source SHA-256 does not match the pinned EAGLE-I 2024 source")
    split = fixed_temporal_split(
        load_windows(source, county_fips=county_fips, config=config), config
    )
    all_windows = split.train + split.holdout
    x, y, mean, scale = _normalise(split.train, all_windows)
    train_count = len(split.train)
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
        target = y_train @ target_encoder
        error = (context @ predictor - target) / len(x_train)
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
    persistence_counts = np.repeat(
        np.asarray([window.context[-1] for window in split.holdout])[:, None],
        config.target_steps,
        axis=1,
    )
    metrics = {
        "holdout_embedding_mse": float(
            np.mean((hold_embedding - y_hold @ target_encoder) ** 2)
        ),
        "holdout_count_mae": float(np.mean(np.abs(predicted_counts - actual_counts))),
        "holdout_count_rmse": float(
            math.sqrt(np.mean((predicted_counts - actual_counts) ** 2))
        ),
        "persistence_baseline_count_mae": float(
            np.mean(np.abs(persistence_counts - actual_counts))
        ),
        "persistence_baseline_count_rmse": float(
            math.sqrt(np.mean((persistence_counts - actual_counts) ** 2))
        ),
        "train_count_mae": float(
            np.mean(
                np.abs(
                    np.maximum(np.expm1(train_decoded * scale + mean), 0)
                    - np.maximum(np.expm1(y_train * scale + mean), 0)
                )
            )
        ),
    }
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
        window = split.holdout[index]
        return {
            "county_fips": window.county_fips,
            "county_name": window.county_name,
            "context_start_utc": window.context_start_utc,
            "context_end_utc": window.context_end_utc,
            "target_start_utc": window.target_start_utc,
            "target_end_utc": window.target_end_utc,
            "horizon_minutes": config.target_steps * CADENCE_MINUTES,
            "predicted_customers_out": [
                round(float(value), 3) for value in predicted_counts[index]
            ],
            "actual_customers_out": [
                round(float(value), 3) for value in actual_counts[index]
            ],
        }

    selected_holdout_indexes: dict[str, int] = {}
    for index, window in enumerate(split.holdout):
        selected_holdout_indexes.setdefault(window.county_fips, index)
    observed_county_fips = sorted({window.county_fips for window in all_windows})
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
            "sha256": source_sha256,
            "expected_sha256": EXPECTED_EAGLEI_2024_SHA256,
            "provider": "ORNL EAGLE-I",
            "year": 2024,
        },
        "scope": {
            "requested_county_fips": list(county_fips),
            "observed_county_fips": observed_county_fips,
            "unavailable_county_fips": [
                {
                    "county_fips": fips,
                    "reason": f"no contiguous {config.context_steps + config.target_steps}-step {CADENCE_MINUTES}-minute window in the source",
                }
                for fips in county_fips
                if fips not in observed_county_fips
            ],
            "cadence_minutes": CADENCE_MINUTES,
            "context_steps": config.context_steps,
            "target_steps": config.target_steps,
        },
        "split": {
            "strategy": SPLIT_STRATEGY,
            "holdout_start_utc": split.holdout_start_utc,
            "holdout_end_utc": split.holdout_end_utc,
            "membership_rule": "train target_end_utc < holdout_start_utc; evaluation context_start_utc >= holdout_start_utc and target_end_utc <= holdout_end_utc",
            "context_embargo": "boundary-crossing evaluation contexts are discarded; no timestamp appears in both train and evaluation windows",
            "train_windows": len(split.train),
            "holdout_windows": len(split.holdout),
            "candidate_train_windows": split.candidate_train_windows,
            "candidate_holdout_windows": split.candidate_holdout_windows,
            "discarded_boundary_windows": split.discarded_boundary_windows,
            "discarded_outside_interval_windows": split.discarded_outside_interval_windows,
            "train_time_bounds": _bounds(split.train),
            "holdout_time_bounds": _bounds(split.holdout),
            "membership_sha256": _membership_sha256(split),
            "train_counties": sorted({window.county_fips for window in split.train}),
            "holdout_counties": sorted(
                {window.county_fips for window in split.holdout}
            ),
        },
        "metrics": metrics,
        "forecast": forecast_at(0),
        "county_forecasts": [
            forecast_at(selected_holdout_indexes[fips])
            for fips in sorted(selected_holdout_indexes)
        ],
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

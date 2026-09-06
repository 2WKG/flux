"""Train-membership-bound normalization for raw graph-export features."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from gnn.contracts import SamplingError
from gnn.sampler import canonical_json

NORMALIZATION_SCHEMA_VERSION = "gnn-training-normalization/v1"


def fit_graph_normalization(
    graph_dir: Path, graph_dataset: dict[str, Any], split: dict[str, Any]
) -> dict[str, Any]:
    """Fit raw graph features once, binding the result to train membership.

    Topology features are static and appear in every graph input, so scanning
    them once is equivalent to scanning their copies in all training samples.
    The receipt proves that no held-out sample joined the fitting corpus.
    """
    train_ids = _sample_ids(split, "train_sample_ids")
    held_out_ids = _sample_ids(split, "held_out_sample_ids", allow_empty=True)
    if set(train_ids).intersection(held_out_ids):
        raise SamplingError("normalization fit and held-out sample IDs overlap")
    return {
        "schema_version": NORMALIZATION_SCHEMA_VERSION,
        "graph_dataset": dict(graph_dataset),
        "fit_partition": "train",
        "fit_sample_ids": train_ids,
        "fit_sample_ids_sha256": _membership_hash(train_ids),
        "excluded_partitions": {"held_out": held_out_ids},
        "evaluation_policy": "reuse this receipt; never refit normalization during evaluation",
        "feature_scope": (
            "static raw graph features repeated in every training sample; each feature is "
            "scanned once after train membership is fixed"
        ),
        "statistics": {
            "node_features": feature_statistics(
                _read_rows(graph_dir / "nodes.json", "nodes")
            ),
            "edge_features": feature_statistics(
                _read_rows(graph_dir / "edges.json", "edges")
            ),
        },
    }


def normalize_feature_value(
    value: float | None, statistic: dict[str, float | int]
) -> float | None:
    """Apply persisted train statistics to train or held-out features."""
    if value is None:
        return None
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise SamplingError("cannot normalize a non-finite graph feature")
    mean, stddev = float(statistic["mean"]), float(statistic["stddev"])
    if not math.isfinite(mean) or not math.isfinite(stddev) or stddev < 0:
        raise SamplingError("normalization statistic is invalid")
    return 0.0 if stddev == 0 else (float(value) - mean) / stddev


def feature_statistics(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    """Compute finite numeric statistics without imputing JSON null values."""
    values_by_feature: dict[str, list[float]] = {}
    for row in rows:
        features = row.get("features")
        if not isinstance(features, dict):
            raise SamplingError("training graph row has no feature object")
        for feature, value in features.items():
            if value is None:
                continue
            if not isinstance(feature, str) or isinstance(value, bool):
                raise SamplingError(
                    "training graph feature has an invalid numeric value"
                )
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise SamplingError(
                    "training graph feature has an invalid numeric value"
                ) from exc
            if not math.isfinite(number):
                raise SamplingError("training graph feature must be finite or null")
            values_by_feature.setdefault(feature, []).append(number)
    return {
        feature: _statistics(values)
        for feature, values in sorted(values_by_feature.items())
    }


def _statistics(values: list[float]) -> dict[str, float | int]:
    count = len(values)
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / count
    return {
        "count": count,
        "mean": mean,
        "stddev": variance**0.5,
        "min": min(values),
        "max": max(values),
    }


def _sample_ids(
    split: dict[str, Any], key: str, *, allow_empty: bool = False
) -> list[str]:
    values = split.get(key)
    if (
        not isinstance(values, list)
        or (not allow_empty and not values)
        or not all(isinstance(value, str) for value in values)
    ):
        qualifier = "non-empty " if not allow_empty else ""
        raise SamplingError(f"normalization requires {qualifier}{key}")
    if len(values) != len(set(values)):
        raise SamplingError(f"normalization {key} contains duplicates")
    return sorted(values)


def _membership_hash(sample_ids: list[str]) -> str:
    return hashlib.sha256(canonical_json(sample_ids).encode()).hexdigest()


def _read_rows(path: Path, name: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SamplingError(f"training graph {name} payload is invalid") from exc
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise SamplingError(f"training graph {name} payload must be a list of objects")
    return value

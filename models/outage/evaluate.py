"""Held-out outage-model evaluation artifacts."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from math import fsum

from .contracts import (
    Frozen,
    ModelArtifact,
    ObservedLabel,
    Partition,
    Probability,
    Sha256,
    SplitManifest,
    WindowKey,
)


class EvaluationStatus(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"


class EvaluationUnavailableReason(StrEnum):
    INSUFFICIENT_HOLDOUT_RECORDS = "insufficient_holdout_records"
    INCOMPLETE_HOLDOUT = "incomplete_holdout"


class HeldoutPrediction(Frozen):
    """One scored prediction paired with a real holdout label."""

    key: WindowKey
    p_out: Probability
    label: ObservedLabel


class EvaluationMetrics(Frozen):
    """Named metrics and their denominator, preventing ambiguous aggregates."""

    brier_score: Probability
    mean_absolute_error: float
    denominator: int
    metric_definition: str = "mean over observed holdout county-window labels"


class EvaluationArtifact(Frozen):
    """Persistable, content-addressed result for a valid held-out evaluation."""

    evaluation_sha256: Sha256
    status: EvaluationStatus
    model_artifact_sha256: Sha256
    model_version: str
    split_id: str
    split_input_artifact_sha256: Sha256
    metrics: EvaluationMetrics
    calibration_method: str | None
    calibration_status: str
    uncertainty_method: str | None


class UnavailableEvaluationArtifact(Frozen):
    """A safe result when a complete observed holdout evaluation is impossible."""

    evaluation_sha256: Sha256
    status: EvaluationStatus
    model_artifact_sha256: Sha256
    split_id: str
    reason: EvaluationUnavailableReason


def evaluate_holdout_predictions(
    *,
    model: ModelArtifact,
    split: SplitManifest,
    predictions: tuple[HeldoutPrediction, ...],
    calibration_method: str | None = None,
    uncertainty_method: str | None = None,
) -> EvaluationArtifact | UnavailableEvaluationArtifact:
    """Evaluate the complete observed holdout partition and derive its identity."""
    if model.split_id != split.split_id:
        raise ValueError("model split_id does not match evaluation split_id")

    holdout_keys = {
        assignment.key
        for assignment in split.assignments
        if assignment.partition is Partition.HOLDOUT
    }
    prediction_keys = tuple(prediction.key for prediction in predictions)
    if not predictions:
        return _unavailable(
            model, split, predictions, EvaluationUnavailableReason.INSUFFICIENT_HOLDOUT_RECORDS
        )
    if any(key not in holdout_keys for key in prediction_keys):
        raise ValueError("evaluation accepts only holdout partition keys")
    if len(set(prediction_keys)) != len(prediction_keys) or set(prediction_keys) != holdout_keys:
        return _unavailable(
            model, split, predictions, EvaluationUnavailableReason.INCOMPLETE_HOLDOUT
        )

    denominator = len(predictions)
    probabilities = tuple(prediction.p_out for prediction in predictions)
    fractions = tuple(prediction.label.fraction_out for prediction in predictions)
    binary_labels = tuple(float(prediction.label.customers_out_max > 0) for prediction in predictions)
    metrics = EvaluationMetrics(
        brier_score=fsum(
            (probability - label) ** 2
            for probability, label in zip(probabilities, binary_labels)
        )
        / denominator,
        mean_absolute_error=fsum(
            abs(probability - fraction) for probability, fraction in zip(probabilities, fractions)
        )
        / denominator,
        denominator=denominator,
    )
    return EvaluationArtifact(
        evaluation_sha256=_evaluation_sha256(
            model, split, predictions, calibration_method, uncertainty_method, metrics, None
        ),
        status=EvaluationStatus.READY,
        model_artifact_sha256=model.artifact_sha256,
        model_version=model.model_version,
        split_id=split.split_id,
        split_input_artifact_sha256=split.input_artifact_sha256,
        metrics=metrics,
        calibration_method=calibration_method,
        calibration_status="not_calibrated" if calibration_method is None else "reported",
        uncertainty_method=uncertainty_method,
    )


def _unavailable(
    model: ModelArtifact,
    split: SplitManifest,
    predictions: tuple[HeldoutPrediction, ...],
    reason: EvaluationUnavailableReason,
) -> UnavailableEvaluationArtifact:
    return UnavailableEvaluationArtifact(
        evaluation_sha256=_evaluation_sha256(
            model, split, predictions, None, None, None, reason
        ),
        status=EvaluationStatus.UNAVAILABLE,
        model_artifact_sha256=model.artifact_sha256,
        split_id=split.split_id,
        reason=reason,
    )


def _evaluation_sha256(
    model: ModelArtifact,
    split: SplitManifest,
    predictions: tuple[HeldoutPrediction, ...],
    calibration_method: str | None,
    uncertainty_method: str | None,
    metrics: EvaluationMetrics | None,
    reason: EvaluationUnavailableReason | None,
) -> str:
    payload = {
        "model_artifact_sha256": model.artifact_sha256,
        "model_version": model.model_version,
        "split_id": split.split_id,
        "split_input_artifact_sha256": split.input_artifact_sha256,
        "predictions": [
            {
                "key": prediction.key.model_dump(mode="json"),
                "p_out": prediction.p_out,
                "label": prediction.label.model_dump(mode="json"),
            }
            for prediction in sorted(
                predictions,
                key=lambda prediction: (
                    prediction.key.county_fips,
                    prediction.key.scenario_id,
                    prediction.key.window_start,
                ),
            )
        ],
        "calibration_method": calibration_method,
        "uncertainty_method": uncertainty_method,
        "metrics": None if metrics is None else metrics.model_dump(mode="json"),
        "reason": reason,
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

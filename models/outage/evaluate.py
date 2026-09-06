"""Held-out outage-model evaluation artifacts.

Evaluation is deliberately a separate, immutable artifact.  It only accepts
observed labels from the frozen holdout partition, so training or calibration
rows cannot silently inflate reported model quality.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import fsum

from .contracts import (
    ModelArtifact,
    ObservedLabel,
    Partition,
    Sha256,
    SplitManifest,
    WindowKey,
)


class EvaluationStatus(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"


class EvaluationUnavailableReason(StrEnum):
    INSUFFICIENT_HOLDOUT_RECORDS = "insufficient_holdout_records"


@dataclass(frozen=True)
class HeldoutPrediction:
    """One scored prediction paired with a real holdout label."""

    key: WindowKey
    p_out: float
    label: ObservedLabel

    def __post_init__(self) -> None:
        if not 0.0 <= self.p_out <= 1.0:
            raise ValueError("p_out must be a probability")


@dataclass(frozen=True)
class EvaluationMetrics:
    """Named metrics and their denominator, preventing ambiguous aggregates."""

    brier_score: float
    mean_absolute_error: float
    denominator: int
    metric_definition: str = "mean over observed holdout county-window labels"


@dataclass(frozen=True)
class EvaluationArtifact:
    """Persistable, provenance-bound result for a valid held-out evaluation."""

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


@dataclass(frozen=True)
class UnavailableEvaluationArtifact:
    """A safe result when no valid observed holdout evaluation can be made."""

    evaluation_sha256: Sha256
    status: EvaluationStatus
    model_artifact_sha256: Sha256
    split_id: str
    reason: EvaluationUnavailableReason


def evaluate_holdout_predictions(
    *,
    evaluation_sha256: str,
    model: ModelArtifact,
    split: SplitManifest,
    predictions: tuple[HeldoutPrediction, ...],
    calibration_method: str | None = None,
    uncertainty_method: str | None = None,
) -> EvaluationArtifact | UnavailableEvaluationArtifact:
    """Evaluate only observed holdout predictions from the supplied frozen split.

    Passing a train/calibration key or a fixture/uncovered label is an error:
    those inputs indicate a caller crossed the evaluation boundary.  An empty
    holdout returns a machine-readable unavailable artifact instead of metrics
    with a misleading zero denominator.
    """

    if model.split_id != split.split_id:
        raise ValueError("model split_id does not match evaluation split_id")

    holdout_keys = {
        assignment.key
        for assignment in split.assignments
        if assignment.partition is Partition.HOLDOUT
    }
    if not predictions:
        return UnavailableEvaluationArtifact(
            evaluation_sha256=evaluation_sha256,
            status=EvaluationStatus.UNAVAILABLE,
            model_artifact_sha256=model.artifact_sha256,
            split_id=split.split_id,
            reason=EvaluationUnavailableReason.INSUFFICIENT_HOLDOUT_RECORDS,
        )

    for prediction in predictions:
        if prediction.key not in holdout_keys:
            raise ValueError("evaluation accepts only holdout partition keys")

    denominator = len(predictions)
    observed = tuple(prediction.label.fraction_out for prediction in predictions)
    probabilities = tuple(prediction.p_out for prediction in predictions)
    brier_score = (
        fsum(
            (probability - actual) ** 2
            for probability, actual in zip(probabilities, observed)
        )
        / denominator
    )
    mean_absolute_error = (
        fsum(
            abs(probability - actual)
            for probability, actual in zip(probabilities, observed)
        )
        / denominator
    )
    return EvaluationArtifact(
        evaluation_sha256=evaluation_sha256,
        status=EvaluationStatus.READY,
        model_artifact_sha256=model.artifact_sha256,
        model_version=model.model_version,
        split_id=split.split_id,
        split_input_artifact_sha256=split.input_artifact_sha256,
        metrics=EvaluationMetrics(
            brier_score=brier_score,
            mean_absolute_error=mean_absolute_error,
            denominator=denominator,
        ),
        calibration_method=calibration_method,
        calibration_status="not_calibrated"
        if calibration_method is None
        else "reported",
        uncertainty_method=uncertainty_method,
    )

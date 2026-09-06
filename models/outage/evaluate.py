"""Held-out outage-model evaluation artifacts."""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from math import fsum

from .contracts import (
    EvaluationRef,
    Frozen,
    ModelArtifact,
    ObservedLabel,
    Partition,
    Probability,
    Sha256,
    SplitManifest,
    WindowKey,
)
from .split import verify_manifest_integrity

MATERIAL_OUTAGE_FRACTION = 0.05
"""Spec 02 label: ``y_out = frac_out >= 0.05`` ("material outage", >=5% of customers)."""

BRIER_DEFINITION = (
    "brier_score = mean((p_out - y_out)^2) over observed holdout county-windows, "
    f"y_out = 1 if fraction_out >= {MATERIAL_OUTAGE_FRACTION} else 0 (spec 02)"
)
FRACTION_MAE_DEFINITION = (
    "fraction_out_mae = mean(|p_out - fraction_out|) over observed holdout county-windows; "
    "not a spec-02 metric"
)


class EvaluationError(ValueError):
    """The supplied model, split, or predictions cannot form an honest evaluation."""


class EvaluationStatus(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"


class EvaluationUnavailableReason(StrEnum):
    INSUFFICIENT_HOLDOUT_RECORDS = "insufficient_holdout_records"
    INCOMPLETE_HOLDOUT = "incomplete_holdout"


class HeldoutPrediction(Frozen):
    """One scored prediction paired with a real holdout label.

    ``label`` must be an :class:`ObservedLabel`; a fixture or uncovered label is
    rejected at construction with a ``ValueError`` (pydantic ``ValidationError``).
    """

    key: WindowKey
    p_out: Probability
    label: ObservedLabel


class HoldoutCoverage(Frozen):
    """How much of the frozen holdout partition this evaluation actually scored."""

    holdout_size: int
    scored: int
    coverage: float

    @property
    def is_complete(self) -> bool:
        return self.scored == self.holdout_size


class EvaluationMetrics(Frozen):
    """Named metrics and their denominator, preventing ambiguous aggregates."""

    brier_score: Probability
    fraction_out_mae: float
    denominator: int
    brier_definition: str = BRIER_DEFINITION
    fraction_out_mae_definition: str = FRACTION_MAE_DEFINITION


class EvaluationArtifact(Frozen):
    """Persistable, content-addressed result for a valid held-out evaluation."""

    evaluation_sha256: Sha256
    status: EvaluationStatus
    model_artifact_sha256: Sha256
    model_version: str
    split_id: str
    split_input_artifact_sha256: Sha256
    coverage: HoldoutCoverage
    metrics: EvaluationMetrics
    calibration_method: str | None
    calibration_status: str
    uncertainty_method: str | None

    def to_ref(self) -> EvaluationRef:
        """The reference a prediction cites (``TrainedModelPrediction.evaluation``)."""
        return EvaluationRef(
            evaluation_sha256=self.evaluation_sha256,
            split_id=self.split_id,
            calibration_method=self.calibration_method,
        )


class UnavailableEvaluationArtifact(Frozen):
    """A safe result when a complete observed holdout evaluation is impossible."""

    evaluation_sha256: Sha256
    status: EvaluationStatus
    model_artifact_sha256: Sha256
    split_id: str
    coverage: HoldoutCoverage
    reason: EvaluationUnavailableReason


def evaluate_holdout_predictions(
    *,
    model: ModelArtifact,
    split: SplitManifest,
    predictions: tuple[HeldoutPrediction, ...],
    calibration_method: str | None = None,
    uncertainty_method: str | None = None,
    allow_partial_holdout: bool = False,
) -> EvaluationArtifact | UnavailableEvaluationArtifact:
    """Evaluate the observed holdout partition and derive the artifact's identity.

    Raises :class:`EvaluationError` when the model cites a different split, when the
    manifest fails ``split.py``'s integrity check, when any prediction key lies
    outside the holdout partition, or when a holdout key is predicted twice.
    Scoring fewer than all holdout keys returns an ``UNAVAILABLE`` artifact unless
    ``allow_partial_holdout`` is set, in which case the READY artifact carries a
    ``coverage`` below 1.0.
    """
    if model.split_id != split.split_id:
        raise EvaluationError("model split_id does not match evaluation split_id")
    verify_manifest_integrity(split)

    holdout_keys = {
        assignment.key
        for assignment in split.assignments
        if assignment.partition is Partition.HOLDOUT
    }
    prediction_keys = tuple(prediction.key for prediction in predictions)
    distinct_keys = set(prediction_keys)
    if len(distinct_keys) != len(prediction_keys):
        raise EvaluationError("duplicate holdout prediction keys")
    if any(key not in holdout_keys for key in prediction_keys):
        raise EvaluationError("evaluation accepts only holdout partition keys")

    coverage = HoldoutCoverage(
        holdout_size=len(holdout_keys),
        scored=len(distinct_keys),
        coverage=(len(distinct_keys) / len(holdout_keys)) if holdout_keys else 0.0,
    )
    if not predictions:
        return _unavailable(
            model,
            split,
            predictions,
            coverage,
            EvaluationUnavailableReason.INSUFFICIENT_HOLDOUT_RECORDS,
        )
    if not coverage.is_complete and not allow_partial_holdout:
        return _unavailable(
            model,
            split,
            predictions,
            coverage,
            EvaluationUnavailableReason.INCOMPLETE_HOLDOUT,
        )

    denominator = len(predictions)
    probabilities = tuple(prediction.p_out for prediction in predictions)
    fractions = tuple(prediction.label.fraction_out for prediction in predictions)
    binary_labels = tuple(
        float(fraction >= MATERIAL_OUTAGE_FRACTION) for fraction in fractions
    )
    metrics = EvaluationMetrics(
        brier_score=fsum(
            (probability - label) ** 2
            for probability, label in zip(probabilities, binary_labels, strict=True)
        )
        / denominator,
        fraction_out_mae=fsum(
            abs(probability - fraction)
            for probability, fraction in zip(probabilities, fractions, strict=True)
        )
        / denominator,
        denominator=denominator,
    )
    return EvaluationArtifact(
        evaluation_sha256=_evaluation_sha256(
            model,
            split,
            predictions,
            coverage,
            calibration_method,
            uncertainty_method,
            metrics,
            None,
        ),
        status=EvaluationStatus.READY,
        model_artifact_sha256=model.artifact_sha256,
        model_version=model.model_version,
        split_id=split.split_id,
        split_input_artifact_sha256=split.input_artifact_sha256,
        coverage=coverage,
        metrics=metrics,
        calibration_method=calibration_method,
        calibration_status="not_calibrated"
        if calibration_method is None
        else "reported",
        uncertainty_method=uncertainty_method,
    )


def _unavailable(
    model: ModelArtifact,
    split: SplitManifest,
    predictions: tuple[HeldoutPrediction, ...],
    coverage: HoldoutCoverage,
    reason: EvaluationUnavailableReason,
) -> UnavailableEvaluationArtifact:
    return UnavailableEvaluationArtifact(
        evaluation_sha256=_evaluation_sha256(
            model, split, predictions, coverage, None, None, None, reason
        ),
        status=EvaluationStatus.UNAVAILABLE,
        model_artifact_sha256=model.artifact_sha256,
        split_id=split.split_id,
        coverage=coverage,
        reason=reason,
    )


def _evaluation_sha256(
    model: ModelArtifact,
    split: SplitManifest,
    predictions: tuple[HeldoutPrediction, ...],
    coverage: HoldoutCoverage,
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
        "coverage": coverage.model_dump(mode="json"),
        "calibration_method": calibration_method,
        "uncertainty_method": uncertainty_method,
        "metrics": None if metrics is None else metrics.model_dump(mode="json"),
        "reason": reason,
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

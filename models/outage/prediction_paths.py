"""Explicit trained, heuristic, and unavailable prediction paths.

The module intentionally leaves ``models.outage.predict`` available for the
specification's scenario-runner entry point.

Unavailable reasons are a closed vocabulary (``UnavailableReason``) with a fixed
mapping onto the shared copilot ``Unavailable.code`` vocabulary, so the tool
boundary can report the specific cause without inventing codes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Final

from copilot.tools.schemas import Unavailable, UnavailableCode

from .contracts import (
    Driver,
    EvaluationRef,
    FeatureRow,
    HeuristicPrediction,
    ModelArtifact,
    PredictionRecord,
    TrainedModelPrediction,
    UnavailablePrediction,
    WindowKey,
)

Scorer = Callable[[Mapping[str, float]], float]
Heuristic = Callable[[FeatureRow], float]


class UnavailableReason(StrEnum):
    """The only reasons a prediction path may give for not predicting."""

    MISSING_MODEL_ARTIFACT = "missing_model_artifact"
    MISSING_MODEL_SCORER = "missing_model_scorer"
    MISSING_HEURISTIC_RULE = "missing_heuristic_rule"
    MISSING_PREDICTION_FEATURES = "missing_prediction_features"
    FEATURE_SET_VERSION_MISMATCH = "feature_set_version_mismatch"


UNAVAILABLE_CODES: Final[Mapping[UnavailableReason, UnavailableCode]] = {
    UnavailableReason.MISSING_MODEL_ARTIFACT: "artifact_unavailable",
    UnavailableReason.MISSING_MODEL_SCORER: "artifact_unavailable",
    UnavailableReason.MISSING_HEURISTIC_RULE: "artifact_unavailable",
    UnavailableReason.MISSING_PREDICTION_FEATURES: "insufficient_evidence",
    UnavailableReason.FEATURE_SET_VERSION_MISMATCH: "invalid_prerequisite",
}
"""Every reason maps onto exactly one shared ``Unavailable.code``."""


def trained_prediction(
    *,
    features: FeatureRow,
    artifact: ModelArtifact | None,
    scorer: Scorer | None,
    customers_at_risk: int,
    driver: Driver,
    evaluation: EvaluationRef | None = None,
) -> PredictionRecord:
    """Run a model only for a complete, matching feature-set row."""
    if artifact is None:
        return unavailable_prediction(
            key=features.key, reason=UnavailableReason.MISSING_MODEL_ARTIFACT
        )
    if scorer is None:
        return unavailable_prediction(
            key=features.key, reason=UnavailableReason.MISSING_MODEL_SCORER
        )
    if artifact.feature_set_version != features.feature_set_version:
        return unavailable_prediction(
            key=features.key, reason=UnavailableReason.FEATURE_SET_VERSION_MISMATCH
        )
    if features.missing:
        return unavailable_prediction(
            key=features.key, reason=UnavailableReason.MISSING_PREDICTION_FEATURES
        )

    probability = scorer({name: value.value for name, value in features.features})
    return PredictionRecord(
        key=features.key,
        prediction=TrainedModelPrediction(
            p_out=probability,
            customers_at_risk=customers_at_risk,
            driver=driver,
            artifact=artifact,
            evaluation=evaluation,
        ),
    )


def heuristic_prediction(
    *,
    features: FeatureRow,
    rule: Heuristic | None,
    rule_id: str,
    rule_version: str,
    customers_at_risk: int,
    driver: Driver,
) -> PredictionRecord:
    """Run a declared heuristic only for a complete feature row."""
    if rule is None:
        return unavailable_prediction(
            key=features.key, reason=UnavailableReason.MISSING_HEURISTIC_RULE
        )
    if features.missing:
        return unavailable_prediction(
            key=features.key, reason=UnavailableReason.MISSING_PREDICTION_FEATURES
        )

    probability = rule(features)
    return PredictionRecord(
        key=features.key,
        prediction=HeuristicPrediction(
            p_out=probability,
            customers_at_risk=customers_at_risk,
            driver=driver,
            rule_id=rule_id,
            rule_version=rule_version,
        ),
    )


def unavailable_prediction(
    *, key: WindowKey, reason: UnavailableReason
) -> PredictionRecord:
    """Return a non-persistable result whose reason is one of ``UnavailableReason``.

    Free text is rejected: ``reason`` must be a member (or the exact value of a
    member) of the closed vocabulary.
    """
    reason = UnavailableReason(reason)
    return PredictionRecord(
        key=key, prediction=UnavailablePrediction(reason=reason.value)
    )


def to_unavailable(prediction: UnavailablePrediction) -> Unavailable:
    """Map an unavailable prediction onto the shared copilot ``Unavailable`` envelope."""
    reason = UnavailableReason(prediction.reason)
    return Unavailable(
        code=UNAVAILABLE_CODES[reason], reason=reason.value, retryable=False
    )

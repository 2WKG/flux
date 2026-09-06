"""Explicit trained, heuristic, and unavailable prediction paths.

The module intentionally leaves ``models.outage.predict`` available for the
specification's scenario-runner entry point.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

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
        return unavailable_prediction(key=features.key, reason="missing_model_artifact")
    if scorer is None:
        return unavailable_prediction(key=features.key, reason="missing_model_scorer")
    if artifact.feature_set_version != features.feature_set_version:
        return unavailable_prediction(key=features.key, reason="feature_set_version_mismatch")
    if features.missing:
        return unavailable_prediction(key=features.key, reason="missing_prediction_features")

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
        return unavailable_prediction(key=features.key, reason="missing_heuristic_rule")
    if features.missing:
        return unavailable_prediction(key=features.key, reason="missing_prediction_features")

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


def unavailable_prediction(*, key: WindowKey, reason: str) -> PredictionRecord:
    """Return a non-persistable result with an API-safe reason code."""
    return PredictionRecord(key=key, prediction=UnavailablePrediction(reason=reason))

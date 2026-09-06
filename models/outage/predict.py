"""Prediction execution with explicit trained, heuristic, and unavailable modes.

The execution helpers return the versioned contract objects rather than raw
numbers.  This makes it impossible for a fallback rule to masquerade as a
trained-model result at the API or persistence boundary.
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
    key: WindowKey,
    feature_values: Mapping[str, float],
    artifact: ModelArtifact | None,
    scorer: Scorer | None,
    customers_at_risk: int,
    driver: Driver,
    evaluation: EvaluationRef | None = None,
) -> PredictionRecord:
    """Run a supplied trained-model scorer or return an explicit unavailable result.

    ``artifact`` and ``scorer`` are both required.  A missing model never
    falls through to a heuristic, and a pydantic contract bounds the model
    output to a probability before it can be persisted.
    """

    if artifact is None:
        return unavailable_prediction(key=key, reason="missing_model_artifact")
    if scorer is None:
        return unavailable_prediction(key=key, reason="missing_model_scorer")
    if not feature_values:
        return unavailable_prediction(key=key, reason="missing_prediction_features")

    probability = scorer(dict(feature_values))
    return PredictionRecord(
        key=key,
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
    """Run a declared heuristic and preserve the rule provenance."""

    if rule is None:
        return unavailable_prediction(key=features.key, reason="missing_heuristic_rule")

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

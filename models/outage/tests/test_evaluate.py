from datetime import UTC, datetime

import pytest

from models.outage.contracts import (
    ModelArtifact,
    ObservedLabel,
    Partition,
    SplitAssignment,
    SplitManifest,
    WindowKey,
)
from models.outage.evaluate import (
    EvaluationArtifact,
    EvaluationStatus,
    EvaluationUnavailableReason,
    HeldoutPrediction,
    UnavailableEvaluationArtifact,
    evaluate_holdout_predictions,
)

H = "a" * 64
KEY = WindowKey(
    county_fips="48453",
    scenario_id="summer-peak",
    window_start=datetime(2024, 7, 1, tzinfo=UTC),
)
CALIBRATION_KEY = WindowKey(
    county_fips="48453",
    scenario_id="summer-peak",
    window_start=datetime(2024, 7, 1, 6, tzinfo=UTC),
)
TRAINING_KEY = WindowKey(
    county_fips="48453",
    scenario_id="summer-peak",
    window_start=datetime(2024, 7, 1, 12, tzinfo=UTC),
)
MODEL = ModelArtifact(
    artifact_sha256=H,
    model_version="lgbm-1",
    trained_at=datetime(2024, 1, 1, tzinfo=UTC),
    split_id="split-1",
    feature_set_version="features-1",
)
SPLIT = SplitManifest(
    split_id="split-1",
    seed=7,
    input_artifact_sha256=H,
    assignments=(
        SplitAssignment(key=KEY, partition=Partition.HOLDOUT),
        SplitAssignment(key=CALIBRATION_KEY, partition=Partition.CALIBRATION),
        SplitAssignment(key=TRAINING_KEY, partition=Partition.TRAIN),
    ),
)
LABEL = ObservedLabel(
    customers_out_max=20,
    total_customers=100,
    source_dataset_id="eaglei",
    source_file_sha256=H,
    retrieved_at=datetime(2024, 7, 2, tzinfo=UTC),
)


def test_evaluation_is_tied_to_holdout_model_and_split_hashes():
    artifact = evaluate_holdout_predictions(
        evaluation_sha256=H,
        model=MODEL,
        split=SPLIT,
        predictions=(HeldoutPrediction(key=KEY, p_out=0.3, label=LABEL),),
    )

    assert isinstance(artifact, EvaluationArtifact)
    assert artifact.status is EvaluationStatus.READY
    assert artifact.metrics.denominator == 1
    assert artifact.metrics.brier_score == pytest.approx(0.01)
    assert artifact.model_artifact_sha256 == MODEL.artifact_sha256
    assert artifact.split_input_artifact_sha256 == SPLIT.input_artifact_sha256
    assert artifact.calibration_status == "not_calibrated"


@pytest.mark.parametrize("non_holdout_key", (CALIBRATION_KEY, TRAINING_KEY))
def test_calibration_or_training_rows_cannot_enter_heldout_evaluation(non_holdout_key):
    with pytest.raises(ValueError, match="holdout"):
        evaluate_holdout_predictions(
            evaluation_sha256=H,
            model=MODEL,
            split=SPLIT,
            predictions=(
                HeldoutPrediction(key=non_holdout_key, p_out=0.3, label=LABEL),
            ),
        )


def test_empty_evaluation_is_explicitly_unavailable():
    artifact = evaluate_holdout_predictions(
        evaluation_sha256=H,
        model=MODEL,
        split=SPLIT,
        predictions=(),
    )

    assert isinstance(artifact, UnavailableEvaluationArtifact)
    assert artifact.status is EvaluationStatus.UNAVAILABLE
    assert artifact.reason is EvaluationUnavailableReason.INSUFFICIENT_HOLDOUT_RECORDS

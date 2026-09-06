from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from models.outage.contracts import (
    CountyOutageRow,
    EvaluationRef,
    FixtureLabel,
    ModelArtifact,
    ObservedLabel,
    Partition,
    UncoveredLabel,
    WindowKey,
)
from models.outage.evaluate import (
    MATERIAL_OUTAGE_FRACTION,
    EvaluationArtifact,
    EvaluationError,
    EvaluationStatus,
    EvaluationUnavailableReason,
    HeldoutPrediction,
    UnavailableEvaluationArtifact,
    evaluate_holdout_predictions,
)
from models.outage.split import SplitError, build_split_manifest

H = "a" * 64
SOURCE_H = "b" * 64


def _key(when: datetime) -> WindowKey:
    return WindowKey(county_fips="48453", scenario_id="beryl_2024", window_start=when)


def _label(customers_out_max: int, total_customers: int = 100) -> ObservedLabel:
    return ObservedLabel(
        customers_out_max=customers_out_max,
        total_customers=total_customers,
        source_dataset_id="eaglei",
        source_file_sha256=SOURCE_H,
        retrieved_at=datetime(2024, 7, 20, tzinfo=UTC),
    )


# Beryl window (2024-07-04..07-14, TX) -> HOLDOUT; 2023 TX -> CALIBRATION; 2022 TX -> TRAIN.
HOLDOUT_KEYS = (
    _key(datetime(2024, 7, 5, 0, tzinfo=UTC)),
    _key(datetime(2024, 7, 5, 6, tzinfo=UTC)),
    _key(datetime(2024, 7, 5, 12, tzinfo=UTC)),
)
CALIBRATION_KEY = _key(datetime(2023, 3, 1, tzinfo=UTC))
TRAINING_KEY = _key(datetime(2022, 3, 1, tzinfo=UTC))
LABEL = _label(20)
SPLIT = build_split_manifest(
    tuple(
        CountyOutageRow(key=key, label=LABEL)
        for key in (*HOLDOUT_KEYS, CALIBRATION_KEY, TRAINING_KEY)
    ),
    states_by_county={"48453": "TX"},
    input_artifact_sha256=H,
)
MODEL = ModelArtifact(
    artifact_sha256=H,
    model_version="lgbm-1",
    trained_at=datetime(2024, 1, 1, tzinfo=UTC),
    split_id=SPLIT.split_id,
    feature_set_version="features-1",
)
FULL_PREDICTIONS = (
    HeldoutPrediction(
        key=HOLDOUT_KEYS[0], p_out=0.3, label=_label(20)
    ),  # frac 0.20 -> y=1
    HeldoutPrediction(
        key=HOLDOUT_KEYS[1], p_out=0.9, label=_label(100)
    ),  # frac 1.00 -> y=1
    HeldoutPrediction(
        key=HOLDOUT_KEYS[2], p_out=0.1, label=_label(2)
    ),  # frac 0.02 -> y=0
)


def _evaluate(predictions=FULL_PREDICTIONS, **kwargs):
    return evaluate_holdout_predictions(
        model=MODEL, split=SPLIT, predictions=predictions, **kwargs
    )


def test_fixture_manifest_has_every_partition_and_passes_integrity():
    partitions = {
        assignment.key: assignment.partition for assignment in SPLIT.assignments
    }
    assert {partitions[key] for key in HOLDOUT_KEYS} == {Partition.HOLDOUT}
    assert partitions[CALIBRATION_KEY] is Partition.CALIBRATION
    assert partitions[TRAINING_KEY] is Partition.TRAIN


def test_brier_is_spec02_binary_material_outage_not_fraction_mse():
    artifact = _evaluate()

    assert isinstance(artifact, EvaluationArtifact)
    assert artifact.status is EvaluationStatus.READY
    assert artifact.metrics.denominator == 3
    # y_out = frac >= 0.05 -> (1, 1, 0): ((0.3-1)^2 + (0.9-1)^2 + (0.1-0)^2) / 3
    assert artifact.metrics.brier_score == pytest.approx((0.49 + 0.01 + 0.01) / 3)
    # Old fraction-MSE on the first two rows gave 0.01; the spec-02 Brier gives 0.25.
    two_rows = _evaluate(FULL_PREDICTIONS[:2], allow_partial_holdout=True)
    assert two_rows.metrics.brier_score == pytest.approx(0.25)
    assert two_rows.metrics.brier_score != pytest.approx(0.01)
    # |p - frac|: |0.3-0.2| + |0.9-1.0| + |0.1-0.02| = 0.28 / 3
    assert artifact.metrics.fraction_out_mae == pytest.approx(0.28 / 3)
    assert str(MATERIAL_OUTAGE_FRACTION) in artifact.metrics.brier_definition


def test_material_threshold_is_five_percent_not_any_outage():
    # frac 0.02 is a non-material outage: y=0 under spec 02, so p=0.1 is nearly right.
    # If the code used `customers_out_max > 0`, y would be 1 and the Brier 0.81.
    artifact = _evaluate(FULL_PREDICTIONS[2:], allow_partial_holdout=True)
    assert artifact.metrics.brier_score == pytest.approx(0.01)
    exactly_material = _evaluate(
        (HeldoutPrediction(key=HOLDOUT_KEYS[2], p_out=0.1, label=_label(5)),),
        allow_partial_holdout=True,
    )
    assert exactly_material.metrics.brier_score == pytest.approx(0.81)


def test_provenance_fields_and_calibration_status_are_carried():
    artifact = _evaluate()
    assert artifact.model_artifact_sha256 == MODEL.artifact_sha256
    assert artifact.model_version == "lgbm-1"
    assert artifact.split_id == SPLIT.split_id
    assert artifact.split_input_artifact_sha256 == SPLIT.input_artifact_sha256
    assert artifact.calibration_status == "not_calibrated"
    assert artifact.calibration_method is None

    calibrated = _evaluate(
        calibration_method="isotonic", uncertainty_method="bootstrap"
    )
    assert calibrated.calibration_status == "reported"
    assert calibrated.calibration_method == "isotonic"
    assert calibrated.uncertainty_method == "bootstrap"


def test_evaluation_sha256_is_derived_from_content():
    first = _evaluate()
    same_reordered = _evaluate(tuple(reversed(FULL_PREDICTIONS)))
    assert first.evaluation_sha256 == same_reordered.evaluation_sha256
    assert first.evaluation_sha256 not in (H, SOURCE_H)

    different_probability = FULL_PREDICTIONS[:2] + (
        HeldoutPrediction(key=HOLDOUT_KEYS[2], p_out=0.2, label=_label(2)),
    )
    assert _evaluate(different_probability).evaluation_sha256 != first.evaluation_sha256
    different_label = FULL_PREDICTIONS[:2] + (
        HeldoutPrediction(key=HOLDOUT_KEYS[2], p_out=0.1, label=_label(3)),
    )
    assert _evaluate(different_label).evaluation_sha256 != first.evaluation_sha256
    assert (
        _evaluate(calibration_method="isotonic").evaluation_sha256
        != first.evaluation_sha256
    )
    # Same aggregate metrics, different per-window predictions: swapping p_out between
    # two rows with identical labels leaves brier/MAE unchanged, so only the hashed
    # per-row content can tell the two artifacts apart.
    same_label_rows = (
        HeldoutPrediction(key=HOLDOUT_KEYS[0], p_out=0.3, label=_label(20)),
        HeldoutPrediction(key=HOLDOUT_KEYS[1], p_out=0.9, label=_label(20)),
        FULL_PREDICTIONS[2],
    )
    swapped_rows = (
        HeldoutPrediction(key=HOLDOUT_KEYS[0], p_out=0.9, label=_label(20)),
        HeldoutPrediction(key=HOLDOUT_KEYS[1], p_out=0.3, label=_label(20)),
        FULL_PREDICTIONS[2],
    )
    original, swapped = _evaluate(same_label_rows), _evaluate(swapped_rows)
    assert original.metrics == swapped.metrics
    assert original.evaluation_sha256 != swapped.evaluation_sha256
    other_model = MODEL.model_copy(update={"model_version": "lgbm-2"})
    assert (
        evaluate_holdout_predictions(
            model=other_model, split=SPLIT, predictions=FULL_PREDICTIONS
        ).evaluation_sha256
        != first.evaluation_sha256
    )


def test_evaluation_sha256_field_rejects_non_digests():
    artifact = _evaluate()
    with pytest.raises(ValidationError):
        EvaluationArtifact.model_validate(
            {**artifact.model_dump(), "evaluation_sha256": "not-a-hash"}
        )
    with pytest.raises(ValidationError):
        artifact.evaluation_sha256 = "c" * 64  # frozen


def test_tampered_split_manifest_is_rejected_by_integrity_check():
    tampered = SPLIT.model_copy(update={"input_artifact_sha256": "c" * 64})
    model = MODEL.model_copy(update={"split_id": tampered.split_id})
    with pytest.raises(SplitError, match="split_id does not match"):
        evaluate_holdout_predictions(
            model=model, split=tampered, predictions=FULL_PREDICTIONS
        )

    renamed = SPLIT.model_copy(update={"split_id": "split-1"})
    with pytest.raises(SplitError, match="split_id does not match"):
        evaluate_holdout_predictions(
            model=MODEL.model_copy(update={"split_id": "split-1"}),
            split=renamed,
            predictions=FULL_PREDICTIONS,
        )


def test_model_citing_a_different_split_is_rejected():
    other_model = MODEL.model_copy(update={"split_id": "split-" + "0" * 16})
    with pytest.raises(EvaluationError, match="split_id"):
        evaluate_holdout_predictions(
            model=other_model, split=SPLIT, predictions=FULL_PREDICTIONS
        )


@pytest.mark.parametrize("non_holdout_key", (CALIBRATION_KEY, TRAINING_KEY))
def test_calibration_or_training_rows_cannot_enter_heldout_evaluation(non_holdout_key):
    with pytest.raises(EvaluationError, match="holdout"):
        _evaluate(
            FULL_PREDICTIONS
            + (HeldoutPrediction(key=non_holdout_key, p_out=0.3, label=LABEL),)
        )


@pytest.mark.parametrize(
    "label",
    (
        FixtureLabel(customers_out_max=20, total_customers=100, reason="placeholder"),
        UncoveredLabel(reason="no EAGLE-I sample"),
    ),
)
def test_fixture_and_uncovered_labels_cannot_be_scored(label):
    with pytest.raises(ValueError, match="label"):
        HeldoutPrediction(key=HOLDOUT_KEYS[0], p_out=0.3, label=label)


def test_duplicate_holdout_keys_are_a_named_error_not_a_double_count():
    duplicated = FULL_PREDICTIONS + (FULL_PREDICTIONS[0],)
    with pytest.raises(EvaluationError, match="duplicate"):
        _evaluate(duplicated)


def test_empty_evaluation_is_explicitly_unavailable_with_zero_coverage():
    artifact = _evaluate(())

    assert isinstance(artifact, UnavailableEvaluationArtifact)
    assert artifact.status is EvaluationStatus.UNAVAILABLE
    assert artifact.reason is EvaluationUnavailableReason.INSUFFICIENT_HOLDOUT_RECORDS
    assert artifact.coverage.holdout_size == 3
    assert artifact.coverage.scored == 0
    assert artifact.coverage.coverage == 0.0


def test_partial_holdout_is_unavailable_unless_explicitly_allowed():
    partial = _evaluate(FULL_PREDICTIONS[:1])

    assert isinstance(partial, UnavailableEvaluationArtifact)
    assert partial.reason is EvaluationUnavailableReason.INCOMPLETE_HOLDOUT
    assert partial.coverage.holdout_size == 3
    assert partial.coverage.scored == 1
    assert partial.coverage.coverage == pytest.approx(1 / 3)

    allowed = _evaluate(FULL_PREDICTIONS[:1], allow_partial_holdout=True)
    assert isinstance(allowed, EvaluationArtifact)
    assert allowed.coverage.coverage == pytest.approx(1 / 3)
    assert allowed.metrics.denominator == 1

    complete = _evaluate()
    assert complete.coverage.coverage == 1.0
    assert complete.coverage.is_complete
    assert complete.evaluation_sha256 != allowed.evaluation_sha256


def test_to_ref_matches_the_contract_prediction_cites():
    artifact = _evaluate(calibration_method="isotonic")
    ref = artifact.to_ref()
    assert isinstance(ref, EvaluationRef)
    assert ref.evaluation_sha256 == artifact.evaluation_sha256
    assert ref.split_id == SPLIT.split_id
    assert ref.calibration_method == "isotonic"

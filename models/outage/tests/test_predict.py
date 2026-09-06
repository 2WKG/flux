from datetime import UTC, datetime

from models.outage.contracts import (
    Driver,
    FeatureRow,
    FeatureStatus,
    FeatureValue,
    HeuristicPrediction,
    ModelArtifact,
    TrainedModelPrediction,
    UnavailablePrediction,
    WindowKey,
)
from models.outage.prediction_paths import heuristic_prediction, trained_prediction

H = "a" * 64
KEY = WindowKey(
    county_fips="48453",
    scenario_id="summer-peak",
    window_start=datetime(2024, 7, 1, tzinfo=UTC),
)
ARTIFACT = ModelArtifact(
    artifact_sha256=H,
    model_version="lgbm-1",
    trained_at=datetime(2024, 1, 1, tzinfo=UTC),
    split_id="split-1",
    feature_set_version="features-1",
)


def _features(*, status: FeatureStatus = FeatureStatus.PRESENT) -> FeatureRow:
    return FeatureRow(
        key=KEY,
        feature_set_version="features-1",
        source_input_sha256=H,
        features=(
            (
                "gust_max",
                FeatureValue(
                    value=20.0 if status is FeatureStatus.PRESENT else None,
                    status=status,
                    unit="m_s",
                ),
            ),
        ),
    )


def test_trained_path_preserves_artifact_and_identity():
    record = trained_prediction(
        features=_features(),
        artifact=ARTIFACT,
        scorer=lambda values: values["gust_max"] / 100,
        customers_at_risk=120,
        driver=Driver.WIND,
    )

    assert isinstance(record.prediction, TrainedModelPrediction)
    assert record.prediction.artifact == ARTIFACT
    assert record.key == KEY
    assert record.prediction.p_out == 0.2


def test_missing_trained_model_never_falls_back_to_heuristic():
    record = trained_prediction(
        features=_features(),
        artifact=None,
        scorer=lambda _: 0.2,
        customers_at_risk=120,
        driver=Driver.WIND,
    )

    assert isinstance(record.prediction, UnavailablePrediction)
    assert record.prediction.reason == "missing_model_artifact"
    assert record.to_persistence() is None


def test_heuristic_path_carries_rule_provenance():
    record = heuristic_prediction(
        features=_features(),
        rule=lambda _: 0.3,
        rule_id="wind-threshold",
        rule_version="2",
        customers_at_risk=120,
        driver=Driver.WIND,
    )

    assert isinstance(record.prediction, HeuristicPrediction)
    assert record.prediction.rule_id == "wind-threshold"
    assert record.prediction.model_kind == "heuristic"


def test_missing_features_never_produce_a_trained_or_heuristic_probability():
    features = _features(status=FeatureStatus.MISSING_SOURCE)

    trained = trained_prediction(
        features=features,
        artifact=ARTIFACT,
        scorer=lambda _: 0.2,
        customers_at_risk=120,
        driver=Driver.WIND,
    )
    heuristic = heuristic_prediction(
        features=features,
        rule=lambda _: 0.3,
        rule_id="wind-threshold",
        rule_version="2",
        customers_at_risk=120,
        driver=Driver.WIND,
    )

    assert isinstance(trained.prediction, UnavailablePrediction)
    assert isinstance(heuristic.prediction, UnavailablePrediction)
    assert trained.prediction.reason == heuristic.prediction.reason == "missing_prediction_features"


def test_trained_model_rejects_a_different_feature_set_version():
    mismatched = ARTIFACT.model_copy(update={"feature_set_version": "features-2"})

    record = trained_prediction(
        features=_features(),
        artifact=mismatched,
        scorer=lambda _: 0.2,
        customers_at_risk=120,
        driver=Driver.WIND,
    )

    assert isinstance(record.prediction, UnavailablePrediction)
    assert record.prediction.reason == "feature_set_version_mismatch"

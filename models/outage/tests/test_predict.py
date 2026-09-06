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
from models.outage.predict import heuristic_prediction, trained_prediction

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


def test_trained_path_preserves_artifact_and_identity():
    record = trained_prediction(
        key=KEY,
        feature_values={"gust_max": 20.0},
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
        key=KEY,
        feature_values={"gust_max": 20.0},
        artifact=None,
        scorer=lambda _: 0.2,
        customers_at_risk=120,
        driver=Driver.WIND,
    )

    assert isinstance(record.prediction, UnavailablePrediction)
    assert record.prediction.reason == "missing_model_artifact"
    assert record.to_persistence() is None


def test_heuristic_path_carries_rule_provenance():
    features = FeatureRow(
        key=KEY,
        feature_set_version="features-1",
        source_input_sha256=H,
        features=(
            (
                "gust_max",
                FeatureValue(value=20.0, status=FeatureStatus.PRESENT, unit="m_s"),
            ),
        ),
    )
    record = heuristic_prediction(
        features=features,
        rule=lambda _: 0.3,
        rule_id="wind-threshold",
        rule_version="2",
        customers_at_risk=120,
        driver=Driver.WIND,
    )

    assert isinstance(record.prediction, HeuristicPrediction)
    assert record.prediction.rule_id == "wind-threshold"
    assert record.prediction.model_kind == "heuristic"

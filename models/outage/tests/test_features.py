from datetime import UTC, datetime

import pytest

from models.outage.contracts import (
    FeatureStatus,
    Partition,
    SplitAssignment,
    SplitManifest,
    WindowKey,
)
from models.outage.feature_status import (
    FeatureFitError,
    RawFeature,
    assemble_features,
    fit_standardizers,
)

H = "a" * 64
TRAIN_KEY = WindowKey(
    county_fips="48453",
    scenario_id="summer-peak",
    window_start=datetime(2024, 7, 1, tzinfo=UTC),
)
HOLDOUT_KEY = WindowKey(
    county_fips="48453",
    scenario_id="summer-peak",
    window_start=datetime(2024, 7, 1, 6, tzinfo=UTC),
)
SPLIT = SplitManifest(
    split_id="split-1",
    seed=7,
    input_artifact_sha256=H,
    assignments=(
        SplitAssignment(key=TRAIN_KEY, partition=Partition.TRAIN),
        SplitAssignment(key=HOLDOUT_KEY, partition=Partition.HOLDOUT),
    ),
)


def test_transforms_fit_only_training_partition_and_are_reproducible():
    sources = {
        TRAIN_KEY: {"gust": RawFeature(10.0, "m_s")},
        HOLDOUT_KEY: {"gust": RawFeature(1000.0, "m_s")},
    }
    first = fit_standardizers(source_rows=sources, split=SPLIT)
    second = fit_standardizers(
        source_rows=dict(reversed(tuple(sources.items()))), split=SPLIT
    )

    assert first == second
    assert first[0].mean == 10.0
    assert first[0].fit_partition is Partition.TRAIN


def test_complete_and_partially_missing_features_preserve_status_and_reason():
    transforms = fit_standardizers(
        source_rows={
            TRAIN_KEY: {"gust": RawFeature(10.0, "m_s"), "rain": RawFeature(2.0, "mm")}
        },
        split=SPLIT,
    )
    artifact = assemble_features(
        key=HOLDOUT_KEY,
        source_features={"gust": RawFeature(11.0, "m_s")},
        transforms=transforms,
        feature_set_version="v1",
        source_input_sha256=H,
    )

    fields = dict(artifact.row.features)
    assert fields["gust"].status is FeatureStatus.PRESENT
    assert fields["rain"].status is FeatureStatus.MISSING_SOURCE
    assert artifact.missing_reasons == (("rain", "missing_source_feature"),)


def test_unsupported_input_is_explicit_not_silently_imputed():
    transforms = fit_standardizers(
        source_rows={TRAIN_KEY: {"gust": RawFeature(10.0, "m_s")}}, split=SPLIT
    )
    artifact = assemble_features(
        key=HOLDOUT_KEY,
        source_features={
            "gust": RawFeature(None, "m_s", FeatureStatus.OUT_OF_COVERAGE, "no station")
        },
        transforms=transforms,
        feature_set_version="v1",
        source_input_sha256=H,
    )

    assert artifact.row.features[0][1].status is FeatureStatus.OUT_OF_COVERAGE
    assert artifact.missing_reasons == (("gust", "no station"),)


def test_imputed_values_remain_value_carrying_and_explicit():
    transforms = fit_standardizers(
        source_rows={TRAIN_KEY: {"gust": RawFeature(10.0, "m_s")}}, split=SPLIT
    )

    artifact = assemble_features(
        key=HOLDOUT_KEY,
        source_features={
            "gust": RawFeature(11.0, "m_s", FeatureStatus.IMPUTED, "station gap")
        },
        transforms=transforms,
        feature_set_version="v1",
        source_input_sha256=H,
    )

    field = dict(artifact.row.features)["gust"]
    assert field.status is FeatureStatus.IMPUTED
    assert field.value == 1.0


def test_fit_rejects_conflicting_units_for_one_feature():
    second_train = WindowKey(
        county_fips="48453",
        scenario_id="summer-peak",
        window_start=datetime(2024, 7, 1, 12, tzinfo=UTC),
    )
    split = SPLIT.model_copy(
        update={
            "assignments": SPLIT.assignments
            + (SplitAssignment(key=second_train, partition=Partition.TRAIN),)
        }
    )

    with pytest.raises(FeatureFitError, match="conflicting units"):
        fit_standardizers(
            source_rows={
                TRAIN_KEY: {"gust": RawFeature(10.0, "m_s")},
                second_train: {"gust": RawFeature(20.0, "mph")},
            },
            split=split,
        )

"""Leakage and provenance checks for 2WKG-208 feature transforms."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from models.outage.contracts import Partition, SplitAssignment, SplitManifest, WindowKey
from models.outage.transforms import (
    TRANSFORM_VERSION,
    TransformError,
    apply_feature_transforms,
    fit_feature_transforms,
)

HASH = "a" * 64


def _key(at: datetime) -> WindowKey:
    return WindowKey(county_fips="48453", scenario_id="historical", window_start=at)


def _manifest() -> SplitManifest:
    return SplitManifest(
        split_id="split-test",
        seed=7,
        input_artifact_sha256=HASH,
        assignments=(
            SplitAssignment(key=_key(datetime(2021, 2, 15, tzinfo=UTC)), partition=Partition.HOLDOUT),
            SplitAssignment(key=_key(datetime(2022, 1, 1, tzinfo=UTC)), partition=Partition.TRAIN),
            SplitAssignment(key=_key(datetime(2023, 1, 1, tzinfo=UTC)), partition=Partition.CALIBRATION),
            SplitAssignment(key=_key(datetime(2024, 1, 1, tzinfo=UTC)), partition=Partition.TRAIN),
            SplitAssignment(key=_key(datetime(2024, 7, 10, tzinfo=UTC)), partition=Partition.EXCLUDED),
        ),
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "county_fips": ["48453"] * 5,
            "scenario_id": ["historical"] * 5,
            "window_start": [
                datetime(2021, 2, 15, tzinfo=UTC),
                datetime(2022, 1, 1, tzinfo=UTC),
                datetime(2023, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 7, 10, tzinfo=UTC),
            ],
            # Only 10 and 20 are training values.  The other values make a
            # leak immediately obvious if they are included in any statistic.
            "gust_max": [10_000.0, 10.0, 1_000.0, 20.0, -1_000.0],
        }
    )


def test_fit_uses_only_manifest_training_rows_and_freezes_for_holdouts():
    frame = _frame()
    artifact = fit_feature_transforms(
        frame,
        _manifest(),
        feature_columns=["gust_max"],
        verified_input_artifact_sha256=HASH,
        feature_set_version="outage-features-v1",
    )

    transform = artifact.transforms[0]
    assert transform.impute_value == 15.0
    assert transform.mean == 15.0
    assert transform.scale == 5.0

    holdout = frame.iloc[[0]].copy()
    result = apply_feature_transforms(
        holdout,
        artifact,
        verified_input_artifact_sha256=HASH,
        feature_set_version="outage-features-v1",
    )
    assert result.frame.gust_max.tolist() == [1997.0]


def test_calibration_and_holdout_values_cannot_change_fitted_parameters():
    original = _frame()
    changed = original.copy()
    changed.loc[[0, 2, 4], "gust_max"] = [-99_999.0, 77_777.0, 42_424.0]

    kwargs = {
        "feature_columns": ["gust_max"],
        "verified_input_artifact_sha256": HASH,
        "feature_set_version": "outage-features-v1",
    }
    first = fit_feature_transforms(original, _manifest(), **kwargs)
    second = fit_feature_transforms(changed, _manifest(), **kwargs)

    assert first == second
    assert first.artifact_sha256 == second.artifact_sha256


def test_feature_output_carries_versioned_input_and_transform_provenance():
    artifact = fit_feature_transforms(
        _frame(),
        _manifest(),
        feature_columns=["gust_max"],
        verified_input_artifact_sha256=HASH,
        feature_set_version="outage-features-v1",
    )
    result = apply_feature_transforms(
        _frame().iloc[[2]],
        artifact,
        verified_input_artifact_sha256=HASH,
        feature_set_version="outage-features-v1",
    )

    assert result.provenance == {
        "transform_sha256": artifact.artifact_sha256,
        "transform_version": TRANSFORM_VERSION,
        "split_id": "split-test",
        "source_input_sha256": HASH,
        "feature_set_version": "outage-features-v1",
    }


def test_fit_rejects_a_partial_or_mismatched_source_artifact():
    with pytest.raises(TransformError, match="exactly match"):
        fit_feature_transforms(
            _frame().iloc[[1, 3]],
            _manifest(),
            feature_columns=["gust_max"],
            verified_input_artifact_sha256=HASH,
            feature_set_version="outage-features-v1",
        )
    with pytest.raises(TransformError, match="hash"):
        fit_feature_transforms(
            _frame(),
            _manifest(),
            feature_columns=["gust_max"],
            verified_input_artifact_sha256="b" * 64,
            feature_set_version="outage-features-v1",
        )


def test_apply_rejects_a_different_input_or_feature_set_version():
    artifact = fit_feature_transforms(
        _frame(),
        _manifest(),
        feature_columns=["gust_max"],
        verified_input_artifact_sha256=HASH,
        feature_set_version="outage-features-v1",
    )
    with pytest.raises(TransformError, match="hash"):
        apply_feature_transforms(
            _frame().iloc[[0]],
            artifact,
            verified_input_artifact_sha256="b" * 64,
            feature_set_version="outage-features-v1",
        )
    with pytest.raises(TransformError, match="feature_set_version"):
        apply_feature_transforms(
            _frame().iloc[[0]],
            artifact,
            verified_input_artifact_sha256=HASH,
            feature_set_version="outage-features-v2",
        )

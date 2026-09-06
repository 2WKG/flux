"""Leakage and provenance checks for 2WKG-208 feature transforms."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

import numpy as np
import pandas as pd
import pytest

from models.outage.contracts import Partition, SplitAssignment, SplitManifest, WindowKey
from models.outage.split import manifest_sha256
from models.outage.transforms import (
    TRANSFORM_VERSION,
    FeatureTransformArtifact,
    NumericTransform,
    TransformError,
    apply_feature_transforms,
    feature_frame_sha256,
    fit_feature_transforms,
)


def _key(at: datetime) -> WindowKey:
    return WindowKey(county_fips="48453", scenario_id="historical", window_start=at)


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


HASH = feature_frame_sha256(_frame())
"""The real digest of the fixture frame; the manifest is built for exactly it."""


def _manifest(input_artifact_sha256: str = HASH) -> SplitManifest:
    manifest = SplitManifest(
        split_id="split-pending",
        seed=7,
        input_artifact_sha256=input_artifact_sha256,
        assignments=(
            SplitAssignment(
                key=_key(datetime(2021, 2, 15, tzinfo=UTC)), partition=Partition.HOLDOUT
            ),
            SplitAssignment(
                key=_key(datetime(2022, 1, 1, tzinfo=UTC)), partition=Partition.TRAIN
            ),
            SplitAssignment(
                key=_key(datetime(2023, 1, 1, tzinfo=UTC)),
                partition=Partition.CALIBRATION,
            ),
            SplitAssignment(
                key=_key(datetime(2024, 1, 1, tzinfo=UTC)), partition=Partition.TRAIN
            ),
            SplitAssignment(
                key=_key(datetime(2024, 7, 10, tzinfo=UTC)),
                partition=Partition.EXCLUDED,
            ),
        ),
    )
    return manifest.model_copy(
        update={"split_id": f"split-{manifest_sha256(manifest)[:16]}"}
    )


def _fit(
    frame: pd.DataFrame, manifest: SplitManifest | None = None
) -> FeatureTransformArtifact:
    manifest = (
        manifest if manifest is not None else _manifest(feature_frame_sha256(frame))
    )
    return fit_feature_transforms(
        frame,
        manifest,
        feature_columns=["gust_max"],
        verified_input_artifact_sha256=manifest.input_artifact_sha256,
        feature_set_version="outage-features-v1",
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

    first = _fit(original)
    second = _fit(changed)

    # Non-training values never reach a statistic ...
    assert first.transforms == second.transforms
    # ... but the changed frame is a different source artifact, and the
    # fitted artifact's hash says so through its source_input_sha256.
    assert first.source_input_sha256 != second.source_input_sha256
    assert first.artifact_sha256 != second.artifact_sha256


def test_fit_rejects_a_changed_frame_presented_under_the_manifest_hash():
    changed = _frame()
    changed.loc[3, "gust_max"] = 21.0  # a training value

    with pytest.raises(TransformError, match="frame digest"):
        fit_feature_transforms(
            changed,
            _manifest(),
            feature_columns=["gust_max"],
            verified_input_artifact_sha256=HASH,
            feature_set_version="outage-features-v1",
        )

    holdout_only = _frame()
    holdout_only.loc[0, "gust_max"] = 12_345.0  # a holdout value
    with pytest.raises(TransformError, match="frame digest"):
        fit_feature_transforms(
            holdout_only,
            _manifest(),
            feature_columns=["gust_max"],
            verified_input_artifact_sha256=HASH,
            feature_set_version="outage-features-v1",
        )


def test_feature_frame_sha256_is_canonical_and_covers_every_value():
    frame = _frame()
    reordered_rows = frame.iloc[[4, 2, 0, 3, 1]].reset_index(drop=True)
    reordered_columns = frame[
        ["gust_max", "window_start", "scenario_id", "county_fips"]
    ]
    assert feature_frame_sha256(reordered_rows) == HASH
    assert feature_frame_sha256(reordered_columns) == HASH

    one_value = frame.copy()
    one_value.loc[2, "gust_max"] = 1_000.5
    assert feature_frame_sha256(one_value) != HASH

    missing_value = frame.copy()
    missing_value.loc[2, "gust_max"] = np.nan
    assert feature_frame_sha256(missing_value) != HASH

    extra_column = frame.assign(extra=1)
    assert feature_frame_sha256(extra_column) != HASH
    assert feature_frame_sha256(extra_column.drop(columns="extra")) == HASH

    assert feature_frame_sha256(frame) == HASH  # pure: the frame is unchanged
    with pytest.raises(TransformError, match="duplicate identities"):
        feature_frame_sha256(pd.concat([frame, frame.iloc[[1]]]))


def test_artifact_sha256_is_the_digest_of_the_full_canonical_artifact():
    artifact = _fit(_frame())

    expected_document = {
        "transform_version": TRANSFORM_VERSION,
        "split_id": _manifest().split_id,
        "source_input_sha256": HASH,
        "feature_set_version": "outage-features-v1",
        "transforms": [
            {"name": "gust_max", "impute_value": 15.0, "mean": 15.0, "scale": 5.0},
        ],
    }
    encoded = json.dumps(expected_document, sort_keys=True, separators=(",", ":"))
    assert artifact.artifact_sha256 == sha256(encoded.encode("utf-8")).hexdigest()


def test_altering_or_dropping_any_fitted_value_changes_artifact_sha256():
    artifact = _fit(_frame())
    baseline = artifact.artifact_sha256
    transform = artifact.transforms[0]

    for field in ("impute_value", "mean", "scale"):
        altered = replace(transform, **{field: getattr(transform, field) + 1.0})
        assert replace(artifact, transforms=(altered,)).artifact_sha256 != baseline, (
            field
        )
    renamed = replace(transform, name="gust_min")
    assert replace(artifact, transforms=(renamed,)).artifact_sha256 != baseline

    dropped = replace(artifact, transforms=())
    assert dropped.artifact_sha256 != baseline
    extra = NumericTransform(name="temp_min", impute_value=0.0, mean=0.0, scale=1.0)
    assert replace(artifact, transforms=(transform, extra)).artifact_sha256 != baseline

    for field, value in (
        ("transform_version", "9.9.9"),
        ("split_id", "split-0000000000000000"),
        ("source_input_sha256", "b" * 64),
        ("feature_set_version", "outage-features-v2"),
    ):
        assert replace(artifact, **{field: value}).artifact_sha256 != baseline, field


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
        "split_id": _manifest().split_id,
        "source_input_sha256": HASH,
        "feature_set_version": "outage-features-v1",
    }


def test_fit_rejects_a_partial_or_mismatched_source_artifact():
    partial = _frame().iloc[[1, 3]]
    with pytest.raises(TransformError, match="frame digest"):
        fit_feature_transforms(
            partial,
            _manifest(),
            feature_columns=["gust_max"],
            verified_input_artifact_sha256=HASH,
            feature_set_version="outage-features-v1",
        )
    # Even a manifest built for the partial frame's own digest cannot fit it:
    # the population must match the manifest exactly.
    with pytest.raises(TransformError, match="exactly match"):
        fit_feature_transforms(
            partial,
            _manifest(feature_frame_sha256(partial)),
            feature_columns=["gust_max"],
            verified_input_artifact_sha256=feature_frame_sha256(partial),
            feature_set_version="outage-features-v1",
        )


def test_fit_rejects_a_manifest_whose_assignments_no_longer_match_its_split_id():
    manifest = _manifest()
    tampered_assignments = (
        SplitAssignment(key=manifest.assignments[0].key, partition=Partition.TRAIN),
        *manifest.assignments[1:],
    )
    tampered = manifest.model_copy(update={"assignments": tampered_assignments})

    with pytest.raises(TransformError, match="split_id"):
        fit_feature_transforms(
            _frame(),
            tampered,
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

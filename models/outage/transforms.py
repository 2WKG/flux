"""Leakage-safe feature transforms for the county outage model.

The split manifest is the authority for membership.  Fitting accepts the full,
hashed feature artifact and derives every numeric transform from *only* the
manifest's ``train`` assignments.  Calibration, holdout, and excluded rows are
never used to estimate an imputation value, centre, or scale.

The fitted artifact is deliberately small and serialisable: it carries the
source artifact hash, split id, feature-set version, and transform version so
the values produced later can be traced to exactly the input and split that
created them.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Final

import numpy as np
import pandas as pd

from models.outage.contracts import Partition, SplitManifest

TRANSFORM_VERSION: Final = "1.0.0"
"""Bump when transform semantics change."""

IDENTITY_COLUMNS: Final = ("county_fips", "scenario_id", "window_start")


class TransformError(ValueError):
    """A feature artifact cannot safely be fitted or transformed."""


@dataclass(frozen=True)
class NumericTransform:
    """Train-derived parameters for one numeric feature."""

    name: str
    impute_value: float
    mean: float
    scale: float

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "impute_value": self.impute_value,
            "mean": self.mean,
            "scale": self.scale,
        }


@dataclass(frozen=True)
class FeatureTransformArtifact:
    """Frozen transform parameters plus their reproducibility provenance."""

    transform_version: str
    split_id: str
    source_input_sha256: str
    feature_set_version: str
    transforms: tuple[NumericTransform, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a canonical, JSON-ready representation of this artifact."""

        return {
            "transform_version": self.transform_version,
            "split_id": self.split_id,
            "source_input_sha256": self.source_input_sha256,
            "feature_set_version": self.feature_set_version,
            "transforms": [transform.as_dict() for transform in self.transforms],
        }

    @property
    def artifact_sha256(self) -> str:
        """Canonical digest for storing or comparing the fitted artifact."""

        encoded = json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        return sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TransformedFeatureFrame:
    """Feature values with the frozen artifact that produced them."""

    frame: pd.DataFrame
    artifact: FeatureTransformArtifact

    @property
    def provenance(self) -> dict[str, str]:
        """Metadata that must travel with an emitted feature artifact."""

        return {
            "transform_sha256": self.artifact.artifact_sha256,
            "transform_version": self.artifact.transform_version,
            "split_id": self.artifact.split_id,
            "source_input_sha256": self.artifact.source_input_sha256,
            "feature_set_version": self.artifact.feature_set_version,
        }


def fit_feature_transforms(
    frame: pd.DataFrame,
    manifest: SplitManifest,
    *,
    feature_columns: Sequence[str],
    verified_input_artifact_sha256: str,
    feature_set_version: str,
) -> FeatureTransformArtifact:
    """Fit numeric transforms using only the manifest's training partition.

    ``frame`` must be the complete population represented by ``manifest`` and
    ``verified_input_artifact_sha256`` must be the externally verified digest
    of that versioned source artifact.  Those checks make it impossible to
    sneak calibration or holdout rows into a fitting subset by accident.
    """

    if verified_input_artifact_sha256 != manifest.input_artifact_sha256:
        raise TransformError("verified input artifact hash does not match the split manifest")
    if not feature_set_version.strip():
        raise TransformError("feature_set_version must not be empty")

    columns = _validate_feature_columns(frame, feature_columns)
    frame_keys = _frame_keys(frame)
    partition_by_key = {
        _manifest_key(assignment.key.county_fips, assignment.key.scenario_id, assignment.key.window_start): assignment.partition
        for assignment in manifest.assignments
    }
    if len(partition_by_key) != len(manifest.assignments):
        raise TransformError("split manifest contains duplicate feature identities")
    if set(frame_keys) != set(partition_by_key):
        raise TransformError("feature frame does not exactly match the split manifest population")

    train_positions = [
        position
        for position, key in enumerate(frame_keys)
        if partition_by_key[key] is Partition.TRAIN
    ]
    if not train_positions:
        raise TransformError("split manifest has no training rows")

    transforms = tuple(
        _fit_numeric_transform(frame.iloc[train_positions][column], column)
        for column in columns
    )
    return FeatureTransformArtifact(
        transform_version=TRANSFORM_VERSION,
        split_id=manifest.split_id,
        source_input_sha256=manifest.input_artifact_sha256,
        feature_set_version=feature_set_version,
        transforms=transforms,
    )


def apply_feature_transforms(
    frame: pd.DataFrame,
    artifact: FeatureTransformArtifact,
    *,
    verified_input_artifact_sha256: str,
    feature_set_version: str,
) -> TransformedFeatureFrame:
    """Apply a frozen artifact to train, calibration, or holdout feature rows.

    This function has no fitting path.  It rejects a different source version
    or feature-set version rather than silently producing incomparable values.
    """

    if verified_input_artifact_sha256 != artifact.source_input_sha256:
        raise TransformError("verified input artifact hash does not match the transform artifact")
    if feature_set_version != artifact.feature_set_version:
        raise TransformError("feature_set_version does not match the transform artifact")

    result = frame.copy(deep=True)
    for transform in artifact.transforms:
        if transform.name not in result.columns:
            raise TransformError(f"feature frame is missing transform column {transform.name!r}")
        values = _numeric_values(result[transform.name], transform.name)
        result[transform.name] = (values.fillna(transform.impute_value) - transform.mean) / transform.scale
    return TransformedFeatureFrame(frame=result, artifact=artifact)


def _validate_feature_columns(frame: pd.DataFrame, feature_columns: Sequence[str]) -> tuple[str, ...]:
    columns = tuple(feature_columns)
    if not columns:
        raise TransformError("feature_columns must not be empty")
    if len(set(columns)) != len(columns):
        raise TransformError("feature_columns must not contain duplicates")
    missing = set(columns).difference(frame.columns)
    if missing:
        raise TransformError(f"feature frame is missing columns: {sorted(missing)}")
    return columns


def _frame_keys(frame: pd.DataFrame) -> tuple[tuple[str, str, pd.Timestamp], ...]:
    missing = set(IDENTITY_COLUMNS).difference(frame.columns)
    if missing:
        raise TransformError(f"feature frame is missing identity columns: {sorted(missing)}")
    counties = frame["county_fips"].astype("string")
    scenarios = frame["scenario_id"].astype("string")
    if counties.isna().any() or not counties.str.fullmatch(r"\d{5}").all():
        raise TransformError("county_fips must be a five-digit string")
    if scenarios.isna().any() or scenarios.str.strip().eq("").any():
        raise TransformError("scenario_id must not be empty")
    try:
        starts = pd.to_datetime(frame["window_start"], utc=True, errors="raise")
    except (TypeError, ValueError) as error:
        raise TransformError("window_start must be a valid timestamp") from error
    keys = tuple(zip(counties.astype(str), scenarios.astype(str), starts, strict=True))
    if len(set(keys)) != len(keys):
        raise TransformError("feature frame contains duplicate identities")
    return keys


def _manifest_key(county_fips: str, scenario_id: str, window_start: object) -> tuple[str, str, pd.Timestamp]:
    return county_fips, scenario_id, pd.Timestamp(window_start)


def _fit_numeric_transform(values: pd.Series, name: str) -> NumericTransform:
    numeric = _numeric_values(values, name)
    observed = numeric.dropna()
    if observed.empty:
        raise TransformError(f"training feature {name!r} has no observed values")
    impute_value = float(observed.median())
    imputed = numeric.fillna(impute_value)
    mean = float(imputed.mean())
    scale = float(np.sqrt(np.mean(np.square(imputed - mean))))
    # Constant columns become exactly zero after centring, the conventional
    # StandardScaler behaviour; use 1 so the stored artifact is finite.
    if scale == 0.0:
        scale = 1.0
    return NumericTransform(name=name, impute_value=impute_value, mean=mean, scale=scale)


def _numeric_values(values: pd.Series, name: str) -> pd.Series:
    try:
        numeric = pd.to_numeric(values, errors="raise").astype("float64")
    except (TypeError, ValueError) as error:
        raise TransformError(f"feature {name!r} must be numeric") from error
    if np.isinf(numeric.to_numpy(dtype=float, na_value=np.nan)).any():
        raise TransformError(f"feature {name!r} contains infinite values")
    return numeric

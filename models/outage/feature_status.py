"""Explicit feature availability and train-only standardization helpers.

The specification reserves ``models.outage.features`` for the bulk DuckDB
feature builder; these small contract-row helpers deliberately use a separate
module path.

This module is the per-row, contract-typed face of feature assembly
(2WKG-119).  It does **not** implement its own standardization: fitting and
applying numeric transforms are delegated to :mod:`models.outage.transforms`
(2WKG-208), which is the single train-only fitter in the tree.  That module
verifies the split manifest, digests the fitted frame against the manifest's
``input_artifact_sha256``, imputes fit-time gaps with the training median,
centres and scales with training statistics, and hashes the fitted artifact.

What this module adds on top:

* ``RawFeature`` carries a unit and an availability status per source value.
  Units are not part of the numeric frame, so conflicting units for one
  feature across training rows are rejected here as a named
  :class:`FeatureFitError` before anything is pooled.
* ``assemble_features`` never emits an imputed value for a source gap.  The
  transform artifact's ``impute_value`` exists for fitting statistics only;
  a source that is absent, non-present, non-finite, or in another unit is
  emitted with an explicit ``FeatureStatus`` and a reason, exactly as the
  ``FeatureRow`` contract requires.  A source already labelled ``IMPUTED``
  upstream keeps that status and is standardized like a present value.
* ``FeatureArtifact`` has a canonical JSON encoding and a SHA-256 digest so
  "deterministic feature artifacts" is a property of the bytes, not of a
  dataclass equality.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite, isnan

import pandas as pd

from .contracts import (
    FeatureRow,
    FeatureStatus,
    FeatureValue,
    Partition,
    SplitManifest,
    WindowKey,
)
from .transforms import (
    IDENTITY_COLUMNS,
    FeatureTransformArtifact,
    NumericTransform,
    TransformError,
    apply_feature_transforms,
    feature_frame_sha256,
    fit_feature_transforms,
)

UNIT_COLUMN_SUFFIX = "__unit"
"""Suffix of the per-feature unit column in :func:`source_frame`."""

MISSING_SOURCE_FEATURE = "missing_source_feature"
INVALID_SOURCE_VALUE = "invalid_source_value"
INCOMPATIBLE_SOURCE_UNIT = "incompatible_source_unit"
IMPUTED_SOURCE_VALUE = "imputed_source_value"
NOT_IN_FITTED_FEATURE_SET = "not_in_fitted_feature_set"


class FeatureError(TransformError):
    """Features cannot be fitted or assembled safely."""


class FeatureFitError(FeatureError):
    """The training population cannot yield a trustworthy standardizer."""


class FeatureAssemblyError(FeatureError):
    """A request does not match the fitted standardizer artifact."""


@dataclass(frozen=True)
class RawFeature:
    """One source value and its availability reason before transformation."""

    value: float | None
    unit: str
    status: FeatureStatus = FeatureStatus.PRESENT
    reason: str | None = None

    @property
    def is_usable(self) -> bool:
        """True when the value may be standardized (present or already imputed)."""

        return (
            self.status in (FeatureStatus.PRESENT, FeatureStatus.IMPUTED)
            and self.value is not None
            and isfinite(self.value)
        )


@dataclass(frozen=True)
class StandardizerArtifact:
    """Fitted transforms, units, and evidence for each source row."""

    transforms: FeatureTransformArtifact
    units: tuple[tuple[str, str], ...]
    source_row_sha256s: tuple[tuple[WindowKey, str], ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(transform.name for transform in self.transforms.transforms)

    def transform_for(self, name: str) -> NumericTransform:
        for transform in self.transforms.transforms:
            if transform.name == name:
                return transform
        raise KeyError(name)

    def unit_for(self, name: str) -> str:
        for unit_name, unit in self.units:
            if unit_name == name:
                return unit
        raise KeyError(name)

    def source_row_sha256_for(self, key: WindowKey) -> str:
        for row_key, row_sha256 in self.source_row_sha256s:
            if row_key == key:
                return row_sha256
        raise KeyError(key)

    def as_dict(self) -> dict[str, object]:
        return {
            "transforms": self.transforms.as_dict(),
            "units": [[name, unit] for name, unit in self.units],
            "source_rows": [
                [key.model_dump(mode="json"), row_sha256]
                for key, row_sha256 in self.source_row_sha256s
            ],
        }

    def canonical_json(self) -> str:
        return _canonical_json(self.as_dict())

    @property
    def artifact_sha256(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FeatureArtifact:
    """Contract row plus explicit per-feature reasons that the row shape omits."""

    row: FeatureRow
    missing_reasons: tuple[tuple[str, str], ...]
    transform_version: str
    transform_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "row": self.row.model_dump(mode="json"),
            "missing_reasons": [
                [name, reason] for name, reason in self.missing_reasons
            ],
            "transform_version": self.transform_version,
            "transform_sha256": self.transform_sha256,
        }

    def canonical_json(self) -> str:
        return _canonical_json(self.as_dict())

    @property
    def artifact_sha256(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()


def source_frame(
    source_rows: Mapping[WindowKey, Mapping[str, RawFeature]],
    feature_names: Sequence[str],
) -> pd.DataFrame:
    """Return the canonical numeric frame for ``source_rows``.

    This frame *is* the input artifact for :func:`fit_standardizers`: its
    :func:`feature_frame_sha256` digest is what the split manifest must cite
    as ``input_artifact_sha256``.  Rows are ordered by identity; each feature
    has a float column (``NaN`` where the source is not usable) and a
    ``<name>__unit`` string column, so a unit change alters the digest too.
    """

    names = _feature_names(feature_names)
    ordered = sorted(
        source_rows.items(),
        key=lambda item: (
            item[0].county_fips,
            item[0].scenario_id,
            item[0].window_start,
        ),
    )
    columns: dict[str, list[object]] = {column: [] for column in IDENTITY_COLUMNS}
    for name in names:
        columns[name] = []
        columns[f"{name}{UNIT_COLUMN_SUFFIX}"] = []
    for key, features in ordered:
        columns["county_fips"].append(key.county_fips)
        columns["scenario_id"].append(key.scenario_id)
        columns["window_start"].append(key.window_start)
        for name in names:
            source = features.get(name)
            columns[name].append(
                float(source.value)
                if source is not None and source.is_usable
                else float("nan")
            )
            columns[f"{name}{UNIT_COLUMN_SUFFIX}"].append(
                source.unit if source is not None else None
            )
    frame = pd.DataFrame(columns)
    for name in names:
        frame[name] = frame[name].astype("float64")
        frame[f"{name}{UNIT_COLUMN_SUFFIX}"] = frame[
            f"{name}{UNIT_COLUMN_SUFFIX}"
        ].astype(object)
    return frame


def fit_standardizers(
    *,
    source_rows: Mapping[WindowKey, Mapping[str, RawFeature]],
    split: SplitManifest,
    feature_names: Sequence[str],
    feature_set_version: str,
) -> StandardizerArtifact:
    """Fit standardizers for ``feature_names`` from the manifest's TRAIN rows only.

    ``source_rows`` must be the complete population the manifest was built
    for; :func:`models.outage.transforms.fit_feature_transforms` rejects a
    population or digest that does not match the manifest, a manifest whose
    id no longer binds its membership, a feature with no training value, and
    a manifest with no training rows.  Conflicting units for one feature
    across training rows are a :class:`FeatureFitError` here.
    """

    names = _feature_names(feature_names)
    partitions = {
        assignment.key: assignment.partition for assignment in split.assignments
    }
    train_units: dict[str, set[str]] = {name: set() for name in names}
    train_rows = 0
    for key, features in source_rows.items():
        if partitions.get(key) is not Partition.TRAIN:
            continue
        train_rows += 1
        for name in names:
            source = features.get(name)
            if source is not None:
                train_units[name].add(source.unit)
    if not train_rows:
        raise FeatureFitError("split manifest has no training rows")
    units: list[tuple[str, str]] = []
    for name in names:
        seen = train_units[name]
        if not seen:
            raise FeatureFitError(f"training feature {name!r} has no source values")
        if len(seen) > 1:
            raise FeatureFitError(
                f"training feature {name!r} has conflicting units {sorted(seen)}"
            )
        units.append((name, next(iter(seen))))

    frame = source_frame(source_rows, names)
    try:
        transforms = fit_feature_transforms(
            frame,
            split,
            feature_columns=names,
            verified_input_artifact_sha256=feature_frame_sha256(frame),
            feature_set_version=feature_set_version,
        )
    except TransformError as error:
        raise FeatureFitError(str(error)) from error
    return StandardizerArtifact(
        transforms=transforms,
        units=tuple(units),
        source_row_sha256s=tuple(
            (key, _source_row_sha256(key, features))
            for key, features in sorted(
                source_rows.items(),
                key=lambda item: (
                    item[0].county_fips,
                    item[0].scenario_id,
                    item[0].window_start,
                ),
            )
        ),
    )


def assemble_features(
    *,
    key: WindowKey,
    source_features: Mapping[str, RawFeature],
    standardizers: StandardizerArtifact,
    feature_set_version: str,
    source_input_sha256: str,
) -> FeatureArtifact:
    """Apply fitted standardizers without concealing missing or invalid sources.

    ``feature_set_version`` and ``source_input_sha256`` must equal the values
    the standardizers were fitted under.  The supplied row must also exactly
    match the source-row evidence captured at fit time; a copied artifact hash
    cannot label arbitrary values as verified input.  Any mismatch is a
    :class:`FeatureAssemblyError`, never a silently incomparable row.  The
    arithmetic is :func:`models.outage.transforms.apply_feature_transforms`;
    cells it would impute are never emitted, they become explicit statuses.
    """

    names = standardizers.names
    try:
        expected_row_sha256 = standardizers.source_row_sha256_for(key)
    except KeyError as error:
        raise FeatureAssemblyError(
            "source row is not present in the fitted artifact"
        ) from error
    if _source_row_sha256(key, source_features) != expected_row_sha256:
        raise FeatureAssemblyError(
            "source feature content does not match the fitted artifact evidence"
        )
    usable: dict[str, float] = {}
    for name in names:
        source = source_features.get(name)
        if (
            source is not None
            and source.is_usable
            and source.unit == standardizers.unit_for(name)
        ):
            usable[name] = float(source.value)  # type: ignore[arg-type]

    frame = pd.DataFrame(
        {
            "county_fips": [key.county_fips],
            "scenario_id": [key.scenario_id],
            "window_start": [key.window_start],
            **{name: [usable.get(name, float("nan"))] for name in names},
        }
    )
    try:
        transformed = apply_feature_transforms(
            frame,
            standardizers.transforms,
            verified_input_artifact_sha256=source_input_sha256,
            feature_set_version=feature_set_version,
        )
    except TransformError as error:
        raise FeatureAssemblyError(str(error)) from error

    values: list[tuple[str, FeatureValue]] = []
    reasons: list[tuple[str, str]] = []
    for name in names:
        unit = standardizers.unit_for(name)
        source = source_features.get(name)
        if source is None:
            values.append(
                (name, FeatureValue(status=FeatureStatus.MISSING_SOURCE, unit=unit))
            )
            reasons.append((name, MISSING_SOURCE_FEATURE))
            continue
        if source.status not in (FeatureStatus.PRESENT, FeatureStatus.IMPUTED):
            values.append((name, FeatureValue(status=source.status, unit=unit)))
            reasons.append((name, source.reason or INVALID_SOURCE_VALUE))
            continue
        if not source.is_usable:
            values.append(
                (name, FeatureValue(status=FeatureStatus.MISSING_SOURCE, unit=unit))
            )
            reasons.append((name, source.reason or INVALID_SOURCE_VALUE))
            continue
        if source.unit != unit:
            values.append(
                (name, FeatureValue(status=FeatureStatus.MISSING_SOURCE, unit=unit))
            )
            reasons.append((name, INCOMPATIBLE_SOURCE_UNIT))
            continue
        standardized = float(transformed.frame[name].iloc[0])
        values.append(
            (name, FeatureValue(value=standardized, status=source.status, unit=unit))
        )
        if source.status is FeatureStatus.IMPUTED:
            reasons.append((name, source.reason or IMPUTED_SOURCE_VALUE))
    for name in sorted(set(source_features).difference(names)):
        reasons.append((name, NOT_IN_FITTED_FEATURE_SET))

    return FeatureArtifact(
        row=FeatureRow(
            key=key,
            feature_set_version=feature_set_version,
            features=tuple(values),
            source_input_sha256=source_input_sha256,
        ),
        missing_reasons=tuple(reasons),
        transform_version=standardizers.transforms.transform_version,
        transform_sha256=standardizers.transforms.artifact_sha256,
    )


def _feature_names(feature_names: Sequence[str]) -> tuple[str, ...]:
    names = tuple(feature_names)
    if not names:
        raise FeatureFitError("feature_names must not be empty")
    if len(set(names)) != len(names):
        raise FeatureFitError("feature_names must not contain duplicates")
    if any(
        not name or name.endswith(UNIT_COLUMN_SUFFIX) or name in IDENTITY_COLUMNS
        for name in names
    ):
        raise FeatureFitError(
            f"feature names must be non-empty, not identity columns, and not end with {UNIT_COLUMN_SUFFIX!r}"
        )
    return tuple(sorted(names))


def _canonical_json(document: object) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _source_row_sha256(key: WindowKey, features: Mapping[str, RawFeature]) -> str:
    """Digest raw row content before transform-time missing-value handling."""

    document = {
        "key": key.model_dump(mode="json"),
        "features": {
            name: {
                "value": _canonical_raw_value(feature.value),
                "unit": feature.unit,
                "status": feature.status.value,
                "reason": feature.reason,
            }
            for name, feature in sorted(features.items())
        },
    }
    return sha256(_canonical_json(document).encode("utf-8")).hexdigest()


def _canonical_raw_value(value: float | None) -> float | str | None:
    if value is None or isfinite(value):
        return value
    if isnan(value):
        return "NaN"
    return "Infinity" if value > 0 else "-Infinity"

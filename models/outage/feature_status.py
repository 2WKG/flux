"""Explicit feature availability and train-only standardization helpers.

The specification reserves ``models.outage.features`` for the bulk DuckDB
feature builder; these small contract-row helpers deliberately use a separate
module path.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from math import fsum, isfinite, sqrt

from .contracts import (
    FeatureRow,
    FeatureStatus,
    FeatureValue,
    Partition,
    SplitManifest,
    WindowKey,
)


class FeatureFitError(ValueError):
    """Source features cannot form a safe deterministic transform."""


@dataclass(frozen=True)
class RawFeature:
    """One source value and its availability reason before transformation."""

    value: float | None
    unit: str
    status: FeatureStatus = FeatureStatus.PRESENT
    reason: str | None = None


@dataclass(frozen=True)
class FittedTransform:
    """A transform fitted exclusively from train-partition values."""

    name: str
    unit: str
    mean: float
    scale: float
    fit_partition: Partition = Partition.TRAIN


@dataclass(frozen=True)
class FeatureArtifact:
    """Contract row plus explicit per-feature reasons that the row shape omits."""

    row: FeatureRow
    missing_reasons: tuple[tuple[str, str], ...]
    transform_version: str


def fit_standardizers(
    *,
    source_rows: Mapping[WindowKey, Mapping[str, RawFeature]],
    split: SplitManifest,
) -> tuple[FittedTransform, ...]:
    """Fit deterministic mean/scale transforms using only frozen train rows."""
    partitions = {
        assignment.key: assignment.partition for assignment in split.assignments
    }
    values: dict[str, list[float]] = defaultdict(list)
    units: dict[str, str] = {}
    for key, features in source_rows.items():
        if partitions.get(key) is not Partition.TRAIN:
            continue
        for name, source in features.items():
            if (
                source.status not in {FeatureStatus.PRESENT, FeatureStatus.IMPUTED}
                or source.value is None
                or not isfinite(source.value)
            ):
                continue
            known_unit = units.setdefault(name, source.unit)
            if known_unit != source.unit:
                raise FeatureFitError(
                    f"feature {name!r} has conflicting units {known_unit!r}/{source.unit!r}"
                )
            values[name].append(source.value)

    transforms: list[FittedTransform] = []
    for name in sorted(values):
        samples = values[name]
        mean = fsum(samples) / len(samples)
        variance = fsum((sample - mean) ** 2 for sample in samples) / len(samples)
        transforms.append(
            FittedTransform(
                name=name,
                unit=units[name],
                mean=mean,
                scale=sqrt(variance) or 1.0,
            )
        )
    return tuple(transforms)


def assemble_features(
    *,
    key: WindowKey,
    source_features: Mapping[str, RawFeature],
    transforms: tuple[FittedTransform, ...],
    feature_set_version: str,
    source_input_sha256: str,
) -> FeatureArtifact:
    """Apply fitted transforms without concealing missing or invalid source values."""
    configured = {transform.name: transform for transform in transforms}
    values: list[tuple[str, FeatureValue]] = []
    reasons: list[tuple[str, str]] = []
    for name in sorted(configured):
        transform = configured[name]
        source = source_features.get(name)
        if source is None:
            values.append(
                (
                    name,
                    FeatureValue(
                        status=FeatureStatus.MISSING_SOURCE, unit=transform.unit
                    ),
                )
            )
            reasons.append((name, "missing_source_feature"))
            continue
        if source.unit != transform.unit:
            values.append(
                (
                    name,
                    FeatureValue(
                        status=FeatureStatus.MISSING_SOURCE, unit=transform.unit
                    ),
                )
            )
            reasons.append((name, "incompatible_source_unit"))
            continue
        if (
            source.status in {FeatureStatus.PRESENT, FeatureStatus.IMPUTED}
            and source.value is not None
            and isfinite(source.value)
        ):
            values.append(
                (
                    name,
                    FeatureValue(
                        value=(source.value - transform.mean) / transform.scale,
                        status=source.status,
                        unit=transform.unit,
                    ),
                )
            )
            continue
        status = (
            source.status
            if source.status is not FeatureStatus.PRESENT
            else FeatureStatus.MISSING_SOURCE
        )
        values.append((name, FeatureValue(status=status, unit=transform.unit)))
        reasons.append((name, source.reason or "invalid_source_value"))

    return FeatureArtifact(
        row=FeatureRow(
            key=key,
            feature_set_version=feature_set_version,
            features=tuple(values),
            source_input_sha256=source_input_sha256,
        ),
        missing_reasons=tuple(reasons),
        transform_version="standardize-train-only-v1",
    )

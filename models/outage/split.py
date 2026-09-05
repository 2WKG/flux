"""Deterministic, immutable train/calibration/holdout assignments.

The split is deliberately based on the identity of a county/window, never on
row order. ``SplitManifest`` is the artifact passed to training and
evaluation, so recreating a split from the same input artifact is stable and a
later data refresh cannot silently reshuffle an existing model's population.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from math import floor
from types import MappingProxyType

import pandas as pd

from models.outage.contracts import (
    CountyOutageRow,
    Partition,
    SplitAssignment,
    SplitManifest,
    WindowKey,
)

DEFAULT_SEED = 7
DEFAULT_CALIBRATION_FRACTION = 0.15
"""The validation fraction specified for the non-holdout training data."""

# Ends are exclusive so every 6-hour window on the stated final calendar day
# remains held out. Keeping these timezone-aware also matches WindowKey.
HOLDOUT_WINDOWS: dict[str, tuple[datetime, datetime, tuple[str, ...]]] = {
    "uri_2021": (
        datetime(2021, 2, 10, tzinfo=UTC),
        datetime(2021, 2, 24, tzinfo=UTC),
        ("TX",),
    ),
    "beryl_2024": (
        datetime(2024, 7, 4, tzinfo=UTC),
        datetime(2024, 7, 15, tzinfo=UTC),
        ("TX",),
    ),
    "helene_2024": (
        datetime(2024, 9, 22, tzinfo=UTC),
        datetime(2024, 10, 4, tzinfo=UTC),
        ("FL", "GA", "NC", "SC", "TN", "VA"),
    ),
}

TX_BERYL_LEAKAGE_CUTOFF = datetime(2024, 7, 1, tzinfo=UTC)
"""Texas windows on/after this instant cannot train or calibrate Beryl."""

TX_POST_BERYL_GUARD = "tx_post_beryl_guard"
"""An unevaluated holdout bucket reserved by the Beryl leakage guard."""


class SplitError(ValueError):
    """The supplied rows cannot form an unambiguous, safe split."""


@dataclass(frozen=True)
class _SplitRow:
    key: WindowKey
    state: str


def build_split_manifest(
    rows: Iterable[CountyOutageRow],
    *,
    states_by_county: Mapping[str, str],
    input_artifact_sha256: str,
    seed: int = DEFAULT_SEED,
    calibration_fraction: float = DEFAULT_CALIBRATION_FRACTION,
) -> SplitManifest:
    """Create a frozen manifest for observed county-window labels.

    Fixture labels are intentionally rejected: the 2WKG-120 contract makes
    them a distinct type precisely so they cannot be promoted into train,
    calibration, or evaluation data. ``states_by_county`` is explicit because
    a ``WindowKey`` intentionally carries no mutable county lookup data.
    """

    materialized = tuple(rows)
    if not materialized:
        raise SplitError("cannot create a split manifest with no rows")
    if any(not row.is_trainable for row in materialized):
        raise SplitError("fixture labels cannot appear in a split manifest")

    split_rows = tuple(
        _SplitRow(row.key, _state_for(row.key.county_fips, states_by_county))
        for row in materialized
    )
    assignments = _assign_partitions(split_rows, seed, calibration_fraction)
    assignment_models = tuple(
        SplitAssignment(key=item.key, partition=assignments[item.key])
        for item in sorted(split_rows, key=lambda item: _identity(item.key))
    )
    split_id = _split_id(seed, input_artifact_sha256, assignment_models)
    return SplitManifest(
        split_id=split_id,
        seed=seed,
        input_artifact_sha256=input_artifact_sha256,
        assignments=assignment_models,
    )


def partition_rows(
    rows: Iterable[CountyOutageRow], manifest: SplitManifest
) -> Mapping[Partition, tuple[CountyOutageRow, ...]]:
    """Materialize manifest assignments without modifying the supplied rows.

    Requiring an exact key set prevents accidentally training a model with a
    stale manifest after the source artifact changes.
    """

    materialized = tuple(rows)
    assignment_by_key = {
        assignment.key: assignment.partition for assignment in manifest.assignments
    }
    if len(assignment_by_key) != len(manifest.assignments):
        raise SplitError("manifest contains duplicate WindowKey assignments")
    row_keys = {row.key for row in materialized}
    if len(row_keys) != len(materialized):
        raise SplitError("input rows contain duplicate WindowKey values")
    if row_keys != set(assignment_by_key):
        raise SplitError("rows do not exactly match the manifest assignments")

    buckets: dict[Partition, list[CountyOutageRow]] = {
        partition: [] for partition in Partition
    }
    for row in materialized:
        buckets[assignment_by_key[row.key]].append(row)
    return MappingProxyType(
        {
            partition: tuple(sorted(bucket, key=lambda row: _identity(row.key)))
            for partition, bucket in buckets.items()
        }
    )


def manifest_membership(
    manifest: SplitManifest,
) -> Mapping[Partition, frozenset[WindowKey]]:
    """Return immutable exact membership for each partition.

    This is intentionally derived from the frozen assignments instead of from
    source rows, which makes it suitable for auditing a stored manifest.
    """

    buckets: dict[Partition, set[WindowKey]] = {
        partition: set() for partition in Partition
    }
    seen: set[WindowKey] = set()
    for assignment in manifest.assignments:
        if assignment.key in seen:
            raise SplitError("manifest contains duplicate WindowKey assignments")
        seen.add(assignment.key)
        buckets[assignment.partition].add(assignment.key)
    return MappingProxyType(
        {partition: frozenset(keys) for partition, keys in buckets.items()}
    )


def manifest_sha256(manifest: SplitManifest) -> str:
    """Return the full canonical digest for a manifest's membership and inputs."""

    encoded = _manifest_encoding(
        manifest.seed, manifest.input_artifact_sha256, manifest.assignments
    )
    return sha256(encoded.encode()).hexdigest()


def manifest_summary(manifest: SplitManifest) -> Mapping[str, object]:
    """Return audit metadata: identifier, full hash, row counts, membership."""

    membership = manifest_membership(manifest)
    return MappingProxyType(
        {
            "split_id": manifest.split_id,
            "manifest_sha256": manifest_sha256(manifest),
            "input_artifact_sha256": manifest.input_artifact_sha256,
            "seed": manifest.seed,
            "row_counts": MappingProxyType(
                {partition.value: len(membership[partition]) for partition in Partition}
            ),
            "membership": MappingProxyType(
                {
                    partition.value: tuple(
                        _identity(key)
                        for key in sorted(membership[partition], key=_identity)
                    )
                    for partition in Partition
                }
            ),
        }
    )


def split(
    df: pd.DataFrame,
    *,
    seed: int = DEFAULT_SEED,
    calibration_fraction: float = DEFAULT_CALIBRATION_FRACTION,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    """Return copied train, calibration, and named holdout DataFrames.

    This adapter retains the interface in spec 02. It requires the
    county/window identity and the county's state; callers that need a durable
    artifact should use :func:`build_split_manifest` instead.
    """

    required = {"county_fips", "scenario_id", "window_start", "state"}
    missing = required.difference(df.columns)
    if missing:
        raise SplitError(
            f"split DataFrame is missing required columns: {sorted(missing)}"
        )

    split_rows: list[_SplitRow] = []
    keys: list[WindowKey] = []
    states: list[str] = []
    for _, row in df.loc[
        :, ["county_fips", "scenario_id", "window_start", "state"]
    ].iterrows():
        key = WindowKey(
            county_fips=str(row.county_fips),
            scenario_id=str(row.scenario_id),
            window_start=_as_utc_datetime(row.window_start),
        )
        state = _normalize_state(row.state)
        split_rows.append(_SplitRow(key=key, state=state))
        keys.append(key)
        states.append(state)

    assignments = _assign_partitions(tuple(split_rows), seed, calibration_fraction)
    train = df.iloc[
        [
            position
            for position, key in enumerate(keys)
            if assignments[key] is Partition.TRAIN
        ]
    ].copy(deep=True)
    calibration = df.iloc[
        [
            position
            for position, key in enumerate(keys)
            if assignments[key] is Partition.CALIBRATION
        ]
    ].copy(deep=True)

    holdout_ids = {
        position: _holdout_id(key, states[position])
        for position, key in enumerate(keys)
        if assignments[key] is Partition.HOLDOUT
    }
    holdouts: dict[str, pd.DataFrame] = {}
    for scenario_id in HOLDOUT_WINDOWS:
        positions = [
            position
            for position, holdout_id in holdout_ids.items()
            if holdout_id == scenario_id
        ]
        holdouts[scenario_id] = df.iloc[positions].copy(deep=True)
    guard_positions = [
        position
        for position, holdout_id in holdout_ids.items()
        if holdout_id == TX_POST_BERYL_GUARD
    ]
    if guard_positions:
        holdouts[TX_POST_BERYL_GUARD] = df.iloc[guard_positions].copy(deep=True)
    return train, calibration, holdouts


def _assign_partitions(
    rows: tuple[_SplitRow, ...], seed: int, calibration_fraction: float
) -> dict[WindowKey, Partition]:
    if not 0.0 <= calibration_fraction < 1.0:
        raise SplitError("calibration_fraction must be in [0.0, 1.0)")
    if len({row.key for row in rows}) != len(rows):
        raise SplitError("input rows contain duplicate WindowKey values")

    assignments: dict[WindowKey, Partition] = {}
    candidates: list[_SplitRow] = []
    for row in rows:
        if _holdout_id(row.key, row.state) is not None:
            assignments[row.key] = Partition.HOLDOUT
        else:
            candidates.append(row)

    calibration_keys = _calibration_keys(candidates, seed, calibration_fraction)
    for row in candidates:
        assignments[row.key] = (
            Partition.CALIBRATION if row.key in calibration_keys else Partition.TRAIN
        )
    return assignments


def _calibration_keys(
    candidates: list[_SplitRow], seed: int, calibration_fraction: float
) -> set[WindowKey]:
    """Select an order-independent, month-stratified calibration population."""

    if len(candidates) < 2 or calibration_fraction == 0:
        return set()
    target = min(
        len(candidates) - 1,
        max(1, floor(len(candidates) * calibration_fraction + 0.5)),
    )
    by_month: dict[int, list[_SplitRow]] = defaultdict(list)
    for row in candidates:
        by_month[row.key.window_start.month].append(row)

    quotas = {
        month: floor(len(group) * calibration_fraction)
        for month, group in by_month.items()
    }
    remaining = target - sum(quotas.values())
    for month in sorted(
        by_month,
        key=lambda value: (
            -(len(by_month[value]) * calibration_fraction - quotas[value]),
            value,
        ),
    )[:remaining]:
        quotas[month] += 1

    selected: set[WindowKey] = set()
    for month, group in by_month.items():
        chosen = sorted(group, key=lambda row: _seeded_rank(seed, row.key))[
            : quotas[month]
        ]
        selected.update(row.key for row in chosen)
    return selected


def _holdout_id(key: WindowKey, state: str) -> str | None:
    for scenario_id, (start, end, states) in HOLDOUT_WINDOWS.items():
        if state in states and start <= key.window_start < end:
            return scenario_id
    if state == "TX" and key.window_start >= TX_BERYL_LEAKAGE_CUTOFF:
        return TX_POST_BERYL_GUARD
    return None


def _state_for(county_fips: str, states_by_county: Mapping[str, str]) -> str:
    try:
        return _normalize_state(states_by_county[county_fips])
    except KeyError as error:
        raise SplitError(f"no state supplied for county {county_fips}") from error


def _normalize_state(value: object) -> str:
    state = str(value).strip().upper()
    if len(state) != 2:
        raise SplitError(f"state must be a two-letter abbreviation, got {value!r}")
    return state


def _as_utc_datetime(value: object) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.to_pydatetime()


def _identity(key: WindowKey) -> str:
    return f"{key.county_fips}\x00{key.scenario_id}\x00{key.window_start.isoformat()}"


def _seeded_rank(seed: int, key: WindowKey) -> bytes:
    return sha256(f"{seed}\x00{_identity(key)}".encode()).digest()


def _manifest_encoding(
    seed: int, input_artifact_sha256: str, assignments: tuple[SplitAssignment, ...]
) -> str:
    encoded = "\n".join(
        f"{_identity(assignment.key)}\x00{assignment.partition.value}"
        for assignment in sorted(
            assignments, key=lambda assignment: _identity(assignment.key)
        )
    )
    return f"v1\x00{seed}\x00{input_artifact_sha256}\x00{encoded}"


def _split_id(
    seed: int, input_artifact_sha256: str, assignments: tuple[SplitAssignment, ...]
) -> str:
    return f"split-{sha256(_manifest_encoding(seed, input_artifact_sha256, assignments).encode()).hexdigest()[:16]}"

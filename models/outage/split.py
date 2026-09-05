"""Deterministic, immutable train/calibration/holdout assignments.

The split is deliberately based on the identity of a county/window, never on
row order. ``SplitManifest`` is the artifact passed to training and
evaluation, so recreating a split from the same input artifact is stable and a
later data refresh cannot silently reshuffle an existing model's population.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
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
"""A non-evaluation exclusion reserved by the Beryl leakage guard."""


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
    rows: Iterable[CountyOutageRow],
    manifest: SplitManifest,
    *,
    verified_input_artifact_sha256: str,
) -> Mapping[Partition, tuple[CountyOutageRow, ...]]:
    """Materialize manifest assignments without modifying the supplied rows.

    ``verified_input_artifact_sha256`` is the digest obtained while verifying
    the source artifact, not a digest inferred from the rows in memory.
    Requiring it and an exact key set prevents a stale or tampered manifest
    from silently being used for a refreshed source artifact.
    """

    _verify_manifest_integrity(manifest)
    if verified_input_artifact_sha256 != manifest.input_artifact_sha256:
        raise SplitError("verified input artifact hash does not match the manifest")
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

    if not 0.0 <= calibration_fraction < 1.0:
        raise SplitError("calibration_fraction must be in [0.0, 1.0)")

    # This path is used for the 600k-row feature table.  Do the identity and
    # partition work with vectorized pandas operations rather than creating a
    # Pydantic WindowKey for every row.
    county_fips = df["county_fips"].astype("string")
    scenario_id = df["scenario_id"].astype("string")
    if county_fips.isna().any() or not county_fips.str.fullmatch(r"\d{5}").all():
        raise SplitError("county_fips must be a five-digit string")
    if scenario_id.isna().any() or scenario_id.str.strip().eq("").any():
        raise SplitError("scenario_id must not be empty")

    try:
        window_start = pd.to_datetime(df["window_start"], utc=True, errors="raise")
    except (TypeError, ValueError) as error:
        raise SplitError("window_start must be a valid timestamp") from error
    if (
        window_start.isna().any()
        or (window_start.dt.hour % 6 != 0).any()
        or (window_start.dt.minute != 0).any()
        or (window_start.dt.second != 0).any()
        or (window_start.dt.microsecond != 0).any()
    ):
        raise SplitError("window_start must be aligned to 6h UTC boundaries")

    states = df["state"].astype("string").str.strip().str.upper()
    if states.isna().any() or states.str.len().ne(2).any():
        raise SplitError("state must be a two-letter abbreviation")

    identity = pd.MultiIndex.from_arrays(
        [county_fips, scenario_id, window_start.astype("int64")]
    )
    if identity.duplicated().any():
        raise SplitError("input rows contain duplicate WindowKey values")

    partitions = pd.Series(Partition.TRAIN.value, index=df.index, dtype="string")
    evaluation_ids = pd.Series(pd.NA, index=df.index, dtype="string")
    for scenario, (start, end, eligible_states) in HOLDOUT_WINDOWS.items():
        matches = states.isin(eligible_states) & window_start.ge(start) & window_start.lt(end)
        partitions.loc[matches] = Partition.HOLDOUT.value
        evaluation_ids.loc[matches] = scenario
    post_beryl_guard = (
        states.eq("TX")
        & window_start.ge(TX_BERYL_LEAKAGE_CUTOFF)
        & partitions.eq(Partition.TRAIN.value)
    )
    partitions.loc[post_beryl_guard] = Partition.EXCLUDED.value

    eligible = partitions.eq(Partition.TRAIN.value)
    block_ids = county_fips + "|" + window_start.dt.strftime("%Y-%m")
    calibration_blocks = {
        block
        for block in block_ids.loc[eligible].unique()
        if _seeded_fraction(seed, block) < calibration_fraction
    }
    calibration = eligible & block_ids.isin(calibration_blocks)
    partitions.loc[calibration] = Partition.CALIBRATION.value

    # A train month following a calibration month would consume calibration
    # labels through the 24-hour autoregressive features.  Purge it.  A
    # calibration month may consume preceding train labels, which is the
    # chronological information available to a nowcast at prediction time.
    following_calibration_blocks = {
        _following_month(block) for block in calibration_blocks
    }
    partitions.loc[
        partitions.eq(Partition.TRAIN.value)
        & block_ids.isin(following_calibration_blocks)
    ] = Partition.EXCLUDED.value

    train = df.iloc[_positions(partitions.eq(Partition.TRAIN.value))].copy(deep=True)
    calibration_frame = df.iloc[_positions(partitions.eq(Partition.CALIBRATION.value))].copy(
        deep=True
    )
    holdouts = {
        scenario: df.iloc[_positions(evaluation_ids.eq(scenario).fillna(False))].copy(
            deep=True
        )
        for scenario in HOLDOUT_WINDOWS
    }
    return train, calibration_frame, holdouts


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
        elif _is_post_beryl_guard(row.key, row.state):
            assignments[row.key] = Partition.EXCLUDED
        else:
            candidates.append(row)

    calibration_keys = _calibration_keys(candidates, seed, calibration_fraction)
    for row in candidates:
        assignments[row.key] = (
            Partition.CALIBRATION if row.key in calibration_keys else Partition.TRAIN
        )

    # Never put a training row immediately after a calibration month: its
    # autoregressive features could contain calibration labels.  This is a
    # non-evaluation exclusion, just like the post-Beryl guard.
    calibration_blocks = {_temporal_block(row.key) for row in candidates if row.key in calibration_keys}
    following_blocks = {_following_month(block) for block in calibration_blocks}
    for row in candidates:
        if assignments[row.key] is Partition.TRAIN and _temporal_block(row.key) in following_blocks:
            assignments[row.key] = Partition.EXCLUDED
    return assignments


def _calibration_keys(
    candidates: list[_SplitRow], seed: int, calibration_fraction: float
) -> set[WindowKey]:
    """Select whole county-month blocks with append-stable hash membership.

    A month is a fixed, contiguous county-time block.  It is deliberately
    independent of the population being split: adding a later artifact batch
    can add memberships but cannot reshuffle existing rows.
    """

    if calibration_fraction == 0:
        return set()
    calibration_blocks = {
        _temporal_block(row.key)
        for row in candidates
        if _seeded_fraction(seed, _temporal_block(row.key)) < calibration_fraction
    }
    return {
        row.key for row in candidates if _temporal_block(row.key) in calibration_blocks
    }


def _holdout_id(key: WindowKey, state: str) -> str | None:
    for scenario_id, (start, end, states) in HOLDOUT_WINDOWS.items():
        if state in states and start <= key.window_start < end:
            return scenario_id
    return None


def _is_post_beryl_guard(key: WindowKey, state: str) -> bool:
    return state == "TX" and key.window_start >= TX_BERYL_LEAKAGE_CUTOFF


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


def _identity(key: WindowKey) -> str:
    return f"{key.county_fips}\x00{key.scenario_id}\x00{key.window_start.isoformat()}"


def _temporal_block(key: WindowKey) -> str:
    """Return the fixed county-month block containing ``key``.

    Scenario is intentionally omitted: alternate views of one county-time
    observation must not end up on opposite sides of the split.
    """

    return f"{key.county_fips}|{key.window_start:%Y-%m}"


def _following_month(block: str) -> str:
    county_fips, year_month = block.split("|", maxsplit=1)
    year, month = (int(part) for part in year_month.split("-", maxsplit=1))
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    return f"{county_fips}|{year:04d}-{month:02d}"


def _seeded_fraction(seed: int, value: str) -> float:
    """Map one stable key to [0, 1), without population-wide ranking."""

    rank = int.from_bytes(sha256(f"{seed}\x00{value}".encode()).digest()[:8], "big")
    return rank / 2**64


def _positions(mask: pd.Series) -> list[int]:
    """Return positional indexes, preserving duplicate DataFrame indexes."""

    return mask.to_numpy().nonzero()[0].tolist()


def _verify_manifest_integrity(manifest: SplitManifest) -> None:
    """Reject manifests whose id no longer binds their membership and input."""

    if not re.fullmatch(r"[0-9a-f]{64}", manifest.input_artifact_sha256):
        raise SplitError("manifest input artifact hash is not a SHA-256 digest")
    keys = [assignment.key for assignment in manifest.assignments]
    if len(set(keys)) != len(keys):
        raise SplitError("manifest contains duplicate WindowKey assignments")
    expected_split_id = _split_id(
        manifest.seed, manifest.input_artifact_sha256, manifest.assignments
    )
    if manifest.split_id != expected_split_id:
        raise SplitError("manifest split_id does not match its membership and input hash")


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

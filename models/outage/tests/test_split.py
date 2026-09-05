"""Behavioural tests for immutable outage-model splits (2WKG-117)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from pydantic import ValidationError

from models.outage.contracts import (
    CountyOutageRow,
    FixtureLabel,
    ObservedLabel,
    Partition,
    WindowKey,
)
from models.outage.split import (
    SplitError,
    build_split_manifest,
    manifest_membership,
    manifest_sha256,
    manifest_summary,
    partition_rows,
    split,
)

HASH = "a" * 64
RETRIEVED_AT = datetime(2026, 9, 5, tzinfo=UTC)


def observed(
    county_fips: str, state: str, at: datetime, scenario_id: str = "historical"
) -> tuple[CountyOutageRow, str]:
    row = CountyOutageRow(
        key=WindowKey(
            county_fips=county_fips, scenario_id=scenario_id, window_start=at
        ),
        label=ObservedLabel(
            customers_out_max=1,
            total_customers=10,
            source_dataset_id="eaglei",
            source_file_sha256=HASH,
            retrieved_at=RETRIEVED_AT,
        ),
    )
    return row, state


def sample_rows() -> tuple[tuple[CountyOutageRow, ...], dict[str, str]]:
    rows_and_states = [
        observed("48453", "TX", datetime(2021, 2, 10, tzinfo=UTC)),
        observed("48201", "TX", datetime(2021, 2, 23, 18, tzinfo=UTC)),
        observed("48113", "TX", datetime(2024, 7, 4, tzinfo=UTC)),
        observed("12001", "FL", datetime(2024, 9, 22, tzinfo=UTC)),
        observed("48453", "TX", datetime(2024, 7, 16, tzinfo=UTC)),
    ]
    for month in range(1, 7):
        for county_fips in ("48001", "48003"):
            rows_and_states.append(
                observed(county_fips, "TX", datetime(2023, month, 1, tzinfo=UTC))
            )
    return tuple(item[0] for item in rows_and_states), {
        item[0].key.county_fips: item[1] for item in rows_and_states
    }


def test_manifest_never_assigns_holdouts_to_train_or_calibration():
    rows, states = sample_rows()
    manifest = build_split_manifest(
        rows, states_by_county=states, input_artifact_sha256=HASH
    )
    by_key = {
        assignment.key: assignment.partition for assignment in manifest.assignments
    }

    assert by_key[rows[0].key] is Partition.HOLDOUT
    assert by_key[rows[1].key] is Partition.HOLDOUT
    assert by_key[rows[2].key] is Partition.HOLDOUT
    assert by_key[rows[3].key] is Partition.HOLDOUT
    assert by_key[rows[4].key] is Partition.EXCLUDED
    membership = manifest_membership(manifest)
    assert membership[Partition.HOLDOUT].isdisjoint(membership[Partition.TRAIN])
    assert membership[Partition.HOLDOUT].isdisjoint(membership[Partition.CALIBRATION])


def test_manifest_is_order_independent_reproducible_and_frozen():
    rows, states = sample_rows()
    forward = build_split_manifest(
        rows, states_by_county=states, input_artifact_sha256=HASH
    )
    reversed_manifest = build_split_manifest(
        tuple(reversed(rows)), states_by_county=states, input_artifact_sha256=HASH
    )

    assert forward == reversed_manifest
    assert manifest_sha256(forward) == manifest_sha256(reversed_manifest)
    assert isinstance(forward.assignments, tuple)
    with pytest.raises(ValidationError):
        forward.split_id = "rewritten"


def test_manifest_audit_includes_hash_counts_and_sorted_membership():
    rows, states = sample_rows()
    manifest = build_split_manifest(
        rows, states_by_county=states, input_artifact_sha256=HASH
    )
    summary = manifest_summary(manifest)

    assert len(summary["manifest_sha256"]) == 64
    assert sum(summary["row_counts"].values()) == len(rows)
    assert summary["row_counts"]["holdout"] == 4
    assert summary["row_counts"]["excluded"] >= 1
    assert tuple(summary["membership"]["train"]) == tuple(
        sorted(summary["membership"]["train"])
    )
    with pytest.raises(TypeError):
        summary["split_id"] = "changed"
    with pytest.raises(TypeError):
        summary["row_counts"]["train"] = 0


def test_partition_rows_requires_the_exact_manifest_population():
    rows, states = sample_rows()
    manifest = build_split_manifest(
        rows, states_by_county=states, input_artifact_sha256=HASH
    )
    partitions = partition_rows(
        rows, manifest, verified_input_artifact_sha256=HASH
    )

    assert sum(len(bucket) for bucket in partitions.values()) == len(rows)
    with pytest.raises(TypeError):
        partitions[Partition.TRAIN] = ()
    with pytest.raises(SplitError, match="exactly match"):
        partition_rows(rows[:-1], manifest, verified_input_artifact_sha256=HASH)


def test_partition_rows_binds_verified_input_hash_and_manifest_integrity():
    rows, states = sample_rows()
    manifest = build_split_manifest(
        rows, states_by_county=states, input_artifact_sha256=HASH
    )

    with pytest.raises(SplitError, match="verified input artifact hash"):
        partition_rows(rows, manifest, verified_input_artifact_sha256="b" * 64)

    tampered = manifest.model_copy(update={"split_id": "split-tampered"})
    with pytest.raises(SplitError, match="split_id"):
        partition_rows(rows, tampered, verified_input_artifact_sha256=HASH)


def test_calibration_is_texas_2023_and_is_stable_under_backfill():
    rows = tuple(
        observed("48001", "TX", at)[0]
        for at in (
            datetime(2022, 12, 31, 18, tzinfo=UTC),
            datetime(2023, 1, 1, tzinfo=UTC),
            datetime(2023, 6, 1, tzinfo=UTC),
            datetime(2023, 12, 31, 18, tzinfo=UTC),
            datetime(2024, 1, 1, tzinfo=UTC),
        )
    )
    states = {"48001": "TX"}
    original = build_split_manifest(
        rows, states_by_county=states, input_artifact_sha256=HASH
    )
    assignment = {item.key: item.partition for item in original.assignments}

    assert [assignment[row.key] for row in rows] == [
        Partition.TRAIN,
        Partition.CALIBRATION,
        Partition.CALIBRATION,
        Partition.CALIBRATION,
        Partition.TRAIN,
    ]

    # Backfilling an earlier window must not rewrite any existing assignment.
    appended = (observed("48001", "TX", datetime(2022, 11, 1, tzinfo=UTC))[0],) + rows
    refreshed = build_split_manifest(
        appended, states_by_county=states, input_artifact_sha256="b" * 64
    )
    refreshed_assignment = {
        item.key: item.partition for item in refreshed.assignments
    }
    assert {key: refreshed_assignment[key] for key in assignment} == assignment


def test_calibration_fold_is_spatially_blocked_disjoint_and_has_expected_fraction():
    rows_and_states = []
    for county_fips, state in (("48001", "TX"), ("48003", "TX"), ("12001", "FL")):
        for year in (2022, 2023, 2024):
            rows_and_states.append(
                observed(county_fips, state, datetime(year, 6, 1, tzinfo=UTC))
            )
    rows = tuple(row for row, _ in rows_and_states)
    states = {row.key.county_fips: state for row, state in rows_and_states}

    manifest = build_split_manifest(
        rows, states_by_county=states, input_artifact_sha256=HASH
    )
    membership = manifest_membership(manifest)
    calibration = membership[Partition.CALIBRATION]

    assert {key.county_fips for key in calibration} == {"48001", "48003"}
    assert {key.window_start.year for key in calibration} == {2023}
    assert calibration.isdisjoint(membership[Partition.TRAIN])
    assert len(calibration) / (len(calibration) + len(membership[Partition.TRAIN])) == pytest.approx(
        2 / 9
    )

    frame = pd.DataFrame(
        {
            "county_fips": [row.key.county_fips for row in rows],
            "scenario_id": [row.key.scenario_id for row in rows],
            "window_start": [row.key.window_start for row in rows],
            "state": [states[row.key.county_fips] for row in rows],
        }
    )
    train, calibration_frame, _ = split(frame)
    assert set(zip(train.county_fips, train.window_start)) == {
        (key.county_fips, key.window_start) for key in membership[Partition.TRAIN]
    }
    assert set(zip(calibration_frame.county_fips, calibration_frame.window_start)) == {
        (key.county_fips, key.window_start) for key in calibration
    }


def test_fixture_labels_cannot_enter_a_manifest():
    fixture = CountyOutageRow(
        key=WindowKey(
            county_fips="48453",
            scenario_id="historical",
            window_start=datetime(2023, 1, 1, tzinfo=UTC),
        ),
        label=FixtureLabel(
            customers_out_max=1, total_customers=10, reason="test fixture"
        ),
    )
    with pytest.raises(SplitError, match="fixture"):
        build_split_manifest(
            (fixture,), states_by_county={"48453": "TX"}, input_artifact_sha256=HASH
        )


def test_split_adapter_preserves_input_and_names_only_evaluation_holdouts():
    start = datetime(2023, 1, 1, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "county_fips": "48453",
                "scenario_id": "historical",
                "window_start": start + timedelta(hours=6 * n),
                "state": "TX",
                "marker": n,
            }
            for n in range(20)
        ]
        + [
            {
                "county_fips": "48453",
                "scenario_id": "historical",
                "window_start": datetime(2021, 2, 15, tzinfo=UTC),
                "state": "TX",
                "marker": 100,
            },
            {
                "county_fips": "48453",
                "scenario_id": "historical",
                "window_start": datetime(2024, 7, 2, tzinfo=UTC),
                "state": "TX",
                "marker": 101,
            },
        ]
    )
    original = frame.copy(deep=True)

    train, calibration, holdouts = split(frame)

    pd.testing.assert_frame_equal(frame, original)
    assert set(holdouts) == {
        "uri_2021",
        "beryl_2024",
        "helene_2024",
    }
    assert holdouts["uri_2021"].marker.tolist() == [100]
    assert {100, 101}.isdisjoint(set(train.marker) | set(calibration.marker))
    assert 101 not in set().union(*(set(frame.marker) for frame in holdouts.values()))


def test_split_dataframe_path_does_not_construct_pydantic_keys(monkeypatch):
    frame = pd.DataFrame(
        {
            "county_fips": ["48001"] * 1000,
            "scenario_id": ["historical"] * 1000,
            "window_start": pd.date_range("2023-01-01", periods=1000, freq="6h", tz="UTC"),
            "state": ["TX"] * 1000,
        }
    )

    def unexpected_pydantic_path(*args, **kwargs):
        raise AssertionError("split DataFrame path must remain vectorized")

    monkeypatch.setattr("models.outage.split.WindowKey", unexpected_pydantic_path)
    train, calibration, holdouts = split(frame)

    assert len(train) + len(calibration) + sum(len(value) for value in holdouts.values()) <= len(frame)


def test_split_rejects_ambiguous_or_invalid_input():
    frame = pd.DataFrame(
        [
            {
                "county_fips": "48453",
                "scenario_id": "x",
                "window_start": datetime(2023, 1, 1, tzinfo=UTC),
                "state": "Texas",
            }
        ]
    )
    with pytest.raises(SplitError, match="two-letter"):
        split(frame)

    duplicate = pd.DataFrame(
        [
            {
                "county_fips": "48453",
                "scenario_id": "x",
                "window_start": datetime(2023, 1, 1, tzinfo=UTC),
                "state": "TX",
            },
            {
                "county_fips": "48453",
                "scenario_id": "x",
                "window_start": datetime(2023, 1, 1, tzinfo=UTC),
                "state": "TX",
            },
        ]
    )
    with pytest.raises(SplitError, match="duplicate"):
        split(duplicate)


def test_split_does_not_treat_dataframe_index_as_the_row_identity():
    frame = pd.DataFrame(
        [
            {
                "county_fips": "48453",
                "scenario_id": "historical",
                "window_start": datetime(2021, 2, 15, tzinfo=UTC),
                "state": "TX",
                "marker": "holdout",
            },
            {
                "county_fips": "48453",
                "scenario_id": "historical",
                "window_start": datetime(2023, 1, 1, tzinfo=UTC),
                "state": "TX",
                "marker": "eligible",
            },
        ],
        index=[5, 5],
    )

    train, calibration, holdouts = split(frame)

    assert holdouts["uri_2021"].marker.tolist() == ["holdout"]
    assert "holdout" not in set(train.marker) | set(calibration.marker)

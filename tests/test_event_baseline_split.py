from __future__ import annotations

import copy
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "event_baseline_split", ROOT / "scripts/data/event_baseline_split.py"
)
assert SPEC and SPEC.loader
splitter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(splitter)


def row(
    event_id: str, parent: str, source_key: str, *, start: str = "2021-01-01T00:00:00Z"
) -> dict:
    return {
        "event": {
            "event_id": event_id,
            "parent_system_id": parent,
            "primary_hazard": "wind",
            "context_window": {"start_utc": start, "end_utc": "2021-01-03T00:00:00Z"},
        },
        "record": {
            "record_id": f"{event_id}-record",
            "county_fips": "27053",
            "scenario_id": event_id,
            "window_start_utc": start,
            "window_end_utc": "2021-01-01T06:00:00Z",
            "mode": "replay",
            "label": {
                "status": "unavailable",
                "customer_denominator": {"status": "unavailable", "value": None},
            },
            "source_row_keys": [source_key],
        },
    }


def test_parent_system_stays_together() -> None:
    rows = [
        row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z"),
        row("wind-b", "storm-a", "eaglei:27053:2021-01-01T06:00:00Z"),
    ]
    manifest = splitter.manifest_rows(rows)
    assert {item["split"] for item in manifest}.__len__() == 1
    splitter.audit(manifest)


def test_shared_selected_source_row_stays_together_without_using_raw_hash() -> None:
    rows = [
        row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z"),
        row(
            "wind-b",
            "storm-b",
            "eaglei:27053:2021-01-01T00:00:00Z",
            start="2021-02-01T00:00:00Z",
        ),
    ]
    manifest = splitter.manifest_rows(rows)
    assert {item["group_key"] for item in manifest} == {"storm-a|storm-b"}


def test_missing_source_row_identity_is_not_silently_proven() -> None:
    candidate = row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")
    candidate["record"].pop("source_row_keys")
    with pytest.raises(splitter.AuditError, match="source_row_keys"):
        splitter.manifest_rows([candidate])


def test_acceptance_rejects_partial_observed_coverage() -> None:
    candidate = row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")
    candidate["event"]["disposition"] = "accepted"
    candidate["record"].update(
        {
            "disposition": "accepted",
            "weather": {
                "coverage": "covered",
                "evidence_kind": "time_series_or_grid",
                "expected_samples": 24,
                "observed_samples": 24,
                "missing_timestamps": [],
            },
            "outage": {
                "coverage": "covered",
                "evidence_kind": "time_series_or_grid",
                "expected_samples": 24,
                "observed_samples": 23,
                "missing_timestamps": ["2021-01-01T23:00:00Z"],
            },
            "matched_coverage_decision": "matched",
            "source_evidence_status": "available",
        }
    )
    with pytest.raises(splitter.AuditError, match="complete expected/observed"):
        splitter.accepts(
            {"event": candidate["event"], "records": [candidate["record"]]}
        )


def test_accepted_complete_coverage_keeps_unavailable_denominator_label() -> None:
    candidate = row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")
    candidate["event"]["disposition"] = "accepted"
    candidate["record"].update(
        {
            "disposition": "accepted",
            "weather": {
                "coverage": "covered",
                "evidence_kind": "time_series_or_grid",
                "expected_samples": 24,
                "observed_samples": 24,
                "missing_timestamps": [],
            },
            "outage": {
                "coverage": "covered",
                "evidence_kind": "time_series_or_grid",
                "expected_samples": 24,
                "observed_samples": 24,
                "missing_timestamps": [],
            },
            "matched_coverage_decision": "matched",
            "source_evidence_status": "available",
        }
    )
    accepted = splitter.accepts(
        {"event": candidate["event"], "records": [candidate["record"]]}
    )
    assert accepted[0]["record"]["label"]["status"] == "unavailable"


def test_accepted_authoritative_weather_report_does_not_invent_sample_counts() -> None:
    candidate = row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")
    candidate["event"]["disposition"] = "accepted"
    candidate["record"].update(
        {
            "disposition": "accepted",
            "weather": {
                "coverage": "covered",
                "evidence_kind": "authoritative_event_report",
                "expected_samples": None,
                "observed_samples": None,
                "missing_timestamps": [],
                "event_report": {"scope_identifier": "MN-zone"},
            },
            "outage": {
                "coverage": "covered",
                "evidence_kind": "time_series_or_grid",
                "expected_samples": 24,
                "observed_samples": 24,
                "missing_timestamps": [],
            },
            "matched_coverage_decision": "matched",
            "source_evidence_status": "available",
        }
    )
    assert splitter.accepts(
        {"event": candidate["event"], "records": [candidate["record"]]}
    )


def test_accepted_covered_record_rejects_uncovered_label() -> None:
    candidate = row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")
    candidate["event"]["disposition"] = "accepted"
    candidate["record"].update(
        {
            "disposition": "accepted",
            "weather": {
                "coverage": "covered",
                "evidence_kind": "time_series_or_grid",
                "expected_samples": 1,
                "observed_samples": 1,
                "missing_timestamps": [],
            },
            "outage": {
                "coverage": "covered",
                "evidence_kind": "time_series_or_grid",
                "expected_samples": 1,
                "observed_samples": 1,
                "missing_timestamps": [],
            },
            "matched_coverage_decision": "matched",
            "source_evidence_status": "available",
            "label": {
                "status": "UncoveredLabel",
                "customer_denominator": {"status": "unavailable", "value": None},
            },
        }
    )
    with pytest.raises(splitter.AuditError, match="has UncoveredLabel"):
        splitter.accepts(
            {"event": candidate["event"], "records": [candidate["record"]]}
        )


def test_empty_accepted_set_cannot_freeze_split_manifests() -> None:
    with pytest.raises(splitter.AuditError, match="no accepted county-window"):
        splitter.require_accepted_rows([])


def test_an_empty_accepted_set_is_reported_not_passed() -> None:
    """`main()` reports rather than aborts, so the refusal must survive audit()."""
    report = splitter.audit([])

    assert report["status"] == "insufficient_corpus"
    assert report["rows"] == 0
    reasons = " ".join(report["insufficient_corpus_reasons"])
    assert "0 < the declared minimum" in reasons
    assert "the train split is empty" in reasons


def test_control_plan_records_unweighted_limited_frame(tmp_path: Path) -> None:
    plan = tmp_path / "preselection-plan.yaml"
    plan.write_text("plan_id: controls-v1\nweights:\n  status: explicitly_unweighted\n")
    control = row("controls", "controls-frame", "control-source-row")
    control["event"]["primary_hazard"] = "ordinary_weather"
    summary = splitter.control_summary(
        [{"event": control["event"], "records": [control["record"]]}], plan
    )
    assert summary["plan_id"] == "controls-v1"
    assert summary["weighting"] == "explicitly_unweighted"
    assert summary["candidate_county_fips"] == ["27053"]


def test_audit_rejects_forced_cross_split_source_row() -> None:
    manifest = splitter.manifest_rows(
        [row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")]
    )
    duplicate = copy.deepcopy(manifest[0])
    duplicate["split"] = "test" if duplicate["split"] != "test" else "train"
    duplicate["record_id"] = "another-record"
    with pytest.raises(splitter.AuditError, match="selected source row"):
        splitter.audit([manifest[0], duplicate])


# --- the audit's teeth -------------------------------------------------------
#
# Every check in `audit()` above is a collision detector, so on a corpus of
# singleton groups none of them can fire.  These exercise the two grouping
# unions the docs advertise by name, the positive re-derivation that catches a
# moved row, and the degeneracy refusal that stops a vacuous "pass".


def _accepted_record(candidate: dict) -> dict:
    """A record that the acceptance guards let through, for guard-level tests."""
    candidate["event"]["disposition"] = "accepted"
    candidate["record"].update(
        {
            "disposition": "accepted",
            "weather": {
                "coverage": "covered",
                "evidence_kind": "time_series_or_grid",
                "expected_samples": 24,
                "observed_samples": 24,
                "missing_timestamps": [],
            },
            "outage": {
                "coverage": "covered",
                "evidence_kind": "time_series_or_grid",
                "expected_samples": 24,
                "observed_samples": 24,
                "missing_timestamps": [],
            },
            "matched_coverage_decision": "matched",
            "source_evidence_status": "available",
        }
    )
    return candidate


def test_rows_sharing_a_parent_system_land_in_one_split() -> None:
    """Guards the `by_parent` union in `components()` directly.

    The windows are disjoint and the source rows differ, so `parent_system_id`
    is the only thing that can hold these two rows together.
    """
    left = row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")
    right = row(
        "wind-b",
        "storm-a",
        "eaglei:27053:2024-06-01T00:00:00Z",
        start="2024-06-01T00:00:00Z",
    )
    right["event"]["context_window"] = {
        "start_utc": "2024-06-01T00:00:00Z",
        "end_utc": "2024-06-03T00:00:00Z",
    }
    right["record"]["window_end_utc"] = "2024-06-01T06:00:00Z"

    # `components()`, not the manifest: two rows under one parent hash to the
    # same group key even when nothing groups them, so only the component count
    # can tell "one group" from "two identical-keyed groups".
    assert len(splitter.components([left, right])) == 1

    manifest = splitter.manifest_rows([left, right])

    assert {item["split"] for item in manifest} == {splitter.split_for("storm-a")}
    assert {item["group_key"] for item in manifest} == {"storm-a"}
    assert len(manifest) == 2


def test_rows_with_overlapping_context_windows_land_in_one_split() -> None:
    """Guards the context-window overlap union in `components()` directly.

    Different parents, different source rows: only the overlapping context
    windows can group these.
    """
    left = row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")
    right = row("wind-b", "storm-b", "eaglei:27053:2021-01-02T12:00:00Z")
    right["event"]["context_window"] = {
        "start_utc": "2021-01-02T00:00:00Z",
        "end_utc": "2021-01-05T00:00:00Z",
    }
    right["record"]["window_start_utc"] = "2021-01-02T12:00:00Z"
    right["record"]["window_end_utc"] = "2021-01-02T18:00:00Z"

    assert len(splitter.components([left, right])) == 1

    manifest = splitter.manifest_rows([left, right])

    assert {item["group_key"] for item in manifest} == {"storm-a|storm-b"}
    assert len({item["split"] for item in manifest}) == 1


def test_acceptance_refuses_a_record_without_source_row_evidence() -> None:
    """`accepts()` must make this refusal itself, not lean on the validator.

    `accepts()` is called on already-validated bundles, so this drives the guard
    with a bundle dict directly; deleting the guard makes this test green.
    """
    candidate = _accepted_record(
        row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")
    )
    candidate["record"]["source_evidence_status"] = "unavailable"

    with pytest.raises(splitter.AuditError, match="lacks source-row evidence"):
        splitter.accepts(
            {"event": candidate["event"], "records": [candidate["record"]]}
        )


def test_moving_a_single_row_between_splits_fails_the_audit() -> None:
    """The singleton case the shipped manifests were in: no collision, still caught."""
    manifest = splitter.manifest_rows(
        [row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")]
    )
    moved = copy.deepcopy(manifest)
    moved[0]["split"] = "test" if moved[0]["split"] != "test" else "train"

    with pytest.raises(
        splitter.AuditError, match="is not the .* its group key hashes to"
    ):
        splitter.audit(moved)


def test_moving_a_whole_group_between_splits_fails_the_audit() -> None:
    rows = [
        row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z"),
        row("wind-b", "storm-a", "eaglei:27053:2021-01-01T06:00:00Z"),
    ]
    manifest = splitter.manifest_rows(rows)
    assert len({item["group_key"] for item in manifest}) == 1
    moved = copy.deepcopy(manifest)
    other = "test" if moved[0]["split"] != "test" else "train"
    for item in moved:
        item["split"] = other

    with pytest.raises(
        splitter.AuditError, match="is not the .* its group key hashes to"
    ):
        splitter.audit(moved)


def test_a_degenerate_corpus_is_never_reported_as_a_passing_audit() -> None:
    manifest = splitter.manifest_rows(
        [row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")]
    )

    report = splitter.audit(manifest)

    assert report["status"] == "insufficient_corpus"
    reasons = " ".join(report["insufficient_corpus_reasons"])
    assert "declared minimum" in reasons
    assert "singleton" in reasons
    assert "split is empty" in reasons


def test_a_corpus_with_real_groups_and_enough_rows_passes() -> None:
    """The other side of the refusal: a non-degenerate corpus still reports pass.

    Without this the `insufficient_corpus` branch could be satisfied by never
    passing at all.
    """
    base = datetime(2021, 1, 1, tzinfo=UTC)
    rows = []
    for index in range(60):
        parent = f"storm-{index // 2}"
        day = base + timedelta(days=index * 3)
        stamp = day.strftime("%Y-%m-%dT%H:%M:%SZ")
        candidate = row(f"wind-{index}", parent, f"eaglei:27053:{index}", start=stamp)
        candidate["event"]["context_window"] = {
            "start_utc": stamp,
            "end_utc": (day + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        candidate["record"]["window_end_utc"] = (day + timedelta(hours=6)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        rows.append(candidate)
    manifest = splitter.manifest_rows(rows)

    report = splitter.audit(manifest)

    assert report["insufficient_corpus_reasons"] == []
    assert report["status"] == "pass"
    assert max(report["group_size_histogram"]) > 1


def test_load_bundles_finds_a_deeply_nested_bundle(tmp_path: Path) -> None:
    """`glob("*/*.json")` used to make a bundle one level deeper invisible."""
    nested = tmp_path / "hazard" / "sub"
    nested.mkdir(parents=True)
    (nested / "bogus.json").write_text('{"event": {}}')

    with pytest.raises(splitter.AuditError, match="contract validation failed"):
        splitter.load_bundles(tmp_path)


def test_acceptance_refuses_a_window_off_the_six_hour_grid() -> None:
    """A 15Z or 09Z start is not a contract window; the assembler says so itself."""
    candidate = _accepted_record(
        row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")
    )
    candidate["record"]["window_start_utc"] = "2021-01-01T15:00:00Z"
    candidate["record"]["window_end_utc"] = "2021-01-01T21:00:00Z"

    with pytest.raises(splitter.AuditError, match="off the 00/06/12/18Z grid"):
        splitter.accepts(
            {"event": candidate["event"], "records": [candidate["record"]]}
        )


def test_acceptance_refuses_a_window_that_is_not_six_hours() -> None:
    candidate = _accepted_record(
        row("wind-a", "storm-a", "eaglei:27053:2021-01-01T00:00:00Z")
    )
    candidate["record"]["window_start_utc"] = "2021-01-01T00:00:00Z"
    candidate["record"]["window_end_utc"] = "2021-01-01T09:00:00Z"

    with pytest.raises(splitter.AuditError, match="not a six-hour grid window"):
        splitter.accepts(
            {"event": candidate["event"], "records": [candidate["record"]]}
        )

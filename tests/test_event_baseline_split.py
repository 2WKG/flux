from __future__ import annotations

import copy
import importlib.util
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

"""Freeze grouped historical-event split manifests and audit their evidence.

This script intentionally consumes validated 461 bundles.  It does not use a
raw-file hash or a source document as a leakage key: annual EAGLE-I extracts
and event reports may legitimately support many independent episodes.  A
cross-split source collision is only a duplicate selected source row key.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditError(ValueError):
    """Raised when a held-out split cannot be defended from the artifacts."""


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def season(value: str) -> str:
    month = utc(value).month
    return (
        "winter"
        if month in (12, 1, 2)
        else "spring"
        if month in (3, 4, 5)
        else "summer"
        if month in (6, 7, 8)
        else "fall"
    )


def state_region(fips: str) -> str:
    # Census regions, keyed only by state FIPS; unlisted areas remain explicit.
    northeast = {"09", "23", "25", "33", "44", "50", "34", "36", "42"}
    midwest = {"17", "18", "26", "39", "55", "19", "20", "27", "29", "31", "38", "46"}
    south = {
        "10",
        "11",
        "12",
        "13",
        "24",
        "37",
        "45",
        "51",
        "54",
        "01",
        "21",
        "28",
        "47",
        "05",
        "22",
        "40",
        "48",
    }
    west = {
        "04",
        "08",
        "16",
        "30",
        "32",
        "35",
        "49",
        "56",
        "02",
        "06",
        "15",
        "41",
        "53",
    }
    prefix = fips[:2]
    if prefix in northeast:
        return "Northeast"
    if prefix in midwest:
        return "Midwest"
    if prefix in south:
        return "South"
    if prefix in west:
        return "West"
    return "unavailable"


def accepts(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Return accepted county windows, retaining unavailable labels unchanged."""
    event = bundle["event"]
    if event["disposition"] != "accepted":
        return []
    output: list[dict[str, Any]] = []
    for record in bundle["records"]:
        if record["disposition"] != "accepted":
            continue
        if record["outage"]["coverage"] == "UncoveredLabel":
            raise AuditError(
                f"{event['event_id']}/{record['record_id']}: accepted UncoveredLabel"
            )
        if (
            record["weather"]["coverage"] != "covered"
            or record["outage"]["coverage"] != "covered"
        ):
            raise AuditError(
                f"{event['event_id']}/{record['record_id']}: accepted record lacks matched coverage"
            )
        if record["matched_coverage_decision"] != "matched":
            raise AuditError(
                f"{event['event_id']}/{record['record_id']}: accepted record lacks matched decision"
            )
        if record.get("source_evidence_status") != "available":
            raise AuditError(
                f"{event['event_id']}/{record['record_id']}: accepted record lacks source-row evidence"
            )
        label = record["label"]
        if label["status"] == "UncoveredLabel":
            raise AuditError(
                f"{event['event_id']}/{record['record_id']}: covered accepted record has UncoveredLabel"
            )
        if (
            label["customer_denominator"]["status"] == "available"
            and label["status"] != "computed"
        ):
            raise AuditError(
                f"{event['event_id']}/{record['record_id']}: available denominator must use the versioned five-percent label"
            )
        if record["outage"].get("evidence_kind") != "time_series_or_grid":
            raise AuditError(
                f"{event['event_id']}/{record['record_id']}: accepted outage requires sampled or grid evidence"
            )
        for evidence_name in ("weather", "outage"):
            evidence = record[evidence_name]
            expected, observed, missing = (
                evidence.get("expected_samples"),
                evidence.get("observed_samples"),
                evidence.get("missing_timestamps"),
            )
            if evidence.get("evidence_kind") == "authoritative_event_report":
                report = evidence.get("event_report")
                if (
                    expected is not None
                    or observed is not None
                    or missing
                    or not isinstance(report, dict)
                ):
                    raise AuditError(
                        f"{event['event_id']}/{record['record_id']}: event report must retain scope and avoid fabricated sample counts"
                    )
                continue
            if (
                not isinstance(expected, int)
                or expected <= 0
                or observed != expected
                or missing
            ):
                raise AuditError(
                    f"{event['event_id']}/{record['record_id']}: {evidence_name} coverage "
                    "does not prove complete expected/observed samples"
                )
        output.append({"event": event, "record": record})
    return output


def record_source_keys(row: dict[str, Any]) -> set[str]:
    """Selected source rows, not reusable files or source documents, form leak keys."""
    keys = row["record"].get("source_row_keys")
    if (
        not isinstance(keys, list)
        or not keys
        or not all(isinstance(key, str) and key for key in keys)
    ):
        event, record = row["event"], row["record"]
        raise AuditError(
            f"{event['event_id']}/{record['record_id']}: missing selected source_row_keys; "
            "raw artifact hashes and document receipts are insufficient to audit row leakage"
        )
    return set(keys)


def components(rows: list[dict[str, Any]]) -> list[list[int]]:
    """Connect rows by parent, source-row reuse, or overlapping/adjacent context windows."""
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(left: int, right: int) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    by_parent: dict[str, int] = {}
    by_source_row: dict[str, int] = {}
    event_windows: list[tuple[datetime, datetime]] = []
    for index, row in enumerate(rows):
        event = row["event"]
        group = event["parent_system_id"]
        if group in by_parent:
            union(index, by_parent[group])
        else:
            by_parent[group] = index
        for source_key in record_source_keys(row):
            if source_key in by_source_row:
                union(index, by_source_row[source_key])
            else:
                by_source_row[source_key] = index
        # Context windows include exposure/recovery. Equality is adjacency and
        # remains in one group to avoid boundary leakage.
        event_windows.append(
            (
                utc(event["context_window"]["start_utc"]),
                utc(event["context_window"]["end_utc"]),
            )
        )
    for left, (start, end) in enumerate(event_windows):
        for right in range(left):
            other_start, other_end = event_windows[right]
            if start <= other_end and other_start <= end:
                union(left, right)
    grouped: dict[int, list[int]] = defaultdict(list)
    for index in range(len(rows)):
        grouped[find(index)].append(index)
    return list(grouped.values())


def split_for(group_key: str) -> str:
    bucket = int(hashlib.sha256(group_key.encode()).hexdigest()[:8], 16) % 100
    return "train" if bucket < 70 else "calibration" if bucket < 85 else "test"


def manifest_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for component in components(rows):
        identifiers = sorted(
            {rows[index]["event"]["parent_system_id"] for index in component}
        )
        group_key = "|".join(identifiers)
        assigned = split_for(group_key)
        for index in component:
            event, record = rows[index]["event"], rows[index]["record"]
            result.append(
                {
                    "split": assigned,
                    "group_key": group_key,
                    "event_id": event["event_id"],
                    "parent_system_id": event["parent_system_id"],
                    "record_id": record["record_id"],
                    "county_fips": record["county_fips"],
                    "scenario_id": record["scenario_id"],
                    "window_start_utc": record["window_start_utc"],
                    "window_end_utc": record["window_end_utc"],
                    "primary_hazard": event["primary_hazard"],
                    "region": state_region(record["county_fips"]),
                    "season": season(record["window_start_utc"]),
                    "mode": record["mode"],
                    "label_status": record["label"]["status"],
                    "control_weight": str(record.get("control_weight", "unavailable")),
                    "source_row_keys": json.dumps(
                        sorted(record_source_keys(rows[index])), separators=(",", ":")
                    ),
                }
            )
    return sorted(
        result, key=lambda row: (row["split"], row["group_key"], row["record_id"])
    )


def require_accepted_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise AuditError(
            "no accepted county-window records; no split manifests can be frozen"
        )


# A split frozen from a handful of rows, or from rows that share no grouping
# key at all, cannot demonstrate that the grouping works: every leakage check
# below is a collision detector, and a degenerate corpus has no collisions to
# detect.  Declare the floor here so the audit refuses instead of reporting a
# vacuous "pass".
MINIMUM_ACCEPTED_ROWS = 12
MINIMUM_NON_SINGLETON_GROUPS = 1


def degeneracy_reasons(manifest: list[dict[str, str]]) -> list[str]:
    """Why this corpus cannot support an auditable held-out split, if it cannot."""
    reasons: list[str] = []
    if len(manifest) < MINIMUM_ACCEPTED_ROWS:
        reasons.append(
            f"accepted county-window rows {len(manifest)} < the declared minimum "
            f"{MINIMUM_ACCEPTED_ROWS}"
        )
    group_sizes = Counter(row["group_key"] for row in manifest)
    non_singleton = sum(1 for size in group_sizes.values() if size > 1)
    if non_singleton < MINIMUM_NON_SINGLETON_GROUPS:
        reasons.append(
            f"every one of the {len(group_sizes)} groups is a singleton, so no "
            "leakage check in this audit can fire"
        )
    for split in ("train", "calibration", "test"):
        if not any(row["split"] == split for row in manifest):
            reasons.append(f"the {split} split is empty")
    return reasons


def regrouping_failures(manifest: list[dict[str, str]]) -> list[str]:
    """Positively re-derive each row's split from its group key.

    The collision checks below can only see rows that collide.  This one fails
    on any single row whose recorded split is not the split its own group key
    hashes to, so moving one row between manifests is caught even when every
    group is a singleton.
    """
    failures: list[str] = []
    for row in manifest:
        expected = split_for(row["group_key"])
        if row["split"] != expected:
            failures.append(
                f"{row['record_id']}: recorded split {row['split']} is not the "
                f"{expected} its group key hashes to"
            )
        if row["parent_system_id"] not in row["group_key"].split("|"):
            failures.append(
                f"{row['record_id']}: parent_system_id {row['parent_system_id']} "
                f"is not part of its group key {row['group_key']}"
            )
    return failures


def audit(manifest: list[dict[str, str]]) -> dict[str, Any]:
    canonical: dict[tuple[str, str, str], str] = {}
    parents: dict[str, str] = {}
    source_rows: dict[str, str] = {}
    failures: list[str] = []
    coverage: dict[str, Counter[str]] = {
        "hazard": Counter(),
        "region": Counter(),
        "season": Counter(),
        "mode": Counter(),
        "label_status": Counter(),
        "control_weight": Counter(),
    }
    for row in manifest:
        split = row["split"]
        for dimension, field in (
            ("hazard", "primary_hazard"),
            ("region", "region"),
            ("season", "season"),
            ("mode", "mode"),
            ("label_status", "label_status"),
            ("control_weight", "control_weight"),
        ):
            coverage[dimension][row[field]] += 1
        key = (row["county_fips"], row["scenario_id"], row["window_start_utc"])
        prior = canonical.setdefault(key, split)
        if prior != split:
            failures.append(f"canonical county-window crosses splits: {key}")
        for group, label in ((row["parent_system_id"], "parent_system_id"),):
            prior = parents.setdefault(group, split)
            if prior != split:
                failures.append(f"{label} crosses splits: {group}")
        for source_key in json.loads(row["source_row_keys"]):
            prior = source_rows.setdefault(source_key, split)
            if prior != split:
                failures.append(f"selected source row crosses splits: {source_key}")
    failures.extend(regrouping_failures(manifest))
    if failures:
        raise AuditError("; ".join(sorted(set(failures))))
    reasons = degeneracy_reasons(manifest)
    return {
        "status": "insufficient_corpus" if reasons else "pass",
        "insufficient_corpus_reasons": reasons,
        "declared_minimums": {
            "accepted_rows": MINIMUM_ACCEPTED_ROWS,
            "non_singleton_groups": MINIMUM_NON_SINGLETON_GROUPS,
            "non_empty_splits": ["train", "calibration", "test"],
        },
        "group_size_histogram": dict(
            sorted(
                Counter(Counter(row["group_key"] for row in manifest).values()).items()
            )
        ),
        "rows": len(manifest),
        "splits": dict(Counter(row["split"] for row in manifest)),
        "coverage": {
            key: dict(sorted(value.items())) for key, value in coverage.items()
        },
    }


def control_summary(
    bundles: list[dict[str, Any]], plan_path: Path | None
) -> dict[str, Any]:
    """Record the declared control plan; do not manufacture row-level weights."""
    controls = [
        bundle
        for bundle in bundles
        if bundle["event"]["primary_hazard"] == "ordinary_weather"
    ]
    if not controls:
        return {"status": "unavailable", "reason": "no ordinary-weather control bundle"}
    if plan_path is None or not plan_path.is_file():
        return {
            "status": "unavailable",
            "reason": "control preselection plan not found",
        }
    content = plan_path.read_bytes()
    text = content.decode("utf-8")
    plan_id = re.search(r"(?m)^plan_id:\s*(\S+)\s*$", text)
    weights = re.search(r"(?ms)^weights:\s*\n\s*status:\s*(\S+)", text)
    fips = sorted(
        {record["county_fips"] for bundle in controls for record in bundle["records"]}
    )
    return {
        "status": "declared",
        "plan_id": plan_id.group(1) if plan_id else "unavailable",
        "plan_sha256": hashlib.sha256(content).hexdigest(),
        "weighting": weights.group(1) if weights else "unavailable",
        "candidate_county_fips": fips,
        "frame_limit": "candidate control frame only; no regional representativeness claim",
    }


def load_bundles(events_dir: Path) -> list[dict[str, Any]]:
    validator_path = Path(__file__).with_name("event_baseline_validate.py")
    spec = importlib.util.spec_from_file_location(
        "event_baseline_validate", validator_path
    )
    if spec is None or spec.loader is None:
        raise AuditError(f"cannot load contract validator at {validator_path}")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    bundles: list[dict[str, Any]] = []
    inputs: list[dict[str, str]] = []
    # rglob, not glob("*/*.json"): a bundle nested one level deeper must not be
    # silently invisible to the assembler.
    for path in sorted(events_dir.rglob("*.json")):
        try:
            bundles.append(validator.load_and_validate(path))
        except Exception as exc:  # the validator's own error type is private
            raise AuditError(f"{path}: contract validation failed: {exc}") from exc
        inputs.append(
            {
                "path": path.as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    if not bundles:
        raise AuditError(f"{events_dir}: no event bundles")
    return bundles, inputs


def head_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def generation_receipt(
    events_dir: Path, inputs: list[dict[str, str]]
) -> dict[str, Any]:
    """Trace the manifests back to the generator and the exact input bundles."""
    generator = Path(__file__)
    return {
        "capture_method": "generated",
        "generator_path": "scripts/data/event_baseline_split.py",
        "generator_sha256": hashlib.sha256(generator.read_bytes()).hexdigest(),
        "generator_commit": head_commit(),
        "input_events_dir": events_dir.as_posix(),
        "input_bundle_count": len(inputs),
        "input_bundles": inputs,
    }


FIELDS = [
    "split",
    "group_key",
    "event_id",
    "parent_system_id",
    "record_id",
    "county_fips",
    "scenario_id",
    "window_start_utc",
    "window_end_utc",
    "primary_hazard",
    "region",
    "season",
    "mode",
    "label_status",
    "control_weight",
    "source_row_keys",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--controls-plan", type=Path)
    args = parser.parse_args(argv)
    try:
        bundles, inputs = load_bundles(args.events_dir)
        rows = [row for bundle in bundles for row in accepts(bundle)]
        require_accepted_rows(rows)
        manifest = manifest_rows(rows)
        report = audit(manifest)
        report["receipt"] = generation_receipt(args.events_dir, inputs)
        report["controls"] = control_summary(
            bundles,
            args.controls_plan
            or args.events_dir / "controls" / "preselection-plan.yaml",
        )
    except AuditError as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for split in ("train", "calibration", "test"):
        path = args.output_dir / f"{split}.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(row for row in manifest if row["split"] == split)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    (args.output_dir / "audit.json").write_text(payload)
    (args.output_dir / "audit.sha256").write_text(
        hashlib.sha256(payload.encode()).hexdigest() + "  audit.json\n"
    )
    print(f"WROTE {args.output_dir} ({report['rows']} accepted county-window rows)")
    if report["status"] != "pass":
        # Written, but refused: the manifests exist so the state is inspectable,
        # and the exit status says they are not a defensible held-out split.
        for reason in report["insufficient_corpus_reasons"]:
            print(f"REFUSED insufficient_corpus: {reason}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

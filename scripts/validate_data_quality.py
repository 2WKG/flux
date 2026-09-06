#!/usr/bin/env python3
"""Validate a curated DuckDB artifact and write a JSON monitoring report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipelines.data_quality import run_quality_gate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument(
        "--operations", type=Path, default=Path("datasets/operations.json")
    )
    parser.add_argument("--ingest-log", type=Path)
    parser.add_argument("--previous-counts", type=Path)
    parser.add_argument(
        "--api-health-url",
        help="Optional deployed/local endpoint to probe; omitted is reported unavailable.",
    )
    parser.add_argument("--report", type=Path, default=Path("data/quality-report.json"))
    args = parser.parse_args()
    report = run_quality_gate(
        args.database,
        args.operations,
        ingest_log_path=args.ingest_log,
        previous_counts_path=args.previous_counts,
        api_health_url=args.api_health_url,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["dashboard_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

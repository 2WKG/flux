#!/usr/bin/env python3
"""Run the reproducible EDA workflow and write its JSON report and summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipelines.eda import (
    EDA_PROFILES,
    MIN_CORRELATION_ROWS,
    ROBUST_Z_THRESHOLD,
    render_summary,
    run_eda,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--view", action="append", choices=sorted(EDA_PROFILES), help="Restrict the run to one or more canonical metric views; repeatable.")
    parser.add_argument("--scenario", help="Restrict every view to one scenario_id.")
    parser.add_argument("--robust-z-threshold", type=float, default=ROBUST_Z_THRESHOLD)
    parser.add_argument("--min-correlation-rows", type=int, default=MIN_CORRELATION_ROWS)
    parser.add_argument("--no-install-views", action="store_true", help="Open the artifact read-only and require the metric views to already exist.")
    parser.add_argument("--report", type=Path, default=Path("data/eda-report.json"))
    parser.add_argument("--summary", type=Path, default=Path("data/eda-summary.md"))
    args = parser.parse_args()

    report = run_eda(
        args.database,
        views=args.view,
        scenario_id=args.scenario,
        robust_z_threshold=args.robust_z_threshold,
        min_correlation_rows=args.min_correlation_rows,
        install_views=not args.no_install_views,
    )
    summary = render_summary(report)
    for path, text in ((args.report, json.dumps(report, indent=2) + "\n"), (args.summary, summary)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

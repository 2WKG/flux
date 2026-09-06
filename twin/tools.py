"""Thin JSON-safe entry points for future copilot registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from twin.cascade import run_cascade


def run_cascade_tool(
    element_ids: list[str], scenario_id: str, hour: int, *, case_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run a synthetic cascade without inventing a result when inputs are absent."""
    return run_cascade(element_ids, scenario_id, hour, case_path=case_path, db_path=db_path, write=False)

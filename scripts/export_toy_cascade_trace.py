"""Freeze the explainer's server-solved teaching cascade into a data artifact.

    uv run --extra dev python scripts/export_toy_cascade_trace.py

`twin/tests/test_toy_cascade.py` reruns the solve and fails if the committed
artifact differs, so the trace the explainer page replays cannot drift away from
the server that produced it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# pyproject sets package=false, so mirror pytest's pythonpath=["."] here.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from twin.toy_cascade import toy_cascade_trace

ARTIFACT = REPO_ROOT / "data/explainer/toy-cascade-trace.json"


def write_artifact(path: Path = ARTIFACT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(toy_cascade_trace(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    print(write_artifact())

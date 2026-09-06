"""Read-only access to the explainer's persisted teaching cascade trace.

The trace is solved on the server by :mod:`twin.toy_cascade` and frozen into
``data/explainer/toy-cascade-trace.json`` by
``scripts/export_toy_cascade_trace.py``.  This route serves those exact bytes so
the explainer page replays a server result instead of computing one; the page
also ships the same artifact as its offline fallback, and
``twin/tests/test_toy_cascade.py`` fails if the two ever diverge from a fresh
solve.

No solving happens here.  A missing artifact is an explicit ``unavailable``,
never an empty success.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from copilot.api import UnavailableError

router = APIRouter(tags=["explainer"])

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACE_ARTIFACT = REPO_ROOT / "data/explainer/toy-cascade-trace.json"


def _artifact_path(request: Request) -> Path:
    """The artifact this request reads, overridable for tests via app state."""
    override = getattr(request.app.state, "explainer_trace_path", None)
    return Path(override) if override is not None else TRACE_ARTIFACT


@router.get("/explainer/toy-cascade")
async def toy_cascade_trace(request: Request) -> dict[str, Any]:
    """Return the persisted teaching cascade trace exactly as it was frozen."""
    path = _artifact_path(request)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise UnavailableError(
            "The explainer teaching cascade artifact has not been exported. "
            "Run scripts/export_toy_cascade_trace.py."
        ) from error
    try:
        return dict(json.loads(raw))
    except (ValueError, TypeError) as error:
        raise UnavailableError(
            "The explainer teaching cascade artifact is not a readable JSON object."
        ) from error

"""Public context uses the canonical shared database."""

from __future__ import annotations

from pathlib import Path

from pipelines.db import connect
from pipelines.state_scope import StateScope, scope


def context_db_path(states=None, db_root: str | Path = "data/duck") -> Path:
    scope(states) if not isinstance(states, StateScope) else states
    return Path(db_root) / "grid.duckdb"


def connect_context(states=None, db_root: str | Path = "data/duck"):
    """Open the shared store for non-Texas context acquisition."""
    selected = states if isinstance(states, StateScope) else scope(states)
    if selected.is_texas_only:
        raise ValueError("Texas P0 uses pipelines.build; context stores are non-Texas only")
    return connect(context_db_path(selected, db_root))

"""Isolated public-context stores using the shared provenance-aware schema."""

from __future__ import annotations

from pathlib import Path

from pipelines.db import connect
from pipelines.state_scope import StateScope, scope


def context_db_path(states=None, db_root: str | Path = "data/duck") -> Path:
    selected = states if isinstance(states, StateScope) else scope(states)
    root = Path(db_root)
    return root / "grid.duckdb" if selected.is_texas_only else root / "context" / f"{selected.slug}.duckdb"


def connect_context(states=None, db_root: str | Path = "data/duck"):
    """Open a separate non-Texas shared-contract store with no topology rows."""
    selected = states if isinstance(states, StateScope) else scope(states)
    if selected.is_texas_only:
        raise ValueError("Texas P0 uses pipelines.build; context stores are non-Texas only")
    return connect(context_db_path(selected, db_root))

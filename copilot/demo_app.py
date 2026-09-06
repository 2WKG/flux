"""Runnable composition for the local Flux control-room demonstration.

The standard API remains provider-neutral and leaves ``/ask`` unavailable by
default.  This entry point explicitly composes its bounded offline demo backend.
"""

from __future__ import annotations

from pathlib import Path

from copilot.app import create_app
from copilot.config import load_settings
from copilot.demo.runtime import build_demo_ask_backend


_settings = load_settings()
_repository_root = Path(__file__).resolve().parent.parent
app = create_app(
    _settings,
    ask_backend=build_demo_ask_backend(
        duckdb_path=_settings.duckdb_path,
        jepa_artifact_path=(
            _repository_root
            / "data/artifacts/jepa/eaglei-2024-count-v1/jepa_count_forecast_artifact.json"
        ),
    ),
)

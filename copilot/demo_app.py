"""Runnable composition for the local Flux control-room demonstration.

The standard API remains provider-neutral and leaves ``/ask`` unavailable by
default.  This entry point explicitly composes its bounded offline demo backend.
"""

from __future__ import annotations

import os
from pathlib import Path

from copilot.app import create_app
from copilot.config import load_settings
from copilot.demo.composed import create_composed_ask_backend
from copilot.demo.data import create_demo_data_router
from copilot.demo.model import create_demo_model_router
from copilot.demo.runtime import build_demo_ask_backend
from copilot.interactive_routes import (
    create_interactive_router,
    create_interactive_service,
)

_settings = load_settings()
_repository_root = Path(__file__).resolve().parent.parent
_case_path = Path(
    os.environ.get("FLUX_CASE_PATH", "data/raw/activsg2000_current/case_ACTIVSg2000.m")
)
_interactive_service = create_interactive_service(
    duckdb_path=_settings.duckdb_path, case_path=_case_path
)
_demo_backend = build_demo_ask_backend(
    duckdb_path=_settings.duckdb_path,
    case_path=_case_path,
    jepa_artifact_path=(
        _repository_root
        / "data/artifacts/jepa/eaglei-2024-count-v1/jepa_count_forecast_artifact.json"
    ),
)
app = create_app(
    _settings,
    ask_backend=create_composed_ask_backend(
        demo=_demo_backend, interactive_service=_interactive_service
    ),
)
app.include_router(
    create_demo_data_router(
        duckdb_path=_settings.duckdb_path,
        jepa_artifact_path=(
            _repository_root
            / "data/artifacts/jepa/eaglei-2024-count-v1/jepa_count_forecast_artifact.json"
        ),
    )
)
app.include_router(
    create_demo_model_router(duckdb_path=_settings.duckdb_path, case_path=_case_path)
)
app.include_router(create_interactive_router(service=_interactive_service))

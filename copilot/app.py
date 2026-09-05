"""FastAPI application factory for Flux's read-only Copilot surface."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from copilot.api import API_VERSION, install_error_handlers
from copilot.config import Settings
from copilot.routes.health import router as health_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an app whose routes can be exercised against a fixture database."""
    app = FastAPI(title="Flux API", version=API_VERSION)
    app.state.settings = settings or Settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app.state.settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(health_router)
    return app


app = create_app()

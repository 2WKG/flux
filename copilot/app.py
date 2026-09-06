"""FastAPI application factory for Flux's read-only Copilot surface."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from copilot.api import (
    API_VERSION,
    NotFoundError,
    install_error_handlers,
    request_id_of,
)
from copilot.api.errors import failure_response
from copilot.config import Settings
from copilot.routes.health import router as health_router
from copilot.routes.interventions import router as interventions_router
from copilot.routes.layers import router as layers_router
from copilot.routes.scenarios import router as scenarios_router
from copilot.routes.predictions import router as predictions_router


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

    @app.exception_handler(StarletteHTTPException)
    async def route_miss(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = request_id_of(request)
        if exc.status_code == 404:
            return failure_response(
                NotFoundError("No route matches the request path."), request_id
            )
        return await http_exception_handler(request, exc)

    app.include_router(health_router)
    app.include_router(layers_router)
    app.include_router(interventions_router)
    app.include_router(scenarios_router)
    app.include_router(predictions_router)
    return app


app = create_app()

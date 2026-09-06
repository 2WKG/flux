"""FastAPI application factory for Flux's read-only Copilot surface."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from copilot.api import (
    API_VERSION,
    API_VERSION_HEADER,
    ARTIFACT_HEADER,
    REQUEST_ID_HEADER,
    NotFoundError,
    install_error_handlers,
    request_id_of,
)
from copilot.api.errors import failure_response
from copilot.config import Settings, load_settings
from copilot.dispatcher import (
    ToolCallingProvider,
    ToolDispatcher,
    interactive_tool_handlers,
)
from copilot.interactive_routes import (
    create_interactive_router,
    create_interactive_service,
)
from copilot.non_interactive_tool_handlers import (
    NonInteractiveToolServices,
    non_interactive_tool_handlers,
)
from copilot.providers import build_tool_provider
from copilot.routes.ask import AskBackend
from copilot.routes.ask import router as ask_router
from copilot.routes.comparisons import router as comparisons_router
from copilot.routes.health import router as health_router
from copilot.routes.interventions import router as interventions_router
from copilot.routes.layers import router as layers_router
from copilot.routes.lines import router as lines_router
from copilot.routes.minnesota_smr import router as minnesota_smr_router
from copilot.routes.mn_comparisons import router as mn_comparisons_router
from copilot.routes.physical_layers import router as physical_layers_router
from copilot.routes.predictions import router as predictions_router
from copilot.routes.scenarios import router as scenarios_router


def create_app(
    settings: Settings | None = None,
    *,
    ask_backend: AskBackend | None = None,
    tool_provider: ToolCallingProvider | None = None,
    tool_dispatcher: ToolDispatcher | None = None,
) -> FastAPI:
    """Build an app whose routes can be exercised against a fixture database."""
    app = FastAPI(title="Flux API", version=API_VERSION)
    app.state.settings = settings if settings is not None else load_settings()
    # Adapter construction is local-only; requests are the only point at which
    # a configured provider can be contacted. Missing credentials stay
    # explicitly unavailable.
    app.state.ask_backend = ask_backend
    # An injected legacy backend owns the attempt outright.  Do not construct a
    # configured SDK transport that the route will never select; the normal
    # dispatcher path constructs its configured transport once at app startup.
    app.state.tool_provider = (
        tool_provider
        if tool_provider is not None
        else (
            None
            if ask_backend is not None
            else build_tool_provider(app.state.settings)
        )
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app.state.settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=[
            REQUEST_ID_HEADER,
            API_VERSION_HEADER,
            ARTIFACT_HEADER,
            "X-Flux-Attempt-Id",
        ],
    )

    @app.exception_handler(StarletteHTTPException)
    async def route_miss(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = request_id_of(request)
        if exc.status_code == 404:
            return failure_response(
                NotFoundError("No route matches the request path."), request_id
            )
        return await http_exception_handler(request, exc)

    app.state.interactive_service = create_interactive_service(
        duckdb_path=app.state.settings.duckdb_path
    )
    app.state.tool_dispatcher = tool_dispatcher or ToolDispatcher(
        interactive_tool_handlers(
            app.state.interactive_service,
            historical_handlers=non_interactive_tool_handlers(
                NonInteractiveToolServices(database_path=app.state.settings.duckdb_path)
            ),
        )
    )

    app.include_router(health_router)
    app.include_router(layers_router)
    app.include_router(physical_layers_router)
    app.include_router(interventions_router)
    app.include_router(lines_router)
    app.include_router(comparisons_router)
    app.include_router(scenarios_router)
    app.include_router(predictions_router)
    app.include_router(ask_router)
    app.include_router(minnesota_smr_router)
    app.include_router(mn_comparisons_router)
    app.include_router(create_interactive_router(service=app.state.interactive_service))
    return app


app = create_app()

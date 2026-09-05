"""Typed API failures and their HTTP mapping.

Route code raises one of the four errors below; the handlers installed by
``install_error_handlers`` render them as a :class:`FailureEnvelope`. Nothing
here reads an exception's text into a response: an unexpected failure is logged
server-side and answered with a fixed message plus the request id.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, ClassVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from copilot.api.envelope import (
    ArtifactRef,
    Failure,
    FailureCode,
    FailureEnvelope,
    ResponseStatus,
    response_meta,
    safe_details,
)

logger = logging.getLogger("copilot.api")

REQUEST_ID_HEADER = "X-Request-ID"
INTERNAL_ERROR_MESSAGE = (
    "The service failed to complete this request. The failure is logged under "
    "the request id."
)


class ApiError(Exception):
    """Base class for the four failure classes the surface can return."""

    code: ClassVar[FailureCode]
    status: ClassVar[ResponseStatus]
    http_status: ClassVar[int]
    retryable: ClassVar[bool]
    retry_after_s: ClassVar[int | None] = None

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = safe_details(details)

    def envelope(
        self,
        request_id: str,
        *,
        artifacts: tuple[ArtifactRef, ...] = (),
        generated_at: datetime | None = None,
    ) -> FailureEnvelope:
        return FailureEnvelope(
            status=self.status,
            error=Failure(
                code=self.code,
                message=self.message,
                retryable=self.retryable,
                retry_after_s=self.retry_after_s,
                details=self.details,
            ),
            meta=response_meta(
                request_id, artifacts=artifacts, generated_at=generated_at
            ),
        )


class UnavailableError(ApiError):
    """A required artifact is absent, unbuilt, stale, or not yet computed."""

    code = "unavailable"
    status = "unavailable"
    http_status = 503
    retryable = True
    retry_after_s = 30


class InvalidInputError(ApiError):
    """Request parameters are malformed or outside the supported contract."""

    code = "invalid_input"
    status = "error"
    http_status = 422
    retryable = False


class NotFoundError(ApiError):
    """The named route target (scenario, layer, site, line) does not exist."""

    code = "not_found"
    status = "error"
    http_status = 404
    retryable = False


class InternalError(ApiError):
    """An unexpected server-side failure. Message is fixed and safe."""

    code = "internal_error"
    status = "error"
    http_status = 500
    retryable = False

    def __init__(
        self, message: str = INTERNAL_ERROR_MESSAGE, *, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, details=details)


def internal_error_from(exc: BaseException, *, request_id: str) -> InternalError:
    """Log the real exception and return a response-safe internal error.

    The exception's text — a raw DuckDB message, a file path, a connection
    string — stays in the server log and never reaches the client.
    """
    logger.exception("unhandled API failure request_id=%s", request_id, exc_info=exc)
    return InternalError(details={"request_id": request_id})


def request_id_of(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if not request_id:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id
    return str(request_id)[:64]


def failure_response(error: ApiError, request_id: str) -> JSONResponse:
    headers = {REQUEST_ID_HEADER: request_id}
    if error.retry_after_s is not None:
        headers["Retry-After"] = str(error.retry_after_s)
    return JSONResponse(
        status_code=error.http_status,
        content=error.envelope(request_id).model_dump(mode="json"),
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> FastAPI:
    """Route every failure on ``app`` through the versioned failure envelope."""

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return failure_response(exc, request_id_of(request))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        return failure_response(
            InvalidInputError(
                "Request parameters do not match the documented contract.",
                details={"field": field} if field else None,
            ),
            request_id_of(request),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        request_id = request_id_of(request)
        return failure_response(internal_error_from(exc, request_id=request_id), request_id)

    return app

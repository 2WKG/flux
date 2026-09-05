"""Versioned HTTP envelope and failure contracts shared by every read route."""

from copilot.api.envelope import (
    API_VERSION,
    Failure,
    FailureCode,
    FailureEnvelope,
    ResponseMeta,
    ResponseStatus,
)
from copilot.api.errors import (
    ApiError,
    InternalError,
    InvalidInputError,
    NotFoundError,
    UnavailableError,
    install_error_handlers,
    internal_error_from,
    request_id_of,
)

__all__ = [
    "API_VERSION",
    "ApiError",
    "Failure",
    "FailureCode",
    "FailureEnvelope",
    "InternalError",
    "InvalidInputError",
    "NotFoundError",
    "ResponseMeta",
    "ResponseStatus",
    "UnavailableError",
    "install_error_handlers",
    "internal_error_from",
    "request_id_of",
]

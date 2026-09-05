"""Versioned HTTP envelope and failure contracts shared by every read route."""

from copilot.api.envelope import (
    API_VERSION,
    ArtifactRef,
    Failure,
    FailureCode,
    FailureEnvelope,
    ResponseMeta,
    ResponseStatus,
    SuccessEnvelope,
    safe_details,
    success,
)
from copilot.api.errors import (
    ApiError,
    InternalError,
    InvalidInputError,
    NotFoundError,
    UnavailableError,
    install_error_handlers,
    internal_error_from,
)

__all__ = [
    "API_VERSION",
    "ApiError",
    "ArtifactRef",
    "Failure",
    "FailureCode",
    "FailureEnvelope",
    "InternalError",
    "InvalidInputError",
    "NotFoundError",
    "ResponseMeta",
    "ResponseStatus",
    "SuccessEnvelope",
    "UnavailableError",
    "install_error_handlers",
    "internal_error_from",
    "safe_details",
    "success",
]

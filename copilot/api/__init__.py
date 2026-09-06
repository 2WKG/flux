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
    API_VERSION_HEADER,
    ARTIFACT_HEADER,
    REQUEST_ID_HEADER,
    ApiError,
    InternalError,
    InvalidInputError,
    NotFoundError,
    UnavailableError,
    install_error_handlers,
    internal_error_from,
    request_id_of,
)
from copilot.api.pagination import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MAX_PAGE_OFFSET,
    DeterministicOrder,
    PageRequest,
    SortTerm,
)

__all__ = [
    "API_VERSION",
    "API_VERSION_HEADER",
    "ARTIFACT_HEADER",
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "MAX_PAGE_OFFSET",
    "REQUEST_ID_HEADER",
    "ApiError",
    "DeterministicOrder",
    "Failure",
    "FailureCode",
    "FailureEnvelope",
    "InternalError",
    "InvalidInputError",
    "NotFoundError",
    "PageRequest",
    "ResponseMeta",
    "ResponseStatus",
    "SortTerm",
    "UnavailableError",
    "install_error_handlers",
    "internal_error_from",
    "request_id_of",
]

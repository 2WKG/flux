"""Shared bounded pagination and total-order primitives for read routes.

Routes own their response payloads and database queries.  This module only
provides the common request bounds and a safe representation of a deterministic
``ORDER BY`` clause.  It deliberately does not add a success envelope or a
new data-status field: the existing unwrapped-success and failure-envelope
contract remains authoritative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from copilot.api.errors import InvalidInputError

DEFAULT_PAGE_LIMIT = 50
"""Rows returned when a route accepts pagination and no limit is supplied."""

MAX_PAGE_LIMIT = 100
"""Default page cap for a route that adopts this helper without its own bound.

This is a default, not a repo-wide ceiling. A route whose page size is already
pinned by the specs keeps that spec'd bound and passes it as
``PageRequest(max_limit=...)``; ``GET /predictions`` is the shipped example
(``MAX_PREDICTIONS = 1000``, ``docs/specs/00-overview.md`` §4.2). A route may
only lower or raise this default through ``max_limit``; it must never accept a
limit it has not declared.
"""

MAX_PAGE_OFFSET = 10_000
"""Largest public offset, limiting an individual scan to a bounded window."""

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SortDirection = Literal["ASC", "DESC"]


@dataclass(frozen=True)
class PageRequest:
    """A bounded SQL ``LIMIT``/``OFFSET`` request.

    An empty page is meaningful only after the route has established that its
    backing artifact is available.  Missing, invalid, or unavailable artifacts
    remain the existing API failure envelope; callers must not substitute an
    empty page for one of those conditions.
    """

    limit: int = DEFAULT_PAGE_LIMIT
    offset: int = 0
    max_limit: int = MAX_PAGE_LIMIT

    def __post_init__(self) -> None:
        if isinstance(self.max_limit, bool) or not isinstance(self.max_limit, int):
            raise TypeError("max_limit must be an integer")
        if self.max_limit < 1:
            raise ValueError("max_limit must be at least 1")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise TypeError("limit must be an integer")
        if not 1 <= self.limit <= self.max_limit:
            raise InvalidInputError(
                f"limit must be between 1 and {self.max_limit}",
                details={"field": "limit"},
            )
        if isinstance(self.offset, bool) or not isinstance(self.offset, int):
            raise TypeError("offset must be an integer")
        if not 0 <= self.offset <= MAX_PAGE_OFFSET:
            raise InvalidInputError(
                f"offset must be between 0 and {MAX_PAGE_OFFSET}",
                details={"field": "offset"},
            )

    @property
    def sql_parameters(self) -> tuple[int, int]:
        """Parameters to bind to a trailing ``LIMIT ? OFFSET ?`` clause."""

        return (self.limit, self.offset)


@dataclass(frozen=True)
class SortTerm:
    """One persisted column and its direction in a route-owned ordering."""

    field: str
    direction: SortDirection

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or not _IDENTIFIER.fullmatch(self.field):
            raise ValueError("sort field must be a simple SQL identifier")
        if self.direction not in ("ASC", "DESC"):
            raise ValueError("sort direction must be ASC or DESC")

    @property
    def sql(self) -> str:
        """A quoted identifier suitable for a route's fixed SQL statement."""

        return f'"{self.field}" {self.direction}'


@dataclass(frozen=True)
class DeterministicOrder:
    """A primary ordering completed by a persisted unique tie-breaker.

    The route must choose ``tie_breaker`` from the selected relation's declared
    unique key (or an equivalent unique projection).  The helper records that
    choice and prevents a duplicate primary term, but cannot infer database
    uniqueness from a Python field name.
    """

    primary: tuple[SortTerm, ...]
    tie_breaker: SortTerm

    def __post_init__(self) -> None:
        if not self.primary:
            raise ValueError("a deterministic order needs at least one primary term")
        fields = [term.field for term in self.primary]
        if len(fields) != len(set(fields)):
            raise ValueError("primary sort fields must be unique")
        if self.tie_breaker.field in fields:
            raise ValueError("tie breaker must be distinct from primary sort fields")

    @property
    def sql(self) -> str:
        """The complete route-owned ``ORDER BY`` expression, including the tie."""

        return ", ".join([*(term.sql for term in self.primary), self.tie_breaker.sql])

    def clause(self, page: PageRequest) -> tuple[str, tuple[int, int]]:
        """Return the SQL suffix and bound values for a deterministic page."""

        return (f"ORDER BY {self.sql} LIMIT ? OFFSET ?", page.sql_parameters)

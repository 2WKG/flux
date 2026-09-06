"""Behavioral contract tests for shared pagination and deterministic ordering."""

from __future__ import annotations

import duckdb
import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from copilot.api.errors import InvalidInputError, install_error_handlers
from copilot.api.pagination import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MAX_PAGE_OFFSET,
    DeterministicOrder,
    PageRequest,
    SortTerm,
)


def test_page_request_has_a_small_default_and_binds_sql_values() -> None:
    request = PageRequest()

    assert request.limit == DEFAULT_PAGE_LIMIT == 50
    assert request.offset == 0
    assert request.sql_parameters == (50, 0)


@pytest.mark.parametrize(
    ("limit", "offset", "field"),
    [
        (0, 0, "limit"),
        (MAX_PAGE_LIMIT + 1, 0, "limit"),
        (1, -1, "offset"),
        (1, MAX_PAGE_OFFSET + 1, "offset"),
    ],
)
def test_page_request_refuses_out_of_range_values_as_invalid_input(
    limit: int, offset: int, field: str
) -> None:
    with pytest.raises(InvalidInputError) as raised:
        PageRequest(limit=limit, offset=offset)

    assert raised.value.code == "invalid_input"
    assert raised.value.http_status == 422
    assert raised.value.details == {"field": field}


@pytest.mark.parametrize(("limit", "offset"), [(True, 0), (1, False)])
def test_page_request_refuses_non_integer_values(limit: object, offset: object) -> None:
    with pytest.raises(TypeError):
        PageRequest(limit=limit, offset=offset)  # type: ignore[arg-type]


def test_max_limit_is_a_default_a_route_may_override_with_its_specd_bound() -> None:
    """``MAX_PAGE_LIMIT`` caps only routes that declare no bound of their own.

    ``GET /predictions`` is pinned at 1-1000 by ``docs/specs/00-overview.md``
    §4.2, so a route must be able to carry its spec'd bound through the same
    helper instead of being silently narrowed to the shared default.
    """

    assert PageRequest(limit=MAX_PAGE_LIMIT).limit == MAX_PAGE_LIMIT

    with pytest.raises(InvalidInputError):
        PageRequest(limit=MAX_PAGE_LIMIT + 1)

    wide = PageRequest(limit=1000, max_limit=1000)
    assert wide.limit == 1000
    assert wide.sql_parameters == (1000, 0)

    with pytest.raises(InvalidInputError) as raised:
        PageRequest(limit=1001, max_limit=1000)
    assert "between 1 and 1000" in raised.value.message

    narrow = PageRequest(limit=50, max_limit=50)
    assert narrow.limit == 50
    with pytest.raises(InvalidInputError):
        PageRequest(limit=51, max_limit=50)


def test_out_of_range_page_values_reach_the_shared_422_envelope() -> None:
    """A route that builds a ``PageRequest`` from query values answers 422.

    Without the shared ``InvalidInputError`` the same construction raises a bare
    ``ValueError`` that ``install_error_handlers`` does not map, so the client
    sees a 500 instead of the documented ``invalid_input`` failure.
    """

    app = install_error_handlers(FastAPI())

    @app.get("/paged")
    def paged(limit: int = Query(DEFAULT_PAGE_LIMIT), offset: int = Query(0)) -> dict:
        page = PageRequest(limit=limit, offset=offset)
        return {"limit": page.limit, "offset": page.offset}

    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/paged", params={"limit": 10}).status_code == 200

    response = client.get("/paged", params={"limit": MAX_PAGE_LIMIT + 1})
    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "invalid_input"
    assert body["error"]["retryable"] is False
    assert body["error"]["details"] == {"field": "limit"}
    assert response.headers["X-Flux-Api-Version"] == "v1"

    offset_response = client.get("/paged", params={"offset": MAX_PAGE_OFFSET + 1})
    assert offset_response.status_code == 422
    assert offset_response.json()["error"]["details"] == {"field": "offset"}


def test_tied_primary_keys_are_ordered_by_the_declared_tie_breaker() -> None:
    """Equal primary sort keys must page in the documented tie-break order.

    Rows are inserted in an order that disagrees with both the primary sort and
    the tie-break, so physical order cannot produce the asserted sequence. If
    ``DeterministicOrder.sql`` stops emitting the tie-break, the two tied rows
    come back in insertion order and this test fails.
    """

    order = DeterministicOrder(
        primary=(SortTerm("score_value", "DESC"),),
        tie_breaker=SortTerm("artifact_id", "ASC"),
    )
    suffix, parameters = order.clause(PageRequest(limit=10, offset=0))

    with duckdb.connect(":memory:") as con:
        con.execute(
            "CREATE TABLE scores(artifact_id TEXT PRIMARY KEY, score_value DOUBLE)"
        )
        con.executemany(
            "INSERT INTO scores VALUES (?, ?)",
            [("b", 5.0), ("c", 1.0), ("a", 5.0)],
        )
        served = [
            row[0]
            for row in con.execute(
                f"SELECT artifact_id FROM scores {suffix}", parameters
            ).fetchall()
        ]

        assert served == ["a", "b", "c"]

        pages = []
        for offset in range(3):
            page_suffix, page_parameters = order.clause(
                PageRequest(limit=1, offset=offset)
            )
            pages.extend(
                row[0]
                for row in con.execute(
                    f"SELECT artifact_id FROM scores {page_suffix}", page_parameters
                ).fetchall()
            )

        assert pages == ["a", "b", "c"]


def test_total_order_appends_the_declared_tie_breaker_before_paging() -> None:
    order = DeterministicOrder(
        primary=(SortTerm("score_value", "DESC"),),
        tie_breaker=SortTerm("artifact_id", "ASC"),
    )

    assert order.sql == '"score_value" DESC, "artifact_id" ASC'
    assert order.clause(PageRequest(limit=25, offset=50)) == (
        'ORDER BY "score_value" DESC, "artifact_id" ASC LIMIT ? OFFSET ?',
        (25, 50),
    )


@pytest.mark.parametrize(
    "order",
    [
        lambda: DeterministicOrder(primary=(), tie_breaker=SortTerm("id", "ASC")),
        lambda: DeterministicOrder(
            primary=(SortTerm("score", "DESC"), SortTerm("score", "ASC")),
            tie_breaker=SortTerm("id", "ASC"),
        ),
        lambda: DeterministicOrder(
            primary=(SortTerm("score", "DESC"),),
            tie_breaker=SortTerm("score", "ASC"),
        ),
    ],
)
def test_total_order_requires_a_distinct_explicit_tie_breaker(order: object) -> None:
    with pytest.raises(ValueError):
        order()  # type: ignore[operator]


@pytest.mark.parametrize("field", ["score; DROP TABLE rows", "score-value", '"score"'])
def test_sort_term_does_not_allow_arbitrary_sql_fragments(field: str) -> None:
    with pytest.raises(ValueError):
        SortTerm(field, "DESC")

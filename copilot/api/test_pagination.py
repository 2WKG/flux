"""Behavioral contract tests for shared pagination and deterministic ordering."""

from __future__ import annotations

import pytest

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
    ("limit", "offset"),
    [
        (0, 0),
        (MAX_PAGE_LIMIT + 1, 0),
        (1, -1),
        (1, MAX_PAGE_OFFSET + 1),
        (True, 0),
        (1, False),
    ],
)
def test_page_request_refuses_unbounded_or_non_integer_values(
    limit: object, offset: object
) -> None:
    with pytest.raises((TypeError, ValueError)):
        PageRequest(limit=limit, offset=offset)  # type: ignore[arg-type]


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

from __future__ import annotations

import pytest
from pydantic import ValidationError

from copilot.routes.ask import AskContext


def test_ask_context_accepts_explicit_forecast_and_model_scope() -> None:
    assert (
        AskContext(
            region="texas",
            county_fips="48201",
            view_mode="texas_model",
        ).county_fips
        == "48201"
    )


@pytest.mark.parametrize(
    "context",
    [
        {"region": "texas", "county_fips": "27053"},
        {"region": "minnesota", "county_fips": "48201"},
        {"region": "minnesota", "view_mode": "texas_model"},
    ],
)
def test_ask_context_rejects_conflicting_stateful_scope(
    context: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        AskContext(**context)

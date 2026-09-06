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


def test_ask_context_keeps_physical_asset_identity_separate_from_model_element() -> (
    None
):
    context = AskContext(
        region="texas",
        view_mode="physical_inventory",
        selected_physical_asset_id="eia860:2025er:generation_unit:10072:GEN1:operable",
    )
    assert context.selected_element_id is None
    assert context.selected_physical_asset_id.endswith(":operable")


def test_ask_context_rejects_client_invented_physical_asset_identity() -> None:
    with pytest.raises(ValidationError):
        AskContext(selected_physical_asset_id="not an asset")


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

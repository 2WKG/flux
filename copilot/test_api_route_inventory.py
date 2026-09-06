"""Inventory the registered Minnesota API surface and its unresolved legacy gap."""

from __future__ import annotations

from copilot.app import create_app

REGISTERED_MINNESOTA_SURFACE = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/layers/{layer_name}"),
        ("POST", "/site-score"),
        ("POST", "/compare"),
        ("GET", "/lines/top"),
        ("GET", "/elements/critical"),
        ("GET", "/scenarios"),
        ("GET", "/scenarios/{scenario_id}"),
        ("GET", "/predictions"),
        ("GET", "/cascade"),
        ("POST", "/ask"),
    }
)

# These routes remain documented in the legacy 00/05 route tables, but are not
# registered by the Minnesota artifact-read API. Keep this inventory explicit:
# 2WKG-106 cannot claim its "every documented route" acceptance condition until
# their product/documentation disposition is decided.
LEGACY_DOCUMENTED_BUT_ABSENT = frozenset(
    {
        ("POST", "/predict"),
        ("POST", "/cascade"),
    }
)


def test_registered_read_surface_and_legacy_route_gap_are_explicit() -> None:
    paths = create_app().openapi()["paths"]
    registered = frozenset(
        (method.upper(), path)
        for path, operations in paths.items()
        for method in operations
    )

    assert registered == REGISTERED_MINNESOTA_SURFACE
    assert not registered & LEGACY_DOCUMENTED_BUT_ABSENT

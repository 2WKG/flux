"""The unresolved legacy route gap in the registered Minnesota API surface.

The registered set itself is pinned by ``copilot/test_read_route_contracts.py``,
which requires a contract cell per route; both modules read the live surface
through ``copilot._artifact_fixtures.registered_routes`` rather than keeping
their own copy of the derivation.
"""

from __future__ import annotations

from copilot._artifact_fixtures import registered_routes

# These routes remain documented in the legacy 00/05 route tables, but are not
# registered by the Minnesota artifact-read API. Keep this inventory explicit:
# 2WKG-106 cannot claim its "every documented route" acceptance condition until
# their product/documentation disposition is decided.
LEGACY_DOCUMENTED_BUT_ABSENT = frozenset(
    {
        ("POST", "/predict"),
        ("POST", "/cascade"),
        ("GET", "/lines/top"),
        ("GET", "/elements/critical"),
    }
)


def test_legacy_documented_routes_are_still_absent() -> None:
    assert not registered_routes() & LEGACY_DOCUMENTED_BUT_ABSENT

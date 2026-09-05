"""Small, explicit state selection helpers for public-data acquisition."""

from __future__ import annotations

STATE_CODES = frozenset((
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
))


def parse_states(values: list[str] | None, *, default: tuple[str, ...] = ("TX",)) -> tuple[str, ...]:
    """Normalize comma-separated postal abbreviations while preserving request order."""
    if not values:
        return default
    states: list[str] = []
    for value in values:
        for part in value.split(","):
            state = part.strip().upper()
            if state not in STATE_CODES:
                raise ValueError(f"unsupported state {part!r}; use two-letter US postal abbreviations")
            if state not in states:
                states.append(state)
    if not states:
        raise ValueError("at least one state is required")
    return tuple(states)

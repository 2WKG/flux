"""Route-parameter contract shared by the read routes.

One source of truth for the documented layer names and the shape of path
identifiers, imported by both ``copilot.routes.layers`` and
``copilot.routes.scenarios``.  ``DOCUMENTED_LAYERS`` is pinned to the table in
``docs/specs/05-copilot.md`` §Layers by a test; change both together.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import Path

# The layer names documented by 05-copilot §Layers / 00-overview §4.2.
DOCUMENTED_LAYERS: Final = frozenset(
    {
        "buses",
        "lines",
        "gens",
        "counties",
        "critical_loads",
        "outage_risk",
        "cascade",
        "sites",
        "line_upgrades",
        "storm",
        "national_hex",
        "eaglei",
    }
)
# Layers whose artifact this service actually serves today.
BUILT_LAYERS: Final = frozenset({"buses"})

# Identifiers are lowercase ASCII words: first character alphanumeric (layers:
# alphabetic), then alphanumerics, underscores (layers) or hyphens (scenarios).
SCENARIO_ID_PATTERN: Final = r"^[a-z0-9][a-z0-9_-]*$"
SCENARIO_ID_MAX_LENGTH: Final = 64
LAYER_NAME_PATTERN: Final = r"^[a-z][a-z0-9_]*$"
LAYER_NAME_MAX_LENGTH: Final = 32

ScenarioId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=SCENARIO_ID_MAX_LENGTH,
        pattern=SCENARIO_ID_PATTERN,
        description="Lowercase scenario identifier from the scenario catalog.",
    ),
]

LayerName = Annotated[
    str,
    Path(
        min_length=1,
        max_length=LAYER_NAME_MAX_LENGTH,
        pattern=LAYER_NAME_PATTERN,
        description=(
            "Map layer name. Shape is validated here; whether the name is "
            "documented or built is decided by the route."
        ),
    ),
]

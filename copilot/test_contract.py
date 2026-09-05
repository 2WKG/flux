"""Pins the shared route contract to the specs and to both route modules."""

from __future__ import annotations

import re
from pathlib import Path

from copilot.routes import layers, scenarios
from copilot.routes.contract import (
    BUILT_LAYERS,
    DOCUMENTED_LAYERS,
    LAYER_NAME_PATTERN,
    SCENARIO_ID_PATTERN,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_COPILOT_SPEC = _REPO_ROOT / "docs" / "specs" / "05-copilot.md"
_OVERVIEW_SPEC = _REPO_ROOT / "docs" / "specs" / "00-overview.md"


def _layer_names_from_copilot_spec() -> set[str]:
    text = _COPILOT_SPEC.read_text(encoding="utf-8")
    start = text.index("### Layers endpoint")
    end = text.index("## Interfaces", start)
    section = text[start:end]
    names = {
        match.group(1)
        for match in re.finditer(r"^\| `([a-z][a-z0-9_]*)` \|", section, re.MULTILINE)
    }
    assert names, "the Layers table in 05-copilot.md was not parsed"
    return names


def _layer_names_from_overview() -> set[str]:
    text = _OVERVIEW_SPEC.read_text(encoding="utf-8")
    match = re.search(r"GET\s+/layers/\{name\}.*?name ∈ \{([^}]*)\}", text, re.DOTALL)
    assert match, "the /layers name set in 00-overview.md §4.2 was not parsed"
    return {name.strip() for name in match.group(1).replace("\n", " ").split(",")}


def test_documented_layers_match_every_name_in_the_copilot_spec_table() -> None:
    assert DOCUMENTED_LAYERS == _layer_names_from_copilot_spec()


def test_documented_layers_match_the_overview_route_list() -> None:
    assert DOCUMENTED_LAYERS == _layer_names_from_overview()


def test_built_layers_are_a_subset_of_the_documented_ones() -> None:
    assert BUILT_LAYERS <= DOCUMENTED_LAYERS
    assert BUILT_LAYERS == {"buses"}


def test_both_route_modules_use_the_shared_contract_objects() -> None:
    assert layers.DOCUMENTED_LAYERS is DOCUMENTED_LAYERS
    assert layers.BUILT_LAYERS is BUILT_LAYERS
    assert scenarios.ScenarioId is not None
    assert not hasattr(scenarios, "Path"), (
        "scenarios.py should not build its own Path()"
    )
    assert not hasattr(layers, "Path"), "layers.py should not build its own Path()"


def test_every_documented_layer_name_satisfies_the_layer_name_pattern() -> None:
    for name in DOCUMENTED_LAYERS:
        assert re.fullmatch(LAYER_NAME_PATTERN, name), name


def test_seeded_scenario_ids_satisfy_the_scenario_id_pattern() -> None:
    for scenario_id in ("uri_2021", "beryl_2024", "helene_2024", "forecast_72h"):
        assert re.fullmatch(SCENARIO_ID_PATTERN, scenario_id), scenario_id
    for rejected in ("URI_2021", "-leading", "a.b", "üri", ""):
        assert not re.fullmatch(SCENARIO_ID_PATTERN, rejected), rejected

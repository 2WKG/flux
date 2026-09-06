"""Guards for spec 12's registration in the authority documents.

Spec 12 (`docs/specs/12-interactive-simulation.md`) declares new DuckDB tables, new
copilot tools and a new HTTP namespace. `docs/specs/00-overview.md` wins over any
downstream spec (`00-overview.md` lattice rule 3, `docs/specs/README.md:33`), so the
declarations only exist once they are registered there. These tests fail if the
registration is removed, if the retired bare-root ``POST /cascade`` (D-3) is reopened,
if the 345 kV bus class that ACTIVSg2000 does not have comes back
(`docs/specs/VERIFICATION.md:46-47`), if a second spelling of the canonical topology
label appears, or if the false "never built" claim about ``run_cascade`` /
``score_site`` / ``predict_outage`` is restored.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from copilot.tools.schemas import TOOL_REGISTRY

SPECS = Path(__file__).resolve().parents[1] / "docs" / "specs"
SPEC_12 = (SPECS / "12-interactive-simulation.md").read_text(encoding="utf-8")
OVERVIEW = (SPECS / "00-overview.md").read_text(encoding="utf-8")

NEW_TABLES = ("scenario_edits", "redundancy_scores", "siting_search_runs")
NEW_TOOLS = ("edit_scenario", "grid_balance", "redundancy_score", "search_locations")
ALREADY_REGISTERED = ("run_cascade", "score_site", "predict_outage")
CANONICAL_TOPOLOGY_LABEL = "synthetic (ACTIVSg2000)"


@pytest.mark.parametrize("table", NEW_TABLES)
def test_spec_12_tables_are_registered_in_the_shared_contract(table: str) -> None:
    """Each new table has a §2.2 row in 00-overview, not only a line in spec 12."""
    assert f"| `{table}` |" in OVERVIEW, (
        f"{table} is declared by spec 12 but has no 00-overview.md §2.2 row, "
        "so it is not in the shared contract"
    )


@pytest.mark.parametrize("tool", NEW_TOOLS)
def test_spec_12_tools_are_registered_in_the_shared_contract(tool: str) -> None:
    """Each new tool has a signature in 00-overview's tool block."""
    assert re.search(rf"^def {tool}\(", OVERVIEW, re.MULTILINE), (
        f"{tool} is declared by spec 12 but has no 00-overview.md tool signature"
    )


def test_spec_12_carries_an_amendment_marker() -> None:
    assert "A13" in OVERVIEW and "A13" in SPEC_12


@pytest.mark.parametrize("tool", ALREADY_REGISTERED)
def test_spec_12_does_not_claim_existing_tools_were_never_built(tool: str) -> None:
    """The three tools spec 12 once called unbuilt are in the frozen registry."""
    assert tool in {definition.name for definition in TOOL_REGISTRY}
    assert "never built" not in SPEC_12, (
        "spec 12 claims tools were never built; run_cascade, score_site and "
        "predict_outage are registered in copilot/tools/schemas.py"
    )


def test_spec_12_names_no_345_kv_bus() -> None:
    """ACTIVSg2000 has no 345 kV class (VERIFICATION.md:46-47)."""
    allowed = ("345 kV**", "name a 345 kV bus")
    offending = [
        line
        for line in SPEC_12.splitlines()
        if "345 kV" in line and not any(marker in line for marker in allowed)
    ]
    assert offending == [], offending
    assert "345 kV" in SPEC_12, (
        "the correction recording that ACTIVSg2000 has no 345 kV is gone"
    )


def test_spec_12_mounts_its_compute_routes_under_the_interactive_prefix() -> None:
    """D-3 stays closed: no bare-root compute route re-declared."""
    for path in (
        "/interactive/scenario/edit",
        "/interactive/cascade",
        "/interactive/balance",
        "/interactive/redundancy",
        "/interactive/siting/search",
    ):
        assert path in SPEC_12, f"{path} missing from spec 12"
    bare = [
        line
        for line in SPEC_12.splitlines()
        if re.match(r"\s*(POST|GET)\s+/(?!interactive/)", line)
    ]
    assert bare == [], bare
    assert "/interactive" in OVERVIEW


def test_spec_12_uses_the_canonical_topology_label_only() -> None:
    assert CANONICAL_TOPOLOGY_LABEL in SPEC_12
    assert '"network_provenance": "synthetic_activsg2000"' not in SPEC_12


def test_spec_12_keeps_success_bodies_unwrapped() -> None:
    assert "unwrapped" in SPEC_12
    assert "unwrapped" in OVERVIEW


def test_spec_12_supersedes_nothing_above_its_lattice_level() -> None:
    """A level-4 spec cannot supersede level-2 10-minnesota-demo.md."""
    assert "supersedes [`10-minnesota-demo.md`]" not in SPEC_12
    assert "supersedes nothing" in SPEC_12.lower()

"""The explainer's teaching solve, and the artifact the page replays.

Two properties: the solve itself is right (balance, DC arithmetic, the trip
rule, island shedding), and the committed artifact is exactly what a fresh solve
produces -- so the trace the browser replays cannot drift away from the server
that made it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.export_toy_cascade_trace import ARTIFACT, write_artifact
from twin.toy_cascade import (
    TOY_LINES,
    ToyCascadeError,
    _solve_linear_system,
    run_toy_cascade,
    solve_toy_dc,
    toy_cascade_trace,
    trace_hash,
)


def test_the_dc_solve_balances_specified_injections_and_reports_utilization() -> None:
    solved = solve_toy_dc(frozenset(line.id for line in TOY_LINES))
    assert sum(solved["injections"].values()) == pytest.approx(0.0, abs=1e-9)
    assert solved["actions"] == []
    assert all(
        isinstance(line["flowMw"], float) and isinstance(line["utilizationPct"], float)
        for line in solved["lines"]
    )
    # F = (theta_i - theta_j) / X, not a fraction of the rating.
    west_hub = next(line for line in solved["lines"] if line["id"] == "west-hub")
    angles = solved["angles"]
    assert west_hub["flowMw"] == pytest.approx(
        (angles["west"] - angles["hub"]) / 0.2, abs=1e-5
    )
    assert west_hub["utilizationPct"] == pytest.approx(
        abs(west_hub["flowMw"]) / west_hub["ratingMw"] * 100, abs=1e-5
    )


def test_the_seeded_outage_cascades_and_sheds_the_islanded_load() -> None:
    stages = run_toy_cascade()
    assert stages[1]["trippedLineId"] == "hub-east"
    assert stages[1]["nextTripLineId"] == "east-south"
    assert stages[2]["trippedLineId"] == "east-south"
    assert any(
        action["busId"] == "east"
        and action["kind"] == "shed_load"
        and action["mw"] == pytest.approx(70.0)
        for action in stages[2]["balanceActions"]
    )
    assert any(
        action["kind"] == "curtail_generation" for action in stages[2]["balanceActions"]
    )
    assert stages[-1]["nextTripLineId"] is None


def test_a_singular_island_is_a_named_refusal_not_a_default() -> None:
    """The solve refuses by name rather than returning a plausible zero flow."""
    with pytest.raises(ToyCascadeError) as raised:
        _solve_linear_system([[0.0, 0.0], [0.0, 0.0]], [1.0, 1.0])
    assert str(raised.value) == "Toy DC matrix is singular."
    assert issubclass(ToyCascadeError, RuntimeError)


def test_the_artifact_states_it_is_not_the_products_solver() -> None:
    limitations = toy_cascade_trace()["limitations"]
    assert any("not the product's solver" in line for line in limitations)
    assert any("not ACTIVSg2000" in line for line in limitations)


def test_the_committed_artifact_is_exactly_a_fresh_server_solve(
    tmp_path: Path,
) -> None:
    committed = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    regenerated = json.loads(
        (write_artifact(tmp_path / "trace.json")).read_text(encoding="utf-8")
    )
    assert committed == regenerated, (
        "data/explainer/toy-cascade-trace.json is stale; rerun "
        "scripts/export_toy_cascade_trace.py"
    )


def test_the_artifact_digest_covers_the_stages_it_ships() -> None:
    trace = toy_cascade_trace()
    assert trace["traceHash"] == trace_hash(trace["stages"])
    mutated = json.loads(json.dumps(trace["stages"]))
    mutated[0]["lines"][0]["flowMw"] += 1.0
    assert trace_hash(mutated) != trace["traceHash"]
    committed = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert committed["traceHash"] == trace_hash(committed["stages"])

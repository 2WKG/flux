"""Capture real interactive-route payloads for the browser boundary.

``twin/balance.py`` and ``siting/redundancy.py`` are the only sources of truth
for the ``/interactive/balance`` and ``/interactive/redundancy`` response
shapes.  This script *runs* them and writes the captured payloads to
``web/src/contracts/interactive-payloads.json`` so the TypeScript boundary in
``web/src/data/interactive-client.ts`` can be checked against a payload the
producers actually emitted rather than a hand-written guess.  Run it with::

    uv run --extra dev python scripts/ci/export_interactive_contracts.py

``tests/test_interactive_contract_export.py`` fails when the committed file and
a fresh capture disagree, so the browser guards cannot drift away from the
producers without a red gate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandapower as pp

from siting.redundancy import score_redundancy
from twin.balance import balance_report

OUT_PATH = REPO_ROOT / "web" / "src" / "contracts" / "interactive-payloads.json"
REGENERATE = "uv run --extra dev python scripts/ci/export_interactive_contracts.py"


def balance_net() -> Any:
    """A three-bus network with declared fuels, mirroring twin/tests/test_balance.py."""
    net = pp.create_empty_network(sn_mva=100.0)
    buses = [pp.create_bus(net, 230.0, name=f"bus-{sid}") for sid in (101, 102, 103)]
    net["flux_bus_index"] = {101: buses[0], 102: buses[1], 103: buses[2]}
    net["flux_bus_metadata"] = {
        buses[index]: {
            "bus_id": bus_id,
            "state": "TX",
            "ba_code": "ERCO",
            "county_fips": county,
        }
        for index, (bus_id, county) in enumerate(
            ((101, "48001"), (102, "48003"), (103, "48005"))
        )
    }
    net["flux_element_lookup"] = {}
    for start, end, name in ((0, 1, "line:10"), (1, 2, "line:11")):
        index = pp.create_line_from_parameters(
            net, buses[start], buses[end], 1.0, 0.01, 0.1, 0.0, 1.0, name=name
        )
        net.line.at[index, "flux_element_id"] = name
        net.flux_element_lookup[name] = ("line", index)

    ext = pp.create_ext_grid(net, buses[0], name="generator:1")
    net.ext_grid.at[ext, "pmax_mw"] = 20.0
    net.ext_grid.at[ext, "fuel"] = "natural gas"
    coal = pp.create_gen(
        net, buses[0], p_mw=40.0, vm_pu=1.0, max_p_mw=100.0, name="generator:2"
    )
    wind = pp.create_gen(
        net, buses[1], p_mw=10.0, vm_pu=1.0, max_p_mw=50.0, name="generator:3"
    )
    solar = pp.create_sgen(net, buses[2], p_mw=0.0, max_p_mw=30.0, name="generator:4")
    net.gen.at[coal, "fuel"] = "coal"
    net.gen.at[wind, "fuel"] = "wind"
    net.sgen.at[solar, "fuel"] = "solar"
    pp.create_load(net, buses[0], p_mw=100.0, q_mvar=0.0, name="load:1")
    pp.create_load(net, buses[1], p_mw=30.0, q_mvar=0.0, name="load:2")
    pp.create_load(net, buses[2], p_mw=20.0, q_mvar=0.0, name="load:3")
    return net


def redundancy_net() -> Any:
    """Two sources: one direct path and one two-edge alternative path."""
    return SimpleNamespace(
        branches=[
            {"id": "direct", "from_bus": "load", "to_bus": "source_a", "dptf": 90.0},
            {"id": "via_mid_1", "from_bus": "load", "to_bus": "mid", "dptf": 70.0},
            {"id": "via_mid_2", "from_bus": "mid", "to_bus": "source_b", "dptf": 60.0},
            {"id": "low_priority", "from_bus": "mid", "to_bus": "spur", "dptf": 1.0},
        ],
        sources=[{"bus": "source_a"}, {"bus": "source_b"}],
        synthetic_topology=True,
    )


def build_document() -> dict[str, Any]:
    return {
        "description": f"Captured from the real producers by {REGENERATE}",
        "routes": {
            "/interactive/balance": {
                "method": "GET",
                "producer": "twin.balance.balance_report",
                "response": balance_report(balance_net(), scope="state"),
            },
            "/interactive/redundancy": {
                "method": "GET",
                "producer": "siting.redundancy.score_redundancy",
                "response": score_redundancy(redundancy_net(), "load"),
            },
        },
    }


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(build_document()), encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The committed interactive payload capture must match a fresh capture.

``web/src/data/interactive-client.ts`` derives its browser guards from
``web/src/contracts/interactive-payloads.json``.  That file is only useful if it
is what the producers actually emit, so this test re-runs the capture and
compares.  A producer change that is not re-exported fails here rather than
silently turning every live interactive response into ``malformed`` in the
browser.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "export_interactive_contracts.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "export_interactive_contracts", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_capture_matches_a_fresh_capture() -> None:
    module = _module()
    expected = module.render(module.build_document())
    actual = module.OUT_PATH.read_text(encoding="utf-8")
    assert actual == expected, (
        "web/src/contracts/interactive-payloads.json is stale; regenerate with "
        f"{module.REGENERATE}"
    )


def test_capture_keeps_the_producer_field_names_the_browser_guards_read() -> None:
    module = _module()
    document = module.build_document()
    balance = document["routes"]["/interactive/balance"]["response"]
    redundancy = document["routes"]["/interactive/redundancy"]["response"]

    for field in (
        "edit_hash",
        "scope",
        "draw_mw",
        "capability_mw",
        "dispatch_mw",
        "headroom_mw",
        "capability_basis",
        "limitations",
    ):
        assert field in balance

    for field in (
        "bus_id",
        "score",
        "components",
        "worst_contingency",
        "synthetic_topology",
        "evidence",
    ):
        assert field in redundancy

    # The browser must not re-derive headroom; the producer owns the rule.
    assert balance["headroom_mw"] == balance["capability_mw"] - balance["draw_mw"]
    assert isinstance(redundancy["evidence"]["synthetic_topology"], bool)

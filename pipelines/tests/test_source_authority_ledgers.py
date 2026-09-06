"""Run the shared source-authority ledger validator over every checked-in ledger."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_source_authority_ledger import (
    discover_ledgers,
    validate_ledger,
)

LEDGERS = discover_ledgers(ROOT)

# Ledgers that must exist. Without this the parametrisation below would pass
# vacuously if the glob ever stopped matching.
EXPECTED_LEDGERS = {
    "minnesota-source-authority-ledger-v1.json",
    "texas-distribution-source-authority-ledger-v1.json",
    "texas-source-authority-ledger-v1.json",
}


def test_every_expected_ledger_is_discovered():
    discovered = {path.name for path in LEDGERS}
    assert EXPECTED_LEDGERS <= discovered, discovered


@pytest.mark.parametrize("path", LEDGERS, ids=lambda path: path.name)
def test_ledger_satisfies_the_shared_schema(path: Path):
    ledger = json.loads(path.read_text(encoding="utf-8"))
    assert validate_ledger(ledger, ROOT) == []


def test_no_class_carries_two_different_statuses_for_the_same_state():
    """Two ledgers may own the same class; they may not disagree about it.

    ``distribution_feeder`` is recorded as ``unavailable`` in both
    ``texas-source-authority-ledger-v1.json`` and
    ``texas-distribution-source-authority-ledger-v1.json``. They agree today,
    and nothing noticed if a future edit to one silently contradicted the
    other.
    """
    seen: dict[tuple[str, str], dict[str, str]] = {}
    shared = 0
    for path in LEDGERS:
        ledger = json.loads(path.read_text(encoding="utf-8"))
        state = ledger["state"]
        for entry in ledger["physical_class_coverage"]:
            key = (state, entry["class_id"])
            if key in seen:
                shared += 1
                assert entry["status"] == seen[key]["status"], (
                    f"{key} is {entry['status']!r} in {path.name} but "
                    f"{seen[key]['status']!r} in {seen[key]['ledger']}"
                )
            else:
                seen[key] = {"status": entry["status"], "ledger": path.name}
    # Without a shared class this test would pass vacuously.
    assert shared >= 1, "no class_id is shared between ledgers for one state"
    assert ("TX", "distribution_feeder") in seen

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

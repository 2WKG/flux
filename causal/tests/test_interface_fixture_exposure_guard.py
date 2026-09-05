"""Contract-level exposure guard while no causal client or tool exists."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "causal" / "fixtures" / "interface_only_causal_fixture.json"
SCHEMA_PATH = ROOT / "docs" / "causal-evidence-artifact.schema.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _branch_validator(schema: dict, branch_index: int) -> Draft202012Validator:
    return Draft202012Validator({"$defs": schema["$defs"], **schema["oneOf"][branch_index]})


def test_interface_fixture_is_ineligible_for_the_available_estimate_contract_branch() -> None:
    """Keep a future consumer from confusing the fixture with an estimable result."""
    schema = _load_json(SCHEMA_PATH)
    fixture = _load_json(FIXTURE_PATH)

    assert _branch_validator(schema, 0).is_valid(fixture)
    assert not _branch_validator(schema, 2).is_valid(fixture)
    assert fixture["availability"]["status"] == "unavailable"
    assert "FIXTURE_NOT_ESTIMABLE" in fixture["availability"]["unavailable_codes"]
    assert "estimate" not in fixture

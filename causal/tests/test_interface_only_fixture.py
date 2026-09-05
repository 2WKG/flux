"""Contract checks for the causal interface-only rendering fixture."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "interface_only_causal_fixture.json"
)
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "causal-evidence-artifact.schema.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_interface_fixture_fails_closed_without_an_estimate() -> None:
    fixture = _fixture()

    assert fixture["classification"] == "interface_fixture"
    assert fixture["availability"] == {
        "status": "unavailable",
        "unavailable_codes": ["FIXTURE_NOT_ESTIMABLE"],
    }
    assert "estimate" not in fixture


def test_interface_fixture_validates_against_its_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_fixture())

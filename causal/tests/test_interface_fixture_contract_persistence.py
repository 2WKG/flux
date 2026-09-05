"""Schema and persistence checks for the interface-only causal fixture."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "causal" / "fixtures" / "interface_only_causal_fixture.json"
SCHEMA_PATH = ROOT / "docs" / "causal-evidence-artifact.schema.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    return Draft202012Validator(_load_json(SCHEMA_PATH))


def test_interface_fixture_validates_against_the_causal_contract() -> None:
    errors = list(_validator().iter_errors(_load_json(FIXTURE_PATH)))

    assert errors == []


def test_interface_fixture_json_round_trips_to_identical_bytes() -> None:
    serialized = FIXTURE_PATH.read_bytes()
    persisted = (json.dumps(_load_json(FIXTURE_PATH), indent=2) + "\n").encode("utf-8")

    assert persisted == serialized


@pytest.mark.parametrize(
    "mutate",
    [
        lambda artifact: artifact["availability"].update({"status": "available"}),
        lambda artifact: (
            artifact.update({"classification": "estimable_study"}),
            artifact["availability"].update({"status": "available"}),
            artifact["availability"].pop("unavailable_codes"),
        ),
    ],
    ids=["available-with-unavailable-code", "estimable-without-estimate"],
)
def test_contract_rejects_mutations_that_make_fixture_look_estimable(mutate) -> None:
    mutated = deepcopy(_load_json(FIXTURE_PATH))
    mutate(mutated)

    assert not _validator().is_valid(mutated)

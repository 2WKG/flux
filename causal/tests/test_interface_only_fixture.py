"""Contract checks for the causal interface-only rendering fixture."""

import json
from pathlib import Path


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "interface_only_causal_fixture.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _walk(value):
    if isinstance(value, dict):
        yield from value.items()
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_interface_fixture_fails_closed_without_an_estimate() -> None:
    fixture = _fixture()

    assert fixture["classification"] == "interface_fixture"
    assert fixture["availability"] == {
        "status": "unavailable",
        "unavailable_codes": ["FIXTURE_NOT_ESTIMABLE"],
    }
    assert "estimate" not in fixture


def test_interface_fixture_has_labeled_placeholders_and_provenance() -> None:
    fixture = _fixture()
    source_ids = {source["source_id"] for source in fixture["sources"]}

    for variable in (
        fixture["question"]["treatment"],
        fixture["question"]["outcome"],
    ):
        assert all(variable[field] for field in ("name", "definition", "unit_or_category"))
        assert variable["source_id"] in source_ids

    assert fixture["citations"]
    assert all(citation["source_id"] in source_ids for citation in fixture["citations"])
    assert any(
        diagnostic["name"] == "Method placeholder"
        and diagnostic["status"] == "not_run"
        for diagnostic in fixture["diagnostics"]
    )
    assert any("Insufficiency reason:" in diagnostic["evidence"] for diagnostic in fixture["diagnostics"])
    assert any(assumption.startswith("Caveat:") for assumption in fixture["assumptions"])


def test_interface_fixture_cannot_suggest_a_causal_result() -> None:
    fixture = _fixture()
    forbidden_keys = {"estimate", "effect", "interval", "p_value", "p-value", "efficacy"}

    assert not {key.lower() for key, _ in _walk(fixture)} & forbidden_keys

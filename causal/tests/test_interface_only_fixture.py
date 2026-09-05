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


def _sufficient_study() -> dict:
    variable = {
        "name": "outage duration",
        "definition": "hours without service",
        "unit_or_category": "hours",
        "source_id": "source-1",
    }
    citation = {"source_id": "source-1", "locator": "table-1"}
    return {
        "artifact_version": "1.0.0",
        "artifact_id": "sufficient-study-test",
        "classification": "estimable_study",
        "question": {
            "treatment": variable,
            "outcome": variable,
            "target_population": {
                "description": "test population",
                "geography": "test geography",
                "time_window": "test period",
            },
        },
        "sources": [{"source_id": "source-1", "name": "test", "version": "1", "locator": "table-1", "coverage": "test period"}],
        "sample": {"unit": "county", "n_total": 2, "n_treated": 1, "n_control": 1, "period": "test period"},
        "covariates": [],
        "assumptions": ["test assumption"],
        "diagnostics": [{"name": "test diagnostic", "status": "pass", "evidence": "test evidence"}],
        "citations": [citation],
        "availability": {"status": "available"},
        "estimate": {
            "estimand": "test estimand",
            "method": "test method",
            "effect": 1,
            "interval": {"lower": 0, "upper": 2},
            "confidence_level": 0.95,
            "evidence": [citation],
            "caveats": ["test caveat"],
        },
    }


def test_sufficient_study_rejects_nonpassing_diagnostics() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    assert validator.is_valid(_sufficient_study())
    for status in ("fail", "not_run"):
        study = _sufficient_study()
        study["diagnostics"][0]["status"] = status
        assert not validator.is_valid(study)

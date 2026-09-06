"""Behavioral tests for the causal evidence prerequisite validator."""

from copy import deepcopy

import pytest

from causal.validation import (
    FIXTURE_NOT_ESTIMABLE,
    MISSING_DATA_COVERAGE,
    MISSING_DIAGNOSTICS,
    MISSING_IDENTIFICATION,
    MISSING_OUTCOME_DEFINITION,
    MISSING_TREATMENT_DEFINITION,
    validate_artifact,
)


def _study() -> dict:
    variable = {
        "name": "outage duration",
        "definition": "hours without service",
        "unit_or_category": "hours",
        "source_id": "source-1",
    }
    return {
        "classification": "estimable_study",
        "question": {
            "treatment": deepcopy(variable),
            "outcome": deepcopy(variable),
            "target_population": {
                "description": "test population",
                "geography": "test geography",
                "time_window": "test period",
            },
        },
        "sources": [
            {
                "source_id": "source-1",
                "name": "test source",
                "version": "1",
                "locator": "table-1",
                "coverage": "test period",
            }
        ],
        "sample": {
            "unit": "county",
            "n_total": 2,
            "n_treated": 1,
            "n_control": 1,
            "period": "test period",
        },
        "covariates": [],
        "assumptions": ["conditional exchangeability"],
        "diagnostics": [{"name": "balance", "status": "pass", "evidence": "recorded"}],
        "availability": {"status": "available"},
        "estimate": {"estimand": "ATE", "method": "twfe_only"},
    }


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda study: study.update(classification="interface_fixture"),
            FIXTURE_NOT_ESTIMABLE,
        ),
        (lambda study: study.update(assumptions=[]), MISSING_IDENTIFICATION),
        (
            lambda study: study["question"].pop("treatment"),
            MISSING_TREATMENT_DEFINITION,
        ),
        (lambda study: study["question"].pop("outcome"), MISSING_OUTCOME_DEFINITION),
        (lambda study: study["sources"].clear(), MISSING_DATA_COVERAGE),
        (
            lambda study: study["diagnostics"].__setitem__(
                0, {"name": "balance", "status": "not_run", "evidence": "recorded"}
            ),
            MISSING_DIAGNOSTICS,
        ),
    ],
)
def test_each_insufficiency_code_fails_closed(mutate, expected) -> None:
    study = _study()
    mutate(study)

    result = validate_artifact(study)

    assert not result.estimable
    assert expected in result.unavailable_codes


def test_validator_returns_all_relevant_failed_criteria_without_data_values() -> None:
    study = _study()
    study.pop("assumptions")
    study["question"].pop("treatment")
    study["sources"].clear()
    study["diagnostics"].clear()

    result = validate_artifact(study)

    assert result.unavailable_codes == (
        MISSING_TREATMENT_DEFINITION,
        MISSING_IDENTIFICATION,
        MISSING_DATA_COVERAGE,
        MISSING_DIAGNOSTICS,
    )
    assert all(
        "source-1" not in diagnostic.message for diagnostic in result.diagnostics
    )


def test_minimally_valid_artifact_requires_explicit_method_and_passing_diagnostics() -> (
    None
):
    study = _study()

    assert validate_artifact(study).estimable

    study["estimate"].pop("method")
    result = validate_artifact(study)
    assert not result.estimable
    assert result.unavailable_codes == (MISSING_IDENTIFICATION,)


def test_unsupported_method_and_malformed_availability_fail_closed() -> None:
    study = _study()
    study["estimate"]["method"] = "not_a_supported_method"

    assert validate_artifact(study).unavailable_codes == (MISSING_IDENTIFICATION,)

    study = _study()
    study["availability"] = None
    assert validate_artifact(study).unavailable_codes == (MISSING_IDENTIFICATION,)


def test_incoherent_sample_counts_fail_closed() -> None:
    study = _study()
    study["sample"].update(n_total=0, n_treated=1, n_control=1)

    assert validate_artifact(study).unavailable_codes == (MISSING_DATA_COVERAGE,)

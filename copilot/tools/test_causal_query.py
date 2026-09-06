"""Tests for the bounded, read-only causal artifact query."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from copilot.tools.causal_query import (
    CausalArtifactReader,
    RegisteredCausalArtifact,
    causal_query,
    configure_causal_artifacts,
    evidence_from_artifact,
)
from copilot.tools.schemas import CausalQueryInput


def _request() -> CausalQueryInput:
    return CausalQueryInput(kind="effect", treatment="hardening_saidi")


def _artifact() -> dict:
    variable = {
        "name": "outage duration",
        "definition": "hours without service",
        "unit_or_category": "hours",
        "source_id": "source-1",
    }
    citation = {"source_id": "source-1", "locator": "table-1"}
    return {
        "artifact_version": "1.0.0",
        "artifact_id": "causal-effect-test",
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
        "citations": [citation],
        "availability": {"status": "available"},
        "estimate": {
            "estimand": "ATE",
            "method": "twfe_only",
            "effect": 1.5,
            "interval": {"lower": 0.5, "upper": 2.5},
            "confidence_level": 0.95,
            "evidence": [citation],
            "caveats": ["observational"],
        },
    }


def _reader(path: Path) -> CausalArtifactReader:
    return CausalArtifactReader(
        (RegisteredCausalArtifact(_request(), path, "observed"),)
    )


def test_valid_registered_artifact_is_read_without_estimation(tmp_path: Path) -> None:
    path = tmp_path / "effect.json"
    path.write_text(json.dumps(_artifact()), encoding="utf-8")

    result = _reader(path).query(_request())

    assert result.status == "available"
    assert result.answer_numbers == {"effect": 1.5}
    assert result.method == "twfe_only"
    assert result.provenance[0].artifact_id == "causal-effect-test"
    assert result.question.treatment.definition == "hours without service"
    assert result.sources[0].coverage == "test period"
    assert result.sample.n_total == 2
    assert result.diagnostics[0].status == "pass"
    assert result.citations[0].locator == "table-1"
    assert result.evidence_rows == []

    evidence = evidence_from_artifact(_artifact())
    assert evidence.sample.n_total == 2
    assert evidence.citations[0].locator == "table-1"


def test_fixture_and_malformed_artifacts_cannot_yield_an_effect(tmp_path: Path) -> None:
    path = tmp_path / "effect.json"
    fixture = {
        "artifact_version": "1.0.0",
        "artifact_id": "fixture",
        "classification": "interface_fixture",
        "availability": {
            "status": "unavailable",
            "unavailable_codes": ["FIXTURE_NOT_ESTIMABLE"],
        },
    }
    path.write_text(json.dumps(fixture), encoding="utf-8")

    fixture_result = _reader(path).query(_request())
    assert fixture_result.status == "unavailable"
    assert fixture_result.unavailable.code == "insufficient_evidence"
    assert "FIXTURE_NOT_ESTIMABLE" in fixture_result.unavailable.reason

    path.write_text("{not JSON", encoding="utf-8")
    malformed_result = _reader(path).query(_request())
    assert malformed_result.status == "unavailable"
    assert malformed_result.unavailable.code == "artifact_unavailable"


def test_unregistered_selection_is_rejected_without_reading_a_path(
    tmp_path: Path,
) -> None:
    result = _reader(tmp_path / "does-not-exist.json").query(
        CausalQueryInput(kind="effect", treatment="firm_generation_100mw")
    )

    assert result.status == "unavailable"
    assert result.unavailable.code == "unsupported_request"


def test_public_tool_returns_unavailable_until_deployment_registers_artifacts() -> None:
    configure_causal_artifacts(())

    result = causal_query("effect", treatment="hardening_saidi")

    assert result.status == "unavailable"
    assert result.unavailable.code == "unsupported_request"


@pytest.mark.parametrize(
    ("unavailable_code", "mutate"),
    [
        (
            "MISSING_IDENTIFICATION",
            lambda artifact: artifact.update(
                availability={
                    "status": "unavailable",
                    "unavailable_codes": ["MISSING_IDENTIFICATION"],
                }
            ),
        ),
        (
            "MISSING_TREATMENT_DEFINITION",
            lambda artifact: (
                artifact.pop("question"),
                artifact.update(
                    availability={
                        "status": "unavailable",
                        "unavailable_codes": ["MISSING_TREATMENT_DEFINITION"],
                    }
                ),
            ),
        ),
        (
            "MISSING_OUTCOME_DEFINITION",
            lambda artifact: (
                artifact.pop("question"),
                artifact.update(
                    availability={
                        "status": "unavailable",
                        "unavailable_codes": ["MISSING_OUTCOME_DEFINITION"],
                    }
                ),
            ),
        ),
        (
            "MISSING_DATA_COVERAGE",
            lambda artifact: (
                artifact["sample"].pop("n_treated"),
                artifact["sample"].pop("n_control"),
                artifact.update(
                    availability={
                        "status": "unavailable",
                        "unavailable_codes": ["MISSING_DATA_COVERAGE"],
                    }
                ),
            ),
        ),
        (
            "MISSING_DIAGNOSTICS",
            lambda artifact: (
                artifact["diagnostics"].__setitem__(
                    0,
                    {"name": "balance", "status": "not_run", "evidence": "recorded"},
                ),
                artifact.update(
                    availability={
                        "status": "unavailable",
                        "unavailable_codes": ["MISSING_DIAGNOSTICS"],
                    }
                ),
            ),
        ),
    ],
)
def test_each_insufficiency_code_returns_unavailable_without_an_effect(
    tmp_path: Path, unavailable_code: str, mutate
) -> None:
    path = tmp_path / "effect.json"
    artifact = deepcopy(_artifact())
    artifact.pop("estimate")
    mutate(artifact)
    path.write_text(json.dumps(artifact), encoding="utf-8")

    result = _reader(path).query(_request())

    assert result.status == "unavailable"
    assert result.unavailable.code == "insufficient_evidence"
    assert unavailable_code in result.unavailable.reason

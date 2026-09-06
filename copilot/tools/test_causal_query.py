"""Tests for the bounded, read-only causal artifact query."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

import copilot.tools.causal_query as causal_query_module
from copilot.tools.causal_query import (
    CausalArtifactReader,
    RegisteredCausalArtifact,
    causal_query,
    configure_causal_artifacts,
    evidence_from_artifact,
)
from copilot.tools.schemas import CausalCitation, CausalQueryInput

CITATION_LOCATOR = "table-1#row-7"


@pytest.fixture(autouse=True)
def _isolate_process_bindings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from an unconfigured tool process."""

    monkeypatch.setattr(causal_query_module, "_default_reader", None)


def _request() -> CausalQueryInput:
    return CausalQueryInput(kind="effect", treatment="hardening_saidi")


def _artifact() -> dict:
    treatment = {
        "name": "hardening",
        "definition": "line hardening completed",
        "unit_or_category": "category",
        "source_id": "source-1",
    }
    outcome = {
        "name": "outage duration",
        "definition": "hours without service",
        "unit_or_category": "hours",
        "source_id": "source-1",
    }
    # The citation locator deliberately differs from the source locator so a
    # response that fabricated citations from ``sources`` would be caught.
    citation = {"source_id": "source-1", "locator": CITATION_LOCATOR}
    return {
        "artifact_version": "1.0.0",
        "artifact_id": "causal-effect-test",
        "classification": "estimable_study",
        "question": {
            "treatment": treatment,
            "outcome": outcome,
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


def _write(path: Path, artifact: dict) -> Path:
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def test_valid_registered_artifact_is_read_without_estimation(tmp_path: Path) -> None:
    path = _write(tmp_path / "effect.json", _artifact())

    result = _reader(path).query(_request())

    assert result.status == "available"
    assert result.answer_numbers == {"effect": 1.5}
    assert result.method == "twfe_only"
    assert result.interval == [0.5, 2.5]
    # docs/causal-evidence-artifact.md: assumptions and caveats -> assumptions.
    assert result.assumptions == ["conditional exchangeability", "observational"]
    assert result.provenance[0].artifact_id == "causal-effect-test"
    assert result.question.treatment.definition == "line hardening completed"
    assert result.question.outcome.definition == "hours without service"
    assert result.sources[0].coverage == "test period"
    assert result.sample.n_total == 2
    assert result.diagnostics[0].status == "pass"
    assert result.citations == [
        CausalCitation(source_id="source-1", locator=CITATION_LOCATOR)
    ]
    # Every number in answer_numbers is traceable to an evidence row (spec 07).
    assert result.evidence_rows == [
        {
            "estimand": "ATE",
            "effect": 1.5,
            "interval": [0.5, 2.5],
            "confidence_level": 0.95,
            "evidence": [{"source_id": "source-1", "locator": CITATION_LOCATOR}],
        }
    ]

    evidence = evidence_from_artifact(_artifact())
    assert evidence.sample.n_total == 2
    assert evidence.citations[0].locator == CITATION_LOCATOR


def test_source_ref_does_not_leak_the_host_path(tmp_path: Path) -> None:
    path = _write(tmp_path / "effect.json", _artifact())

    result = _reader(path).query(_request())

    assert result.status == "available"
    assert result.provenance[0].source_ref == "effect.json"
    assert str(tmp_path) not in result.provenance[0].source_ref


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
    _write(path, fixture)

    fixture_result = _reader(path).query(_request())
    assert fixture_result.status == "unavailable"
    assert fixture_result.unavailable.code == "insufficient_evidence"
    assert "FIXTURE_NOT_ESTIMABLE" in fixture_result.unavailable.reason

    path.write_text("{not JSON", encoding="utf-8")
    malformed_result = _reader(path).query(_request())
    assert malformed_result.status == "unavailable"
    assert malformed_result.unavailable.code == "artifact_unavailable"

    structured_malformed = _artifact()
    structured_malformed.pop("sources")
    _write(path, structured_malformed)
    structured_result = _reader(path).query(_request())
    assert structured_result.status == "unavailable"
    assert structured_result.unavailable.code == "insufficient_evidence"


def test_non_utf8_artifact_bytes_are_unavailable_not_raised(tmp_path: Path) -> None:
    path = tmp_path / "effect.json"
    path.write_bytes(b"\xff\xfe" + json.dumps(_artifact()).encode("utf-8"))

    result = _reader(path).query(_request())

    assert result.status == "unavailable"
    assert result.unavailable.code == "artifact_unavailable"
    assert "UnicodeDecodeError" in result.unavailable.reason


def test_schema_invalid_but_semantically_estimable_artifact_is_malformed(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    artifact["unexpected_top_level_key"] = "not in the contract"
    path = _write(tmp_path / "effect.json", artifact)

    result = _reader(path).query(_request())

    assert result.status == "unavailable"
    assert result.unavailable.code == "insufficient_evidence"
    assert "malformed" in result.unavailable.reason


def _fifty_one_sources(artifact: dict) -> None:
    artifact["sources"] = [
        {**artifact["sources"][0], "source_id": f"source-{index}"}
        for index in range(1, 52)
    ]


def _over_long_source_name(artifact: dict) -> None:
    artifact["sources"][0]["name"] = "x" * 600


def _over_long_citation_locator(artifact: dict) -> None:
    artifact["citations"][0]["locator"] = "y" * 2049


@pytest.mark.parametrize(
    "mutate",
    [_fifty_one_sources, _over_long_source_name, _over_long_citation_locator],
    ids=["51-sources", "600-char-name", "2049-char-locator"],
)
def test_schema_gate_mirrors_the_wire_contract_bounds(tmp_path: Path, mutate) -> None:
    artifact = _artifact()
    mutate(artifact)
    path = _write(tmp_path / "effect.json", artifact)

    result = _reader(path).query(_request())

    assert result.status == "unavailable"
    assert result.unavailable.code == "insufficient_evidence"
    assert "malformed" in result.unavailable.reason


class _PermissiveValidator:
    """Stand-in for a schema that has drifted looser than the wire contract."""

    @staticmethod
    def is_valid(_document: object) -> bool:
        return True


def _missing_effect(artifact: dict) -> None:
    artifact["estimate"].pop("effect")


def _blank_artifact_id(artifact: dict) -> None:
    artifact["artifact_id"] = ""


@pytest.mark.parametrize(
    ("mutate", "cause"),
    [
        (_fifty_one_sources, "ValidationError"),
        (_over_long_source_name, "ValidationError"),
        (_missing_effect, "TypeError"),
        (_blank_artifact_id, "ValueError"),
    ],
    ids=["pydantic-too-long", "pydantic-string-too-long", "type-error", "value-error"],
)
def test_contract_skew_never_raises(tmp_path: Path, mutate, cause: str) -> None:
    artifact = _artifact()
    mutate(artifact)
    path = _write(tmp_path / "effect.json", artifact)
    reader = _reader(path)
    reader._validator = _PermissiveValidator()

    result = reader.query(_request())

    assert result.status == "unavailable"
    assert result.unavailable.code == "insufficient_evidence"
    assert cause in result.unavailable.reason
    assert not hasattr(result, "answer_numbers")


@pytest.mark.parametrize(
    "dangle",
    [
        lambda artifact: artifact["citations"][0].update(source_id="source-999"),
        lambda artifact: artifact["estimate"]["evidence"][0].update(
            source_id="source-999"
        ),
    ],
    ids=["citation", "estimate-evidence"],
)
def test_citations_must_resolve_to_a_declared_source(tmp_path: Path, dangle) -> None:
    artifact = _artifact()
    dangle(artifact)
    path = _write(tmp_path / "effect.json", artifact)

    result = _reader(path).query(_request())

    assert result.status == "unavailable"
    assert result.unavailable.code == "insufficient_evidence"
    assert "UNRESOLVED_CITATION" in result.unavailable.reason
    assert "source-999" not in result.unavailable.reason


@pytest.mark.parametrize(
    "tag",
    [
        lambda artifact: artifact["assumptions"].append("[UNVERIFIED] parallel trends"),
        lambda artifact: artifact["estimate"]["caveats"].append(
            "[UNVERIFIED: no placebo run] robust"
        ),
        lambda artifact: artifact["diagnostics"][0].update(
            evidence="[UNVERIFIED] balance table"
        ),
    ],
    ids=["assumption", "caveat", "diagnostic-evidence"],
)
def test_unverified_claims_are_not_served_as_evidence(tmp_path: Path, tag) -> None:
    artifact = _artifact()
    tag(artifact)
    path = _write(tmp_path / "effect.json", artifact)

    result = _reader(path).query(_request())

    assert result.status == "unavailable"
    assert result.unavailable.code == "insufficient_evidence"
    assert "[UNVERIFIED]" in result.unavailable.reason
    assert not hasattr(result, "assumptions")


@pytest.mark.parametrize(
    "remove",
    [
        lambda artifact: artifact.pop("citations"),
        lambda artifact: artifact.pop("sample"),
        lambda artifact: artifact.pop("assumptions"),
        lambda artifact: artifact["estimate"].pop("method"),
    ],
    ids=["citation", "sample", "assumption", "method"],
)
def test_available_response_evidence_fields_are_required(
    tmp_path: Path, remove
) -> None:
    artifact = _artifact()
    remove(artifact)
    path = _write(tmp_path / "effect.json", artifact)

    result = _reader(path).query(_request())

    assert result.status == "unavailable"
    assert result.unavailable.code == "insufficient_evidence"
    assert not hasattr(result, "answer_numbers")


def test_unregistered_selection_is_rejected_without_reading_a_path(
    tmp_path: Path,
) -> None:
    result = _reader(tmp_path / "does-not-exist.json").query(
        CausalQueryInput(kind="effect", treatment="firm_generation_100mw")
    )

    assert result.status == "unavailable"
    assert result.unavailable.code == "unsupported_request"


def test_public_tool_returns_unavailable_until_deployment_registers_artifacts() -> None:
    unconfigured = causal_query("effect", treatment="hardening_saidi")
    assert unconfigured.status == "unavailable"
    assert unconfigured.unavailable.code == "artifact_unavailable"
    assert "bindings" in unconfigured.unavailable.reason

    configure_causal_artifacts(())

    result = causal_query("effect", treatment="hardening_saidi")

    assert result.status == "unavailable"
    assert result.unavailable.code == "unsupported_request"


def test_public_tool_plumbs_its_arguments_to_the_registered_binding(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    # Distinct from every other fixture so a hard-coded assumptions list is caught.
    artifact["assumptions"] = ["parallel trends"]
    artifact["estimate"]["caveats"] = ["underpowered: n_treated < 15"]
    path = _write(tmp_path / "effect.json", artifact)
    configure_causal_artifacts(
        (RegisteredCausalArtifact(_request(), path, "observed"),)
    )

    result = causal_query("effect", treatment="hardening_saidi")
    assert result.status == "available"
    assert result.answer_numbers == {"effect": 1.5}
    assert result.assumptions == ["parallel trends", "underpowered: n_treated < 15"]
    assert result.provenance[0].source_kind == "observed"

    other_treatment = causal_query("effect", treatment="firm_generation_100mw")
    assert other_treatment.status == "unavailable"
    assert other_treatment.unavailable.code == "unsupported_request"

    other_scenario = causal_query(
        "effect", scenario_id="beryl_2024", treatment="hardening_saidi"
    )
    assert other_scenario.status == "unavailable"
    assert other_scenario.unavailable.code == "unsupported_request"


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
        (
            "UNRESOLVED_CITATION",
            lambda artifact: (
                artifact["citations"][0].update(source_id="source-999"),
                artifact.update(
                    availability={
                        "status": "unavailable",
                        "unavailable_codes": ["UNRESOLVED_CITATION"],
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
    _write(path, artifact)

    result = _reader(path).query(_request())

    assert result.status == "unavailable"
    assert result.unavailable.code == "insufficient_evidence"
    assert unavailable_code in result.unavailable.reason
    assert not hasattr(result, "answer_numbers")

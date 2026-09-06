"""Fail-closed validation for persisted causal evidence artifacts.

The JSON schema defines the durable artifact shape.  This module evaluates the
semantic prerequisites before a caller can use an artifact to expose a causal
claim.  It deliberately reports criteria rather than source rows, values, or
other potentially sensitive evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

FIXTURE_NOT_ESTIMABLE = "FIXTURE_NOT_ESTIMABLE"
MISSING_IDENTIFICATION = "MISSING_IDENTIFICATION"
MISSING_TREATMENT_DEFINITION = "MISSING_TREATMENT_DEFINITION"
MISSING_OUTCOME_DEFINITION = "MISSING_OUTCOME_DEFINITION"
MISSING_DATA_COVERAGE = "MISSING_DATA_COVERAGE"
MISSING_DIAGNOSTICS = "MISSING_DIAGNOSTICS"

INSUFFICIENCY_CODES = (
    FIXTURE_NOT_ESTIMABLE,
    MISSING_IDENTIFICATION,
    MISSING_TREATMENT_DEFINITION,
    MISSING_OUTCOME_DEFINITION,
    MISSING_DATA_COVERAGE,
    MISSING_DIAGNOSTICS,
)

SUPPORTED_ESTIMATION_METHODS = frozenset(
    {"backdoor.econml.dml.LinearDML", "twfe_only"}
)


@dataclass(frozen=True)
class PrerequisiteDiagnostic:
    """A safe, machine-readable reason an effect cannot be exposed."""

    code: str
    criterion: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """Result of evaluating whether an artifact may support an effect claim."""

    estimable: bool
    diagnostics: tuple[PrerequisiteDiagnostic, ...]

    @property
    def unavailable_codes(self) -> tuple[str, ...]:
        return tuple(diagnostic.code for diagnostic in self.diagnostics)


def validate_artifact(artifact: Mapping[str, Any]) -> ValidationResult:
    """Return every unmet causal-evidence prerequisite without exposing data.

    This is intentionally independent of JSON Schema validation: callers can
    receive actionable unavailable diagnostics even for a partially formed
    artifact.  An artifact is estimable only when every prerequisite is met,
    it declares itself available, and it carries an explicit estimate method.
    """

    if artifact.get("classification") == "interface_fixture":
        return _result(
            PrerequisiteDiagnostic(
                FIXTURE_NOT_ESTIMABLE,
                "classification",
                "Interface fixtures cannot support causal effect claims.",
            )
        )

    diagnostics: list[PrerequisiteDiagnostic] = []
    question = _mapping(artifact.get("question"))
    treatment = _mapping(question.get("treatment"))
    outcome = _mapping(question.get("outcome"))

    if not _labeled_variable(treatment):
        diagnostics.append(
            PrerequisiteDiagnostic(
                MISSING_TREATMENT_DEFINITION,
                "treatment",
                "A labeled treatment definition and provenance are required.",
            )
        )
    if not _labeled_variable(outcome):
        diagnostics.append(
            PrerequisiteDiagnostic(
                MISSING_OUTCOME_DEFINITION,
                "outcome",
                "A labeled outcome definition and provenance are required.",
            )
        )

    if not _identification_is_explicit(artifact):
        diagnostics.append(
            PrerequisiteDiagnostic(
                MISSING_IDENTIFICATION,
                "identification",
                "An explicit identification strategy and assumptions are required.",
            )
        )

    if not _has_covered_data(artifact, question, treatment, outcome):
        diagnostics.append(
            PrerequisiteDiagnostic(
                MISSING_DATA_COVERAGE,
                "data_coverage",
                "Population, sample, covariate, and source coverage are required.",
            )
        )

    if not _diagnostics_pass(artifact):
        diagnostics.append(
            PrerequisiteDiagnostic(
                MISSING_DIAGNOSTICS,
                "diagnostics",
                "Required diagnostics must be recorded with passing status.",
            )
        )

    estimate = _mapping(artifact.get("estimate"))
    if not diagnostics and not _explicit_method(estimate):
        diagnostics.append(
            PrerequisiteDiagnostic(
                MISSING_IDENTIFICATION,
                "method",
                "An estimable artifact requires an explicit estimation method.",
            )
        )

    if _mapping(artifact.get("availability")).get("status") != "available" and not diagnostics:
        diagnostics.append(
            PrerequisiteDiagnostic(
                MISSING_IDENTIFICATION,
                "availability",
                "Only an available artifact may expose a causal effect claim.",
            )
        )

    return _result(*diagnostics)


def _result(*diagnostics: PrerequisiteDiagnostic) -> ValidationResult:
    return ValidationResult(estimable=not diagnostics, diagnostics=diagnostics)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _labeled_variable(variable: Mapping[str, Any]) -> bool:
    return all(
        _nonempty(variable.get(field))
        for field in ("name", "definition", "unit_or_category", "source_id")
    )


def _identification_is_explicit(artifact: Mapping[str, Any]) -> bool:
    assumptions = artifact.get("assumptions")
    return isinstance(assumptions, list) and any(_nonempty(item) for item in assumptions)


def _has_covered_data(
    artifact: Mapping[str, Any],
    question: Mapping[str, Any],
    treatment: Mapping[str, Any],
    outcome: Mapping[str, Any],
) -> bool:
    population = _mapping(question.get("target_population"))
    sample = _mapping(artifact.get("sample"))
    sources = artifact.get("sources")
    covariates = artifact.get("covariates")
    source_records = [_mapping(item) for item in sources] if isinstance(sources, list) else []
    source_ids = {
        source.get("source_id")
        for source in source_records
        if isinstance(source.get("source_id"), str)
    }
    population_complete = all(
        _nonempty(population.get(field))
        for field in ("description", "geography", "time_window")
    )
    sample_complete = (
        _nonempty(sample.get("unit"))
        and _nonempty(sample.get("period"))
        and all(isinstance(sample.get(field), int) and sample[field] >= 0 for field in ("n_total", "n_treated", "n_control"))
        and sample.get("n_total", 0) > 0
        and sample.get("n_treated", 0) + sample.get("n_control", 0) <= sample.get("n_total", 0)
    )
    source_complete = bool(source_ids) and all(
        _nonempty(source.get(field))
        for source in source_records
        for field in ("source_id", "name", "version", "locator", "coverage")
    )
    variables_have_sources = (
        _labeled_variable(treatment)
        and _labeled_variable(outcome)
        and treatment.get("source_id") in source_ids
        and outcome.get("source_id") in source_ids
    )
    covariates_complete = isinstance(covariates, list) and all(
        _labeled_variable(_mapping(item)) and _mapping(item).get("source_id") in source_ids
        for item in covariates
    )
    return population_complete and sample_complete and source_complete and variables_have_sources and covariates_complete


def _diagnostics_pass(artifact: Mapping[str, Any]) -> bool:
    diagnostics = artifact.get("diagnostics")
    return isinstance(diagnostics, list) and bool(diagnostics) and all(
        _mapping(item).get("status") == "pass" and _nonempty(_mapping(item).get("name"))
        and _nonempty(_mapping(item).get("evidence"))
        for item in diagnostics
    )


def _explicit_method(estimate: Mapping[str, Any]) -> bool:
    return (
        estimate.get("method") in SUPPORTED_ESTIMATION_METHODS
        and _nonempty(estimate.get("estimand"))
    )

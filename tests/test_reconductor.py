"""Focused behavior checks for the 2WKG-188 parameter artifact."""

import pytest
from pydantic import ValidationError

from twin.reconductor import (
    ConductorParameters,
    Evidence,
    Quantity,
    ReconductorParameterArtifact,
    ScenarioLink,
)


def _conductor(*, name: str, material: str, size: int, rating: float):
    return ConductorParameters(
        name=name,
        material=material,
        size=Quantity(value=size, unit="kcmil"),
        thermal_rating=Quantity(value=rating, unit="MW"),
        nominal_voltage=Quantity(value=230, unit="kV"),
        evidence=Evidence(
            source="fixture conductor inventory",
            assumption="rating is the declared thermal rating, not a live DLR value",
        ),
    )


def _artifact() -> ReconductorParameterArtifact:
    return ReconductorParameterArtifact(
        line_id=44,
        scenario=ScenarioLink(
            scenario_id="uri_2021", baseline_run_id="uri_2021-s0-a1b2"
        ),
        baseline=_conductor(name="Drake", material="ACSR", size=795, rating=300),
        proposed=_conductor(name="ACCC Lisbon", material="ACCC", size=795, rating=540),
        changed_assumptions=(
            "replace the baseline conductor in the existing corridor",
            "retain the existing nominal voltage",
        ),
    )


def test_artifact_records_baseline_proposal_units_evidence_and_scenario_linkage():
    artifact = _artifact()

    assert artifact.scenario.scenario_id == "uri_2021"
    assert artifact.scenario.baseline_run_id == "uri_2021-s0-a1b2"
    assert artifact.baseline.thermal_rating.unit == "MW"
    assert artifact.proposed.size.unit == "kcmil"
    assert artifact.proposed.evidence.source == "fixture conductor inventory"
    assert artifact.proposed.evidence.assumption is not None
    assert artifact.validity_status == "valid"


def test_identical_input_produces_identical_canonical_artifact():
    assert _artifact().canonical_json() == _artifact().canonical_json()


def test_parameter_units_cannot_be_mislabeled():
    with pytest.raises(ValidationError, match="thermal rating must use MW"):
        ConductorParameters(
            name="Drake",
            material="ACSR",
            size=Quantity(value=795, unit="kcmil"),
            thermal_rating=Quantity(value=300, unit="kV"),
            nominal_voltage=Quantity(value=230, unit="kV"),
            evidence=Evidence(source="fixture conductor inventory"),
        )


def test_proposal_must_raise_rating_without_changing_voltage_class():
    baseline = _conductor(name="Drake", material="ACSR", size=795, rating=300)
    with pytest.raises(ValidationError, match="must exceed"):
        ReconductorParameterArtifact(
            line_id=44,
            scenario=ScenarioLink(scenario_id="uri_2021"),
            baseline=baseline,
            proposed=_conductor(name="ACSS", material="ACSS", size=795, rating=300),
            changed_assumptions=("replace conductor",),
        )

    with pytest.raises(ValidationError, match="retain the baseline"):
        ReconductorParameterArtifact(
            line_id=44,
            scenario=ScenarioLink(scenario_id="uri_2021"),
            baseline=baseline,
            proposed=ConductorParameters(
                name="ACSS",
                material="ACSS",
                size=Quantity(value=795, unit="kcmil"),
                thermal_rating=Quantity(value=540, unit="MW"),
                nominal_voltage=Quantity(value=345, unit="kV"),
                evidence=Evidence(source="fixture conductor inventory"),
            ),
            changed_assumptions=("replace conductor",),
        )

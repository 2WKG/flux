from twin.reconductor import (
    Rating,
    ReconductorArtifact,
    ReconductorStatus,
    ReconductorUnavailableReason,
    UnavailableReconductorArtifact,
    build_reconductor_artifact,
)


def _rating(mw: float, conductor: str = "ACSR") -> Rating:
    return Rating(mw=mw, conductor=conductor, source="fixture-v1")


def test_reconductoring_records_baseline_proposal_and_provenance():
    artifact = build_reconductor_artifact(
        scenario_id="summer-peak",
        baseline=_rating(100.0, "ACSR"),
        proposed=_rating(145.0, "ACSS"),
        source="engineering-estimate-v1",
        assumption="same voltage and ambient design point",
    )

    assert isinstance(artifact, ReconductorArtifact)
    assert artifact.intervention_type == "reconductor"
    assert artifact.status is ReconductorStatus.READY
    assert artifact.uplift_mw == 45.0
    assert artifact.baseline.conductor == "ACSR"
    assert artifact.proposed.conductor == "ACSS"
    assert artifact.baseline.unit == artifact.proposed.unit == "MW"


def test_reconductoring_can_never_be_labeled_dlr():
    artifact = build_reconductor_artifact(
        scenario_id="summer-peak",
        baseline=_rating(100.0),
        proposed=_rating(145.0, "ACSS"),
        source="fixture-v1",
        assumption="design rating",
    )

    assert artifact.intervention_type != "dlr"
    assert not hasattr(artifact, "weather")


def test_missing_or_invalid_prerequisites_return_explicit_unavailable():
    missing = build_reconductor_artifact(
        scenario_id="summer-peak",
        baseline=None,
        proposed=_rating(145.0, "ACSS"),
        source="fixture-v1",
        assumption="design rating",
    )
    unchanged = build_reconductor_artifact(
        scenario_id="summer-peak",
        baseline=_rating(145.0),
        proposed=_rating(145.0, "ACSS"),
        source="fixture-v1",
        assumption="design rating",
    )

    assert isinstance(missing, UnavailableReconductorArtifact)
    assert missing.status is ReconductorStatus.UNAVAILABLE
    assert missing.reason is ReconductorUnavailableReason.MISSING_BASELINE_RATING
    assert unchanged.reason is ReconductorUnavailableReason.NON_INCREASING_RATING

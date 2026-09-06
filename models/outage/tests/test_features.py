"""Behavioural checks for 2WKG-119 feature assembly.

The fixture is built so that any leak is visible in the statistics: training
values are 10 and 30 (mean 20, population std 10); the calibration and holdout
rows carry values that would move both the mean and the scale by orders of
magnitude if they were ever fitted on.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

import pytest

from models.outage.contracts import (
    Driver,
    FeatureStatus,
    ModelArtifact,
    Partition,
    SplitAssignment,
    SplitManifest,
    TrainedModelPrediction,
    UnavailablePrediction,
    WindowKey,
)
from models.outage.feature_status import (
    IMPUTED_SOURCE_VALUE,
    INCOMPATIBLE_SOURCE_UNIT,
    MISSING_SOURCE_FEATURE,
    NOT_IN_FITTED_FEATURE_SET,
    FeatureArtifact,
    FeatureAssemblyError,
    FeatureFitError,
    RawFeature,
    assemble_features,
    fit_standardizers,
    source_frame,
)
from models.outage.prediction_paths import UnavailableReason, trained_prediction
from models.outage.split import manifest_sha256
from models.outage.transforms import TRANSFORM_VERSION, feature_frame_sha256

FEATURE_SET_VERSION = "features-test-1"
NAMES = ("gust", "rain")


def _key(hour: int) -> WindowKey:
    return WindowKey(
        county_fips="48453",
        scenario_id="summer-peak",
        window_start=datetime(2024, 7, 1, hour, tzinfo=UTC),
    )


TRAIN_A, TRAIN_B, CALIBRATION_KEY, HOLDOUT_KEY = _key(0), _key(6), _key(12), _key(18)

SOURCE_ROWS = {
    TRAIN_A: {"gust": RawFeature(10.0, "m_s"), "rain": RawFeature(2.0, "mm")},
    TRAIN_B: {"gust": RawFeature(30.0, "m_s"), "rain": RawFeature(4.0, "mm")},
    # Outliers: pooling either of these into the fit is immediately visible.
    CALIBRATION_KEY: {
        "gust": RawFeature(1_000_000.0, "m_s"),
        "rain": RawFeature(999.0, "mm"),
    },
    HOLDOUT_KEY: {"gust": RawFeature(35.0, "m_s"), "rain": RawFeature(5.0, "mm")},
}


def _manifest(source_rows=SOURCE_ROWS, names=NAMES) -> SplitManifest:
    digest = feature_frame_sha256(source_frame(source_rows, names))
    manifest = SplitManifest(
        split_id="split-pending",
        seed=7,
        input_artifact_sha256=digest,
        assignments=(
            SplitAssignment(key=TRAIN_A, partition=Partition.TRAIN),
            SplitAssignment(key=TRAIN_B, partition=Partition.TRAIN),
            SplitAssignment(key=CALIBRATION_KEY, partition=Partition.CALIBRATION),
            SplitAssignment(key=HOLDOUT_KEY, partition=Partition.HOLDOUT),
        ),
    )
    return manifest.model_copy(
        update={"split_id": f"split-{manifest_sha256(manifest)[:16]}"}
    )


SPLIT = _manifest()
HASH = SPLIT.input_artifact_sha256


def _fit(source_rows=SOURCE_ROWS, split=SPLIT, names=NAMES):
    return fit_standardizers(
        source_rows=source_rows,
        split=split,
        feature_names=names,
        feature_set_version=FEATURE_SET_VERSION,
    )


def _assemble(standardizers, source_features, key=HOLDOUT_KEY, **overrides):
    kwargs = {
        "key": key,
        "source_features": source_features,
        "standardizers": standardizers,
        "feature_set_version": FEATURE_SET_VERSION,
        "source_input_sha256": HASH,
    }
    kwargs.update(overrides)
    return assemble_features(**kwargs)


# --- fit: train-only, hand-computed, reproducible ----------------------------


def test_fit_uses_only_train_rows_with_hand_computed_statistics():
    standardizers = _fit()

    gust = standardizers.transform_for("gust")
    rain = standardizers.transform_for("rain")
    # train gust: 10, 30 -> mean 20, population std 10; calib 1e6 / holdout 35 excluded
    assert (gust.mean, gust.scale) == (20.0, 10.0)
    # train rain: 2, 4 -> mean 3, population std 1; calib 999 / holdout 5 excluded
    assert (rain.mean, rain.scale) == (3.0, 1.0)
    assert standardizers.names == ("gust", "rain")
    assert standardizers.units == (("gust", "m_s"), ("rain", "mm"))
    assert standardizers.transforms.split_id == SPLIT.split_id
    assert standardizers.transforms.source_input_sha256 == HASH
    assert standardizers.transforms.feature_set_version == FEATURE_SET_VERSION


def test_fit_is_reproducible_as_bytes_across_row_and_name_order():
    first = _fit()
    second = _fit(
        source_rows=dict(reversed(tuple(SOURCE_ROWS.items()))),
        names=tuple(reversed(NAMES)),
    )

    assert first == second
    assert first.canonical_json() == second.canonical_json()
    assert first.artifact_sha256 == second.artifact_sha256
    assert (
        first.artifact_sha256
        == sha256(
            json.dumps(first.as_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def test_fit_rejects_a_population_that_does_not_match_the_manifest():
    # Same manifest, a training value changed after the manifest was frozen.
    tampered = dict(SOURCE_ROWS)
    tampered[TRAIN_A] = {"gust": RawFeature(11.0, "m_s"), "rain": RawFeature(2.0, "mm")}
    with pytest.raises(FeatureFitError, match="does not match"):
        _fit(source_rows=tampered)

    # Same values, a row the manifest does not know.
    extra = dict(SOURCE_ROWS)
    extra[_key(0).model_copy(update={"county_fips": "48001"})] = {
        "gust": RawFeature(1.0, "m_s"),
        "rain": RawFeature(1.0, "mm"),
    }
    with pytest.raises(FeatureFitError, match="does not match"):
        _fit(source_rows=extra)


def test_fit_rejects_conflicting_units_across_train_rows():
    mixed = dict(SOURCE_ROWS)
    mixed[TRAIN_B] = {"gust": RawFeature(30.0, "mph"), "rain": RawFeature(4.0, "mm")}
    with pytest.raises(FeatureFitError, match="conflicting units.*m_s.*mph"):
        _fit(source_rows=mixed, split=_manifest(mixed))


def test_fit_rejects_a_feature_with_no_training_value_and_a_split_without_train():
    absent = {key: {"gust": features["gust"]} for key, features in SOURCE_ROWS.items()}
    with pytest.raises(FeatureFitError, match="'rain' has no source values"):
        _fit(source_rows=absent, split=_manifest(absent))

    no_train = SPLIT.model_copy(
        update={
            "assignments": tuple(
                replace_partition(assignment, Partition.HOLDOUT)
                if assignment.partition is Partition.TRAIN
                else assignment
                for assignment in SPLIT.assignments
            )
        }
    )
    no_train = no_train.model_copy(
        update={"split_id": f"split-{manifest_sha256(no_train)[:16]}"}
    )
    with pytest.raises(FeatureFitError, match="no training rows"):
        _fit(split=no_train)


def replace_partition(assignment: SplitAssignment, partition: Partition):
    return SplitAssignment(key=assignment.key, partition=partition)


# --- assemble: standardization value, statuses, reasons ---------------------


def test_standardized_values_are_train_centred_and_scaled():
    artifact = _assemble(_fit(), SOURCE_ROWS[HOLDOUT_KEY])

    fields = dict(artifact.row.features)
    # (35 - 20) / 10 and (5 - 3) / 1, by hand.
    assert fields["gust"].value == 1.5
    assert fields["rain"].value == 2.0
    assert fields["gust"].status is FeatureStatus.PRESENT
    assert artifact.missing_reasons == ()
    assert artifact.row.missing == ()
    assert artifact.transform_version == TRANSFORM_VERSION

    negative = _assemble(
        _fit(), {"gust": RawFeature(5.0, "m_s"), "rain": RawFeature(1.0, "mm")}
    )
    assert dict(negative.row.features)["gust"].value == -1.5
    assert dict(negative.row.features)["rain"].value == -2.0


def test_partially_missing_features_preserve_status_and_reason():
    artifact = _assemble(_fit(), {"gust": RawFeature(30.0, "m_s")})

    fields = dict(artifact.row.features)
    assert fields["gust"].status is FeatureStatus.PRESENT
    assert fields["gust"].value == 1.0
    assert fields["rain"].status is FeatureStatus.MISSING_SOURCE
    assert fields["rain"].value is None
    assert artifact.missing_reasons == (("rain", MISSING_SOURCE_FEATURE),)
    assert artifact.row.missing == ("rain",)


def test_unsupported_input_is_explicit_not_silently_imputed():
    artifact = _assemble(
        _fit(),
        {
            "gust": RawFeature(
                None, "m_s", FeatureStatus.OUT_OF_COVERAGE, "no station"
            ),
            "rain": RawFeature(float("nan"), "mm"),
        },
    )

    fields = dict(artifact.row.features)
    assert fields["gust"].status is FeatureStatus.OUT_OF_COVERAGE
    assert fields["rain"].status is FeatureStatus.MISSING_SOURCE
    assert artifact.missing_reasons == (
        ("gust", "no station"),
        ("rain", "invalid_source_value"),
    )


def test_incompatible_unit_is_missing_source_not_a_converted_number():
    artifact = _assemble(
        _fit(), {"gust": RawFeature(35.0, "mph"), "rain": RawFeature(5.0, "mm")}
    )

    fields = dict(artifact.row.features)
    assert fields["gust"].status is FeatureStatus.MISSING_SOURCE
    assert fields["gust"].unit == "m_s"
    assert artifact.missing_reasons == (("gust", INCOMPATIBLE_SOURCE_UNIT),)


def test_upstream_imputed_source_keeps_its_status_and_is_standardized():
    artifact = _assemble(
        _fit(),
        {
            "gust": RawFeature(
                30.0, "m_s", FeatureStatus.IMPUTED, "station gap filled"
            ),
            "rain": RawFeature(5.0, "mm"),
        },
    )

    fields = dict(artifact.row.features)
    assert fields["gust"].status is FeatureStatus.IMPUTED
    assert fields["gust"].value == 1.0
    assert artifact.missing_reasons == (("gust", "station gap filled"),)
    assert artifact.row.missing == ("gust",)

    unlabelled = _assemble(
        _fit(),
        {
            "gust": RawFeature(30.0, "m_s", FeatureStatus.IMPUTED),
            "rain": RawFeature(5.0, "mm"),
        },
    )
    assert unlabelled.missing_reasons == (("gust", IMPUTED_SOURCE_VALUE),)


def test_source_feature_outside_the_fitted_set_is_named_not_dropped():
    artifact = _assemble(
        _fit(),
        {**SOURCE_ROWS[HOLDOUT_KEY], "extra": RawFeature(5.0, "mm")},
    )

    assert tuple(name for name, _ in artifact.row.features) == ("gust", "rain")
    assert artifact.missing_reasons == (("extra", NOT_IN_FITTED_FEATURE_SET),)


def test_assemble_rejects_a_version_or_source_hash_the_standardizers_were_not_fitted_under():
    standardizers = _fit()
    with pytest.raises(FeatureAssemblyError, match="feature_set_version"):
        _assemble(
            standardizers,
            SOURCE_ROWS[HOLDOUT_KEY],
            feature_set_version="totally-unrelated",
        )
    with pytest.raises(FeatureAssemblyError, match="input artifact hash"):
        _assemble(standardizers, SOURCE_ROWS[HOLDOUT_KEY], source_input_sha256="b" * 64)


# --- artifact bytes ------------------------------------------------------------

GOLDEN_ARTIFACT_SHA256 = (
    "87b9b2a5e63b9367fa085b053ad6135e9469157b565b813922413d4d8e123cb0"
)


def test_feature_artifact_bytes_are_identical_across_runs_and_input_order():
    forward = _assemble(_fit(), SOURCE_ROWS[HOLDOUT_KEY])
    reversed_inputs = _assemble(
        _fit(
            source_rows=dict(reversed(tuple(SOURCE_ROWS.items()))),
            names=tuple(reversed(NAMES)),
        ),
        dict(reversed(tuple(SOURCE_ROWS[HOLDOUT_KEY].items()))),
    )

    assert isinstance(forward, FeatureArtifact)
    assert forward.canonical_json() == reversed_inputs.canonical_json()
    assert forward.artifact_sha256 == reversed_inputs.artifact_sha256
    names = tuple(name for name, _ in forward.row.features)
    assert names == tuple(sorted(names))
    assert (
        forward.artifact_sha256
        == sha256(forward.canonical_json().encode("utf-8")).hexdigest()
    )
    assert forward.transform_sha256 == _fit().transforms.artifact_sha256
    assert forward.artifact_sha256 == GOLDEN_ARTIFACT_SHA256


def test_feature_artifact_digest_covers_the_standardized_values_and_provenance():
    base = _assemble(_fit(), SOURCE_ROWS[HOLDOUT_KEY])
    other_value = _assemble(
        _fit(), {"gust": RawFeature(36.0, "m_s"), "rain": RawFeature(5.0, "mm")}
    )
    assert base.artifact_sha256 != other_value.artifact_sha256

    retagged = replace(base, transform_version="0.0.0")
    assert retagged.artifact_sha256 != base.artifact_sha256
    rehashed = replace(base, transform_sha256="c" * 64)
    assert rehashed.artifact_sha256 != base.artifact_sha256
    reasoned = replace(base, missing_reasons=(("gust", "x"),))
    assert reasoned.artifact_sha256 != base.artifact_sha256


# --- consumer shape (2WKG-118 handshake) --------------------------------------


def _model() -> ModelArtifact:
    return ModelArtifact(
        artifact_sha256="d" * 64,
        model_version="lgbm-test",
        trained_at=datetime(2026, 9, 5, tzinfo=UTC),
        split_id=SPLIT.split_id,
        feature_set_version=FEATURE_SET_VERSION,
    )


def test_complete_row_is_scored_by_prediction_paths_with_standardized_values():
    seen: list[dict[str, float]] = []

    def scorer(values):
        seen.append(dict(values))
        return 0.25

    record = trained_prediction(
        features=_assemble(_fit(), SOURCE_ROWS[HOLDOUT_KEY]).row,
        artifact=_model(),
        scorer=scorer,
        customers_at_risk=10,
        driver=Driver.WIND,
    )

    assert isinstance(record.prediction, TrainedModelPrediction)
    assert record.prediction.p_out == 0.25
    assert seen == [{"gust": 1.5, "rain": 2.0}]


def test_partial_row_is_refused_by_prediction_paths_not_scored():
    def scorer(values):  # pragma: no cover - must not be reached
        raise AssertionError("a row with a missing feature must not be scored")

    record = trained_prediction(
        features=_assemble(_fit(), {"gust": RawFeature(35.0, "m_s")}).row,
        artifact=_model(),
        scorer=scorer,
        customers_at_risk=10,
        driver=Driver.WIND,
    )

    assert isinstance(record.prediction, UnavailablePrediction)
    assert record.prediction.reason == UnavailableReason.MISSING_PREDICTION_FEATURES

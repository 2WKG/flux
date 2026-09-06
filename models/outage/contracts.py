"""Versioned contracts for county outage inputs, features, splits and predictions.

2WKG-120. These types are the interface between data ingest, feature assembly
(2WKG-119), split assignment (2WKG-117), prediction (2WKG-118) and persistence
(2WKG-122). Field names and units are fixed here; downstream code must not
rename them.

The central design rule is that illegal states are unrepresentable rather than
merely rejected. A fixture placeholder is a different type from an observed
label, and an unavailable prediction has no probability field at all, so no
amount of careless construction can present one as the other.

Shared-contract alignment: `PredictionRecord` carries the six columns that
`docs/specs/00-overview.md` §2.2 pins for the `outage_predictions` table
(`scenario_id, county_fips, ts, p_out, customers_at_risk, driver`) plus the
provenance the persistence layer validates. Only the pinned six are written to
that table; the rest travel with the artifact.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "1.0.0"
"""Bump minor for additive optional fields, major for anything else."""

WINDOW_HOURS = 6
"""Prediction windows are 6 h, aligned to 00/06/12/18 UTC (spec 02)."""


class Frozen(BaseModel):
    """Immutable, strict base: unknown fields are an error, not a shrug."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

CountyFips = Annotated[
    str, Field(pattern=r"^\d{5}$", description="5-digit county FIPS")
]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class WindowKey(Frozen):
    """Identity for every row in this contract: who, which run, and when."""

    county_fips: CountyFips
    scenario_id: str = Field(min_length=1)
    window_start: datetime = Field(description="UTC, 6-h aligned, inclusive start")

    @model_validator(mode="after")
    def _utc_and_aligned(self) -> WindowKey:
        ts = self.window_start
        if ts.tzinfo is None or ts.utcoffset().total_seconds() != 0:
            raise ValueError("window_start must be timezone-aware UTC")
        if (ts.hour % WINDOW_HOURS, ts.minute, ts.second, ts.microsecond) != (
            0,
            0,
            0,
            0,
        ):
            raise ValueError(
                f"window_start must be aligned to {WINDOW_HOURS}h UTC boundaries"
            )
        return self


# --------------------------------------------------------------------------
# Source rows — an observed label and a fixture placeholder are distinct types
# --------------------------------------------------------------------------


class ObservedLabel(Frozen):
    """A real measurement. Requires provenance that a fixture cannot supply."""

    kind: Literal["observed"] = "observed"
    customers_out_max: int = Field(
        ge=0, description="max customers out in the window, count"
    )
    total_customers: int = Field(gt=0, description="denominator, count")
    source_dataset_id: str = Field(min_length=1, description="datasets/catalog.json id")
    source_file_sha256: Sha256
    retrieved_at: datetime

    @property
    def fraction_out(self) -> float:
        return min(self.customers_out_max / self.total_customers, 1.0)

    @model_validator(mode="after")
    def _not_more_out_than_exist(self) -> ObservedLabel:
        if self.customers_out_max > self.total_customers:
            raise ValueError("customers_out_max exceeds total_customers")
        return self


class FixtureLabel(Frozen):
    """A stand-in used before real data lands. Never a validated label.

    It deliberately has no source hash and no `fraction_out`, so it cannot be
    substituted for `ObservedLabel` anywhere a real measurement is required.
    """

    kind: Literal["fixture"] = "fixture"
    customers_out_max: int = Field(ge=0)
    total_customers: int = Field(gt=0)
    reason: str = Field(min_length=1, description="why a fixture stands here")


class UncoveredLabel(Frozen):
    """No EAGLE-I sample exists for this window, so it is not a zero-outage label."""

    kind: Literal["uncovered"] = "uncovered"
    reason: str = Field(
        min_length=1, description="why the source does not cover this window"
    )


Label = Annotated[
    ObservedLabel | FixtureLabel | UncoveredLabel, Field(discriminator="kind")
]


class CountyOutageRow(Frozen):
    """One county-window source row."""

    key: WindowKey
    label: Label

    @property
    def is_trainable(self) -> bool:
        """Only observed labels may train, calibrate or evaluate a model."""
        return self.label.kind == "observed"


# --------------------------------------------------------------------------
# Features — availability is explicit, never a silent NaN
# --------------------------------------------------------------------------


class FeatureStatus(StrEnum):
    PRESENT = "present"
    MISSING_SOURCE = "missing_source"
    OUT_OF_COVERAGE = "out_of_coverage"
    IMPUTED = "imputed"


class FeatureValue(Frozen):
    """A feature plus why it is what it is."""

    value: float | None = None
    status: FeatureStatus
    unit: str = Field(min_length=1, description='e.g. "m_s", "deg_c", "mm", "ratio"')

    @model_validator(mode="after")
    def _value_matches_status(self) -> FeatureValue:
        if (
            self.status in (FeatureStatus.PRESENT, FeatureStatus.IMPUTED)
            and self.value is None
        ):
            raise ValueError(f"status={self.status} requires a value")
        if (
            self.status in (FeatureStatus.MISSING_SOURCE, FeatureStatus.OUT_OF_COVERAGE)
            and self.value is not None
        ):
            raise ValueError(f"status={self.status} must not carry a value")
        return self


FeatureName = Annotated[str, Field(min_length=1)]
FeatureEntries = tuple[tuple[FeatureName, FeatureValue], ...]


class FeatureRow(Frozen):
    """Assembled features for one county-window."""

    key: WindowKey
    feature_set_version: str = Field(min_length=1)
    features: FeatureEntries = Field(min_length=1)
    source_input_sha256: Sha256 = Field(
        description="hash of the input artifact this was built from"
    )

    @model_validator(mode="after")
    def _feature_names_are_unique(self) -> FeatureRow:
        names = tuple(name for name, _ in self.features)
        if len(set(names)) != len(names):
            raise ValueError("features must not contain duplicate names")
        return self

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, feature in self.features
            if feature.status != FeatureStatus.PRESENT
        )


# --------------------------------------------------------------------------
# Split assignment (2WKG-117 produces these)
# --------------------------------------------------------------------------


class Partition(StrEnum):
    TRAIN = "train"
    CALIBRATION = "calibration"
    HOLDOUT = "holdout"
    EXCLUDED = "excluded"


class SplitAssignment(Frozen):
    key: WindowKey
    partition: Partition


class SplitManifest(Frozen):
    """The frozen split. Its id is what every downstream artifact cites."""

    split_id: str = Field(min_length=1)
    seed: int
    input_artifact_sha256: Sha256
    assignments: tuple[SplitAssignment, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _assignments_have_unique_keys(self) -> SplitManifest:
        if len({assignment.key for assignment in self.assignments}) != len(
            self.assignments
        ):
            raise ValueError("assignments must not contain duplicate WindowKey values")
        return self

    def counts(self) -> dict[Partition, int]:
        counts = Counter(assignment.partition for assignment in self.assignments)
        return {partition: counts[partition] for partition in Partition}


# --------------------------------------------------------------------------
# Model artifact + evaluation
# --------------------------------------------------------------------------


class ModelArtifact(Frozen):
    """Identity of a trained model. Evaluation is a separate, later fact."""

    artifact_sha256: Sha256
    model_version: str = Field(min_length=1)
    trained_at: datetime
    split_id: str = Field(min_length=1)
    feature_set_version: str = Field(min_length=1)


class EvaluationRef(Frozen):
    """Points at the held-out evaluation artifact (2WKG-121)."""

    evaluation_sha256: Sha256
    split_id: str
    calibration_method: str | None = Field(
        default=None,
        description="None means predictions are uncalibrated; say so in the UI",
    )


# --------------------------------------------------------------------------
# Predictions — three mutually exclusive shapes
# --------------------------------------------------------------------------


class Driver(StrEnum):
    ICE = "ice"
    WIND = "wind"
    HEAT = "heat"
    WILDFIRE = "wildfire"
    FLOOD = "flood"
    OTHER = "other"


Probability = Annotated[float, Field(ge=0.0, le=1.0)]


class TrainedModelPrediction(Frozen):
    """Requires its artifact. May only claim evaluation when one exists."""

    model_kind: Literal["lightgbm"] = "lightgbm"
    p_out: Probability
    customers_at_risk: int = Field(ge=0)
    driver: Driver
    artifact: ModelArtifact
    evaluation: EvaluationRef | None = None

    @property
    def is_evaluated(self) -> bool:
        return self.evaluation is not None

    @model_validator(mode="after")
    def _evaluation_matches_split(self) -> TrainedModelPrediction:
        if self.evaluation and self.evaluation.split_id != self.artifact.split_id:
            raise ValueError(
                "evaluation split_id does not match the model artifact's split_id"
            )
        return self


class HeuristicPrediction(Frozen):
    """A rule, labelled as one. Has no artifact and cannot cite an evaluation."""

    model_kind: Literal["heuristic"] = "heuristic"
    p_out: Probability
    customers_at_risk: int = Field(ge=0)
    driver: Driver
    rule_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)


class UnavailablePrediction(Frozen):
    """No prediction. Carries no probability field to fabricate."""

    model_kind: Literal["unavailable"] = "unavailable"
    reason: str = Field(min_length=1)


Prediction = Annotated[
    TrainedModelPrediction | HeuristicPrediction | UnavailablePrediction,
    Field(discriminator="model_kind"),
]


class OutagePredictionRow(Frozen):
    """The six pinned columns of the `outage_predictions` table."""

    scenario_id: str = Field(min_length=1)
    county_fips: CountyFips
    ts: datetime
    p_out: Probability
    customers_at_risk: int = Field(ge=0)
    driver: Driver


class LightGBMPredictionProvenance(Frozen):
    """Companion metadata for a persisted LightGBM prediction row."""

    model_kind: Literal["lightgbm"] = "lightgbm"
    model_version: str = Field(min_length=1)
    artifact_sha256: Sha256
    split_id: str = Field(min_length=1)
    feature_set_version: str = Field(min_length=1)
    evaluation_sha256: Sha256 | None = None


class HeuristicPredictionProvenance(Frozen):
    """Companion metadata for a persisted heuristic prediction row."""

    model_kind: Literal["heuristic"] = "heuristic"
    rule_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)


PredictionProvenance = Annotated[
    LightGBMPredictionProvenance | HeuristicPredictionProvenance,
    Field(discriminator="model_kind"),
]


class PredictionPersistence(Frozen):
    """A pinned table row and its companion provenance record, persisted together."""

    row: OutagePredictionRow
    provenance: PredictionProvenance


class PredictionRecord(Frozen):
    """What gets persisted and served."""

    key: WindowKey
    prediction: Prediction
    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION

    def to_persistence(self) -> PredictionPersistence | None:
        """Return the table row plus typed provenance, or None if unavailable.

        Unavailable predictions are deliberately not writable to this table:
        a row there means "the model produced a number".
        """
        p = self.prediction
        if p.model_kind == "unavailable":
            return None
        row = OutagePredictionRow(
            scenario_id=self.key.scenario_id,
            county_fips=self.key.county_fips,
            ts=self.key.window_start,
            p_out=p.p_out,
            customers_at_risk=p.customers_at_risk,
            driver=p.driver,
        )
        if p.model_kind == "lightgbm":
            provenance: PredictionProvenance = LightGBMPredictionProvenance(
                model_version=p.artifact.model_version,
                artifact_sha256=p.artifact.artifact_sha256,
                split_id=p.artifact.split_id,
                feature_set_version=p.artifact.feature_set_version,
                evaluation_sha256=p.evaluation.evaluation_sha256
                if p.evaluation
                else None,
            )
        else:
            provenance = HeuristicPredictionProvenance(
                rule_id=p.rule_id,
                rule_version=p.rule_version,
            )
        return PredictionPersistence(row=row, provenance=provenance)

    def to_outage_predictions_row(self) -> dict[str, object] | None:
        """The six pinned columns, preserving provenance through `to_persistence()`."""
        persisted = self.to_persistence()
        if persisted is None:
            return None
        return {
            "scenario_id": persisted.row.scenario_id,
            "county_fips": persisted.row.county_fips,
            "ts": persisted.row.ts,
            "p_out": persisted.row.p_out,
            "customers_at_risk": persisted.row.customers_at_risk,
            "driver": persisted.row.driver.value,
        }

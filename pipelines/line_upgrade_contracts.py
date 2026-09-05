"""Line-upgrade artifact fields, provenance and score semantics.

2WKG-107, covering its four atomized children:
  2WKG-179  identity, input hashes, provenance
  2WKG-180  congestion source classes and intervention type enumerations
  2WKG-181  score direction, tie-breaker, rounding, unavailable reasons
  2WKG-182  mapping onto the shared DuckDB schema

Consumed by 2WKG-108 (congestion classification), 2WKG-109 (reconductoring),
2WKG-110 (DLR), 2WKG-111 (`top_lines`) and 2WKG-112 (scoring + persistence).

It lives beside `pipelines/line_upgrade.py`, the module spec 08 makes the owner
of the ranking, rather than under `models/`, which holds trained-model code.

As with the outage contracts (2WKG-120), the rule is that illegal states are
unrepresentable. A proxy congestion figure is a different type from a measured
one and carries no market-provenance fields, so no line can imply measured grid
conditions when the input was simulated or assumed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# This is the record/score contract, rather than the DuckDB storage contract.
# Keep it importable by API and calculation-only consumers that do not install
# DuckDB, and bump it independently when the scoring semantics change.
CONTRACT_VERSION = "1.0.0"

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Usd = Annotated[float, Field(ge=0.0, description="US dollars")]
Mw = Annotated[float, Field(ge=0.0, description="megawatts")]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------
# 2WKG-180 — enumerations
# --------------------------------------------------------------------------


class CongestionSource(StrEnum):
    """How a congestion figure was obtained. Distinct, never interchangeable."""

    OBSERVED = "observed"  # market shadow prices actually published
    SIMULATED = "simulated"  # produced by our own twin run
    PROXY = "proxy"  # an assumed $/MWh applied to modelled overload
    UNATTRIBUTED = "unattributed"  # constraint could not be mapped to a line


class InterventionType(StrEnum):
    """DLR and reconductoring are alternatives, never combined into one figure."""

    DLR = "dlr"
    RECONDUCTOR = "reconductor"


class UnavailableReason(StrEnum):
    """Every unavailable outcome names why (2WKG-181)."""

    NO_RATING = "no_rating"  # line has no usable thermal rating
    NO_WEATHER = "no_weather"  # DLR needs wind/temperature it lacks
    NO_CONDUCTOR = "no_conductor"  # reconductor needs a conductor type
    NO_CONGESTION_INPUT = "no_congestion_input"
    UNMAPPED_CONSTRAINT = "unmapped_constraint"
    COST_UNKNOWN = "cost_unknown"


# --------------------------------------------------------------------------
# 2WKG-179 — identity and provenance
# --------------------------------------------------------------------------


class LineUpgradeProvenance(Frozen):
    """What produced a row, and from exactly which inputs."""

    ranking_version: str = Field(min_length=1)
    contract_version: str = CONTRACT_VERSION
    computed_at: datetime
    grid_input_sha256: Sha256 = Field(description="the case/topology artifact")
    weather_input_sha256: Sha256 | None = Field(
        default=None, description="required whenever a DLR figure is present"
    )
    cost_params_sha256: Sha256 = Field(description="refa_costs.yaml or equivalent")

    @model_validator(mode="after")
    def _utc(self) -> LineUpgradeProvenance:
        if (
            self.computed_at.tzinfo is None
            or self.computed_at.utcoffset().total_seconds() != 0
        ):
            raise ValueError("computed_at must be timezone-aware UTC")
        return self


class LineKey(Frozen):
    """Identity of one line-upgrade artifact within an analysis scenario.

    ``line_id`` identifies the synthetic source-case branch.  It is not by
    itself sufficient identity for a ranking artifact: the same branch can be
    ranked for a historical replay, forecast, or declared aggregate period.
    ``scenario_id`` is therefore required even when the congestion source is
    observed or a proxy.  It names the scope of the analysis; it does *not*
    claim that the result came from a Flux simulation.
    """

    line_id: int
    region: str = Field(min_length=1, description='balancing authority, e.g. "ERCOT"')
    scenario_id: str = Field(
        min_length=1,
        description="stable scenario or declared aggregate-period identifier",
    )


class StorageProvenance(Frozen):
    """The fixture provenance columns required by the shared DuckDB contract."""

    source_name: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    source_version: str | None = None
    source_retrieved_at: datetime | None = None
    fixture_batch_id: str = Field(min_length=1)


# --------------------------------------------------------------------------
# Congestion — measured, modelled and assumed are separate types
# --------------------------------------------------------------------------


class ObservedCongestion(Frozen):
    """Published market shadow prices. The only class that may claim measurement."""

    source: Literal[CongestionSource.OBSERVED] = CongestionSource.OBSERVED
    usd_per_year: Usd
    market: str = Field(min_length=1, description='e.g. "ERCOT SCED"')
    input_sha256: Sha256
    mapping_confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    mapping_method: Literal["exact", "fuzzy"]


class SimulatedCongestion(Frozen):
    """Derived from our own twin run. Cites the run, not a market."""

    source: Literal[CongestionSource.SIMULATED] = CongestionSource.SIMULATED
    usd_per_year: Usd
    scenario_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)


class ProxyCongestion(Frozen):
    """Modelled overload times an assumed price. States the assumption inline."""

    source: Literal[CongestionSource.PROXY] = CongestionSource.PROXY
    usd_per_year: Usd
    assumed_usd_per_mwh: Annotated[float, Field(gt=0.0)]
    assumption_note: str = Field(min_length=1)


class UnattributedCongestion(Frozen):
    """Constraint dollars exist but map to no line. Carries no per-line figure."""

    source: Literal[CongestionSource.UNATTRIBUTED] = CongestionSource.UNATTRIBUTED
    reason: UnavailableReason


Congestion = Annotated[
    ObservedCongestion | SimulatedCongestion | ProxyCongestion | UnattributedCongestion,
    Field(discriminator="source"),
]


# --------------------------------------------------------------------------
# Interventions — DLR and reconductoring cannot collide
# --------------------------------------------------------------------------


class DlrIntervention(Frozen):
    intervention: Literal[InterventionType.DLR] = InterventionType.DLR
    uplift_mw: Mw = Field(description="P50 uplift over static rating")
    hours_above_static: int = Field(ge=0, le=8784)
    cost_usd: Usd
    opex_usd_per_year: Usd = 0.0


class ReconductorIntervention(Frozen):
    intervention: Literal[InterventionType.RECONDUCTOR] = InterventionType.RECONDUCTOR
    uplift_mw: Mw
    cost_usd: Usd
    conductor_material: str = Field(min_length=1)
    conductor_kcmil: int | None = None


Intervention = Annotated[
    DlrIntervention | ReconductorIntervention, Field(discriminator="intervention")
]


# --------------------------------------------------------------------------
# 2WKG-181 — score semantics
# --------------------------------------------------------------------------

MW_PER_MUSD_DECIMALS = 3
"""Persisted rounding. Compare on the rounded value so ranking is reproducible."""


def mw_per_musd(uplift_mw: float, cost_usd: float) -> float | None:
    """Higher is better. None when cost is unknown or zero — never infinity."""
    if cost_usd <= 0.0:
        return None
    return round(uplift_mw / (cost_usd / 1e6), MW_PER_MUSD_DECIMALS)


class ScoredLine(Frozen):
    """A line with a usable score."""

    key: LineKey
    provenance: LineUpgradeProvenance
    congestion: Congestion
    best: Intervention
    alternative: Intervention | None = None
    static_rating_mw: Mw
    aar_rating_mw: Mw | None = None
    mw_per_musd: Annotated[float, Field(ge=0.0)]
    owner: str | None = None
    payback_yr: Annotated[float, Field(ge=0.0)] | None = None
    ferc_screen_pass: bool | None = Field(
        default=None,
        description="None means undeterminable (e.g. unattributed congestion), "
        "which is not the same as False",
    )
    spark_eligible: bool | None = None

    @model_validator(mode="after")
    def _consistency(self) -> ScoredLine:
        if (
            isinstance(self.congestion, SimulatedCongestion)
            and self.congestion.scenario_id != self.key.scenario_id
        ):
            raise ValueError(
                "simulated congestion scenario_id must match the scored line scenario_id"
            )
        if self.alternative and self.alternative.intervention == self.best.intervention:
            raise ValueError(
                "alternative must be a different intervention type than best"
            )
        expected = mw_per_musd(self.best.uplift_mw, self.best.cost_usd)
        if expected is None or abs(expected - self.mw_per_musd) > 1e-9:
            raise ValueError(
                "mw_per_musd must equal round(uplift / cost_musd, 3) of `best`"
            )
        if self.alternative is not None:
            alternative_score = mw_per_musd(
                self.alternative.uplift_mw, self.alternative.cost_usd
            )
            if alternative_score is not None and alternative_score > self.mw_per_musd:
                raise ValueError("best must be the higher-scoring intervention")
        if (
            any(
                isinstance(intervention, DlrIntervention)
                for intervention in (self.best, self.alternative)
                if intervention is not None
            )
            and self.provenance.weather_input_sha256 is None
        ):
            raise ValueError("a DLR figure requires weather_input_sha256 provenance")
        if (
            self.congestion.source is CongestionSource.UNATTRIBUTED
            and self.ferc_screen_pass is not None
        ):
            raise ValueError(
                "ferc_screen_pass must be None when congestion is unattributed"
            )
        return self

    def sort_key(self) -> tuple[float, float, int]:
        """Deterministic ranking: score desc, then cheaper, then line_id asc.

        Returned for ascending sort, so the score is negated.
        """
        return (-self.mw_per_musd, self.best.cost_usd, self.key.line_id)

    def _intervention(self, kind: InterventionType) -> Intervention | None:
        """Return an intervention by type, whether it won or was the alternative."""
        for intervention in (self.best, self.alternative):
            if intervention is not None and intervention.intervention is kind:
                return intervention
        return None

    def _congestion_method(self) -> str:
        """Map each source class to the canonical detail-table vocabulary."""
        if isinstance(self.congestion, ObservedCongestion):
            return self.congestion.mapping_method
        if isinstance(self.congestion, UnattributedCongestion):
            return "unmapped"
        # The shared schema has one non-market value for a twin result or an
        # assumed-price proxy; neither may claim an exact/fuzzy market mapping.
        return "twin_proxy"

    def to_score_row(self, storage: StorageProvenance) -> dict[str, object]:
        """Return a complete `line_upgrade_scores` row for `pipelines.db`."""
        dlr = self._intervention(InterventionType.DLR)
        reconductor = self._intervention(InterventionType.RECONDUCTOR)
        congestion_usd_yr = (
            None
            if isinstance(self.congestion, UnattributedCongestion)
            else self.congestion.usd_per_year
        )
        return {
            "line_id": self.key.line_id,
            "congestion_usd_yr": congestion_usd_yr,
            "dlr_uplift_mw": dlr.uplift_mw
            if isinstance(dlr, DlrIntervention)
            else None,
            "reconductor_uplift_mw": (
                reconductor.uplift_mw
                if isinstance(reconductor, ReconductorIntervention)
                else None
            ),
            "dlr_cost_usd": dlr.cost_usd if isinstance(dlr, DlrIntervention) else None,
            "reconductor_cost_usd": (
                reconductor.cost_usd
                if isinstance(reconductor, ReconductorIntervention)
                else None
            ),
            "mw_per_musd": self.mw_per_musd,
            "ferc_screen_pass": self.ferc_screen_pass,
            "spark_eligible": self.spark_eligible,
            **storage.model_dump(),
        }

    def to_detail_row(self, storage: StorageProvenance) -> dict[str, object]:
        """Return a complete `line_upgrade_detail` row for `pipelines.db`."""
        dlr = self._intervention(InterventionType.DLR)
        reconductor = self._intervention(InterventionType.RECONDUCTOR)
        return {
            "line_id": self.key.line_id,
            "owner": self.owner,
            "conductor_material": (
                reconductor.conductor_material
                if isinstance(reconductor, ReconductorIntervention)
                else None
            ),
            "conductor_kcmil": (
                reconductor.conductor_kcmil
                if isinstance(reconductor, ReconductorIntervention)
                else None
            ),
            "static_rating_mw": self.static_rating_mw,
            "aar_rating_mw": self.aar_rating_mw,
            "dlr_p50_mw": (
                self.static_rating_mw + dlr.uplift_mw
                if isinstance(dlr, DlrIntervention)
                else None
            ),
            "dlr_hours_above_static": (
                dlr.hours_above_static if isinstance(dlr, DlrIntervention) else None
            ),
            "best_tech": self.best.intervention.value,
            "payback_yr": self.payback_yr,
            "congestion_method": self._congestion_method(),
            "region": self.key.region,
            **storage.model_dump(),
        }


class UnavailableLine(Frozen):
    """No score. Has no `mw_per_musd` field to fabricate."""

    key: LineKey
    provenance: LineUpgradeProvenance
    reason: UnavailableReason


LineUpgradeRecord = ScoredLine | UnavailableLine


def rank(lines: list[ScoredLine]) -> list[ScoredLine]:
    """Total order, stable across runs (2WKG-181 tie-breaker)."""
    return sorted(lines, key=ScoredLine.sort_key)

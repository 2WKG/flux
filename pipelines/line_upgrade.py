"""Deterministic construction and serialization of line-upgrade rankings."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

import duckdb
import pandas as pd

from pipelines.db import replace_frame
from pipelines.line_upgrade_contracts import (
    Congestion,
    DlrIntervention,
    Intervention,
    LineKey,
    LineUpgradeProvenance,
    ScoredLine,
    StorageProvenance,
    UnavailableLine,
    UnavailableReason,
    mw_per_musd,
)

LineUpgradeResult = ScoredLine | UnavailableLine


def score_line(
    *,
    key: LineKey,
    provenance: LineUpgradeProvenance,
    congestion: Congestion | None,
    static_rating_mw: float | None,
    interventions: Iterable[Intervention],
    owner: str | None = None,
) -> LineUpgradeResult:
    """Select the best valid intervention, or return an explicit unavailable row.

    Intervention scores are rounded by the shared contract before comparison;
    this function never persists a partial record when provenance, a static
    rating, or a usable intervention is missing.
    """

    if congestion is None:
        return UnavailableLine(
            key=key, provenance=provenance, reason=UnavailableReason.NO_CONGESTION_INPUT
        )
    if static_rating_mw is None or static_rating_mw <= 0:
        return UnavailableLine(
            key=key, provenance=provenance, reason=UnavailableReason.NO_RATING
        )

    candidates: list[tuple[float, Intervention]] = []
    for intervention in interventions:
        if (
            isinstance(intervention, DlrIntervention)
            and provenance.weather_input_sha256 is None
        ):
            continue
        score = mw_per_musd(intervention.uplift_mw, intervention.cost_usd)
        if score is not None:
            candidates.append((score, intervention))
    if not candidates:
        reason = (
            UnavailableReason.NO_WEATHER
            if provenance.weather_input_sha256 is None
            else UnavailableReason.COST_UNKNOWN
        )
        return UnavailableLine(key=key, provenance=provenance, reason=reason)

    # Descending rounded score, then lower cost, then a stable intervention name.
    candidates.sort(
        key=lambda item: (-item[0], item[1].cost_usd, item[1].intervention.value)
    )
    best_score, best = candidates[0]
    alternative = next(
        (
            candidate
            for _, candidate in candidates[1:]
            if candidate.intervention != best.intervention
        ),
        None,
    )
    return ScoredLine(
        key=key,
        provenance=provenance,
        congestion=congestion,
        best=best,
        alternative=alternative,
        static_rating_mw=static_rating_mw,
        mw_per_musd=best_score,
        owner=owner,
    )


def rank_results(results: Iterable[LineUpgradeResult]) -> tuple[LineUpgradeResult, ...]:
    """Sort usable scores first, then unavailable records by stable line identity."""

    return tuple(
        sorted(
            results,
            key=lambda result: (
                1 if isinstance(result, UnavailableLine) else 0,
                result.key.line_id
                if isinstance(result, UnavailableLine)
                else result.sort_key(),
            ),
        )
    )


@dataclass(frozen=True)
class PersistedRanking:
    """Rows and canonical bytes for one immutable ranking artifact."""

    score_rows: tuple[dict[str, object], ...]
    detail_rows: tuple[dict[str, object], ...]
    unavailable: tuple[UnavailableLine, ...]

    def canonical_json(self) -> bytes:
        """Stable offline serialization used by reproducibility checks."""

        document = {
            "detail_rows": self.detail_rows,
            "score_rows": self.score_rows,
            "unavailable": [
                record.model_dump(mode="json") for record in self.unavailable
            ],
        }
        return json.dumps(
            document, sort_keys=True, separators=(",", ":"), default=str
        ).encode()


def persist_ranking(
    results: Iterable[LineUpgradeResult], storage: StorageProvenance
) -> PersistedRanking:
    """Materialize complete schema rows for scored results and retain unavailables."""

    score_rows: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []
    unavailable: list[UnavailableLine] = []
    for result in rank_results(results):
        if isinstance(result, UnavailableLine):
            unavailable.append(result)
            continue
        score_rows.append(result.to_score_row(storage))
        detail_rows.append(result.to_detail_row(storage))
    return PersistedRanking(tuple(score_rows), tuple(detail_rows), tuple(unavailable))


def write_ranking(
    con: duckdb.DuckDBPyConnection,
    ranking: PersistedRanking,
    storage: StorageProvenance,
) -> tuple[int, int]:
    """Replace the persisted score and detail artifacts with one ranking."""

    write_args = storage.model_dump()
    scores = replace_frame(
        con,
        "line_upgrade_scores",
        pd.DataFrame(ranking.score_rows),
        **write_args,
    )
    details = replace_frame(
        con,
        "line_upgrade_detail",
        pd.DataFrame(ranking.detail_rows),
        **write_args,
    )
    return scores, details

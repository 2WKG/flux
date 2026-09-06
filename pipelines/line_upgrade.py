"""Deterministic construction, ranking and persistence of line-upgrade records.

Ordering rules (2WKG-112, on top of the 2WKG-181 contract):

* Within one line, candidate interventions are ordered by rounded score
  (``mw_per_musd``) descending, then lower ``cost_usd``, then intervention
  type (``"dlr"`` < ``"reconductor"``), then higher ``uplift_mw``, then the
  canonical JSON form of the intervention. The last key makes the order total,
  so two candidates that tie on every meaningful field are still selected the
  same way regardless of input order.
* Across lines, scored records are ordered by the contract's ``rank()``:
  score descending, then cheaper, then ``line_id`` ascending. Unavailable
  records always sort after every scored record, by ``line_id`` then reason.
* A ranking is one analysis partition: exactly one ``scenario_id`` and one
  ``region``. Mixing them raises instead of interleaving.

A missing prerequisite produces a named :class:`UnavailableLine`; a non-finite
figure (``inf``) is treated as missing, never as the best score.
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Iterable
from dataclasses import dataclass

import duckdb

from pipelines.line_upgrade_contracts import (
    Congestion,
    DlrIntervention,
    Intervention,
    LineKey,
    LineUpgradeProvenance,
    LineUpgradeRecord,
    ScoredLine,
    StorageProvenance,
    UnavailableLine,
    UnavailableReason,
    mw_per_musd,
    rank,
)

LineUpgradeResult = LineUpgradeRecord
"""Alias kept for the name this module was introduced with."""

SCORE_TABLE = "line_upgrade_scores"
DETAIL_TABLE = "line_upgrade_detail"


def _candidate_key(item: tuple[float, Intervention]) -> tuple[object, ...]:
    score, intervention = item
    return (
        -score,
        intervention.cost_usd,
        intervention.intervention.value,
        -intervention.uplift_mw,
        json.dumps(intervention.model_dump(mode="json"), sort_keys=True),
    )


def score_line(
    *,
    key: LineKey,
    provenance: LineUpgradeProvenance,
    congestion: Congestion | None,
    static_rating_mw: float | None,
    interventions: Iterable[Intervention],
    owner: str | None = None,
) -> LineUpgradeRecord:
    """Select the best valid intervention, or return an explicit unavailable row.

    Prerequisite failures, in precedence order:

    * no congestion input -> ``NO_CONGESTION_INPUT``
    * no, zero, negative or non-finite static rating -> ``NO_RATING``
    * every DLR candidate dropped because ``provenance.weather_input_sha256``
      is absent and nothing else remains -> ``NO_WEATHER`` (a DLR candidate
      without weather provenance is skipped, so a reconductor candidate can
      still win)
    * a candidate dropped for a non-finite ``uplift_mw`` and nothing else
      remains -> ``NO_RATING``
    * otherwise no candidate with a usable (positive, finite) cost, including
      an empty intervention list -> ``COST_UNKNOWN``
    """

    if congestion is None:
        return UnavailableLine(
            key=key, provenance=provenance, reason=UnavailableReason.NO_CONGESTION_INPUT
        )
    if (
        static_rating_mw is None
        or not math.isfinite(static_rating_mw)
        or static_rating_mw <= 0
    ):
        return UnavailableLine(
            key=key, provenance=provenance, reason=UnavailableReason.NO_RATING
        )

    candidates: list[tuple[float, Intervention]] = []
    dropped_for_weather = False
    dropped_for_uplift = False
    for intervention in interventions:
        if (
            isinstance(intervention, DlrIntervention)
            and provenance.weather_input_sha256 is None
        ):
            dropped_for_weather = True
            continue
        if not math.isfinite(intervention.uplift_mw):
            dropped_for_uplift = True
            continue
        if not math.isfinite(intervention.cost_usd):
            continue
        score = mw_per_musd(intervention.uplift_mw, intervention.cost_usd)
        if score is not None:
            candidates.append((score, intervention))
    if not candidates:
        if dropped_for_weather:
            reason = UnavailableReason.NO_WEATHER
        elif dropped_for_uplift:
            reason = UnavailableReason.NO_RATING
        else:
            reason = UnavailableReason.COST_UNKNOWN
        return UnavailableLine(key=key, provenance=provenance, reason=reason)

    candidates.sort(key=_candidate_key)
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


def _require_one_partition(results: tuple[LineUpgradeRecord, ...]) -> None:
    scenario_ids = {result.key.scenario_id for result in results}
    regions = {result.key.region for result in results}
    if len(scenario_ids) > 1 or len(regions) > 1:
        raise ValueError(
            "a ranking covers exactly one scenario_id and one region; got "
            f"scenario_ids={sorted(scenario_ids)!r} regions={sorted(regions)!r}"
        )


def rank_results(results: Iterable[LineUpgradeRecord]) -> tuple[LineUpgradeRecord, ...]:
    """Rank one partition: contract-ranked scores first, then unavailables.

    Raises ``ValueError`` when the records span more than one ``scenario_id``
    or ``region`` (the same ``line_id`` can exist in both ERCOT and PJM).
    """

    materialized = tuple(results)
    _require_one_partition(materialized)
    scored = [result for result in materialized if isinstance(result, ScoredLine)]
    unavailable = sorted(
        (result for result in materialized if isinstance(result, UnavailableLine)),
        key=lambda result: (result.key.line_id, result.reason.value),
    )
    return (*rank(scored), *unavailable)


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
    results: Iterable[LineUpgradeRecord], storage: StorageProvenance
) -> PersistedRanking:
    """Materialize complete schema rows for scored results and retain unavailables.

    This builds the rows; :func:`write_ranking` puts them in DuckDB.
    """

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


def write_ranking(con: duckdb.DuckDBPyConnection, ranking: PersistedRanking) -> int:
    """Insert the ranking's rows into ``line_upgrade_scores`` / ``line_upgrade_detail``.

    The connection must already carry the ``pipelines.db`` contract
    (``pipelines.db.connect`` / ``ensure_schema``). Rows are inserted, never
    replaced: a ``(line_id, scenario_id)`` that already exists raises
    ``duckdb.ConstraintException`` from the table's primary key and the whole
    write is rolled back, so a partially written ranking never persists.
    Unavailable records have no table and are not written. Returns the number
    of scored lines written.
    """

    con.begin()
    try:
        for table, rows in (
            (SCORE_TABLE, ranking.score_rows),
            (DETAIL_TABLE, ranking.detail_rows),
        ):
            for row in rows:
                columns = ", ".join(row)
                placeholders = ", ".join("?" for _ in row)
                con.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                    list(row.values()),
                )
    except Exception:
        con.rollback()
        raise
    con.commit()
    return len(ranking.score_rows)


def main(argv: list[str] | None = None) -> int:
    """Spec 08's ``python -m pipelines.line_upgrade --region`` is not built yet.

    2WKG-112 ships ``score_line`` / ``rank_results`` / ``persist_ranking`` /
    ``write_ranking``. ``score_lines`` needs the inventory, congestion and
    uplift inputs from 2WKG-108/109/110, so the CLI refuses loudly rather than
    exiting 0 having done nothing.
    """

    args = sys.argv[1:] if argv is None else argv
    print(
        "pipelines.line_upgrade: score_lines/--region is not implemented yet "
        f"(args={args!r}); this module provides score_line, rank_results, "
        "persist_ranking and write_ranking only.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

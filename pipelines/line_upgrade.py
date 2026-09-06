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
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from pipelines.congestion import CongestionArtifactError, load_congestion_artifact
from pipelines.line_upgrade_contracts import (
    Congestion,
    DlrIntervention,
    Intervention,
    LineKey,
    LineUpgradeProvenance,
    LineUpgradeRecord,
    ScoredLine,
    StorageProvenance,
    UnattributedCongestion,
    UnavailableLine,
    UnavailableReason,
    mw_per_musd,
    rank,
)
from twin.dlr import Conductor, dlr_cost_usd, dlr_summary, hourly_ratings_mw
from twin.reconductor import ReconductorArtifact, build_reconductor_artifact

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
    if isinstance(congestion, UnattributedCongestion):
        return UnavailableLine(
            key=key, provenance=provenance, reason=UnavailableReason.UNMAPPED_CONSTRAINT
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


class LineUpgradeArtifactError(ValueError):
    """A line-upgrade input artifact is incomplete or contradicts its request."""


def _load_artifact(path: Path, *, scenario_id: str, region: str) -> dict[str, Any]:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LineUpgradeArtifactError(
            f"cannot read line-upgrade artifact {path}: {exc}"
        ) from exc
    if (
        not isinstance(artifact, dict)
        or artifact.get("format") != "flux-line-upgrade-v1"
    ):
        raise LineUpgradeArtifactError("artifact format must be 'flux-line-upgrade-v1'")
    if artifact.get("scenario_id") != scenario_id or artifact.get("region") != region:
        raise LineUpgradeArtifactError(
            "artifact scenario_id and region must match request"
        )
    if artifact.get("source_kind") not in {
        "fixture",
        "observed",
        "simulated",
        "heuristic",
    }:
        raise LineUpgradeArtifactError(
            "artifact source_kind must be explicit and supported"
        )
    if not isinstance(artifact.get("lines"), list):
        raise LineUpgradeArtifactError("artifact lines must be an array")
    return artifact


def _sha(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise LineUpgradeArtifactError(f"{field} must be a lowercase SHA-256")
    return value


def _artifact_rows(artifact: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for index, row in enumerate(artifact["lines"]):
        if (
            not isinstance(row, dict)
            or isinstance(row.get("line_id"), bool)
            or not isinstance(row.get("line_id"), int)
        ):
            raise LineUpgradeArtifactError(
                f"artifact lines[{index}].line_id must be an integer"
            )
        line_id = row["line_id"]
        if line_id in rows:
            raise LineUpgradeArtifactError(f"artifact repeats line_id {line_id}")
        rows[line_id] = row
    return rows


def _interventions(
    *,
    key: LineKey,
    static_rating_mw: float | None,
    base_kv: float,
    length_km: float,
    artifact_row: dict[str, Any],
    provenance: LineUpgradeProvenance,
) -> tuple[Intervention, ...]:
    """Build only interventions whose qualified inputs are explicitly supplied."""
    interventions: list[Intervention] = []
    dlr = artifact_row.get("dlr")
    if isinstance(dlr, dict):
        weather = dlr.get("weather")
        conductor = dlr.get("conductor")
        if (
            isinstance(weather, list)
            and isinstance(conductor, dict)
            and static_rating_mw is not None
        ):
            try:
                ratings = hourly_ratings_mw(
                    str(key.line_id),
                    Conductor(**conductor),
                    pd.DataFrame(weather),
                    base_kv,
                    static_rating_mw,
                )
                summary = dlr_summary(ratings)
                if summary.get("status") == "ok":
                    interventions.append(
                        DlrIntervention(
                            uplift_mw=summary["dlr_uplift_mw"],
                            hours_above_static=summary["hours_above_static"],
                            cost_usd=dlr_cost_usd(length_km),
                        )
                    )
            except (TypeError, ValueError):
                pass
    reconductor = artifact_row.get("reconductor")
    if isinstance(reconductor, dict):
        result = build_reconductor_artifact(
            key=key,
            scenario_id=key.scenario_id,
            rate_a_mw=static_rating_mw,
            material=reconductor.get("material"),
            kcmil=reconductor.get("kcmil"),
            length_km=length_km,
            base_kv=base_kv,
            costs=reconductor.get("costs", {}),
        )
        if isinstance(result, ReconductorArtifact):
            interventions.append(result.intervention)
    return tuple(interventions)


def score_lines(
    *,
    db_path: Path,
    artifact_path: Path,
    congestion_path: Path,
    region: str,
    scenario_id: str,
    write: bool = True,
) -> PersistedRanking:
    """Score every selected inventory line from explicit qualified artifacts.

    Missing per-line inputs intentionally yield unavailable records.  The
    returned artifact retains those records even though DuckDB has no score row
    for them, so callers can report coverage instead of implying completeness.
    """
    artifact = _load_artifact(artifact_path, scenario_id=scenario_id, region=region)
    rows = _artifact_rows(artifact)
    try:
        congestion = load_congestion_artifact(congestion_path, scenario_id=scenario_id)
    except CongestionArtifactError as exc:
        raise LineUpgradeArtifactError(str(exc)) from exc
    provenance = LineUpgradeProvenance(
        ranking_version=artifact.get("ranking_version"),
        computed_at=artifact.get("computed_at"),
        grid_input_sha256=_sha(artifact.get("grid_input_sha256"), "grid_input_sha256"),
        weather_input_sha256=_sha(
            artifact.get("weather_input_sha256"), "weather_input_sha256"
        )
        if artifact.get("weather_input_sha256") is not None
        else None,
        cost_params_sha256=_sha(
            artifact.get("cost_params_sha256"), "cost_params_sha256"
        ),
    )
    storage = StorageProvenance(
        source_name=artifact.get("source_name"),
        source_ref=artifact.get("source_ref"),
        source_version=artifact.get("source_version"),
        fixture_batch_id=artifact.get("fixture_batch_id"),
        source_kind=artifact["source_kind"],
    )
    con = duckdb.connect(str(db_path), read_only=not write)
    try:
        inventory = con.execute(
            """SELECT l.line_id, l.base_kv, l.rate_a_mw, l.length_km
               FROM lines AS l JOIN buses AS b ON b.bus_id = l.from_bus
               WHERE b.ba_code = ? ORDER BY l.line_id""",
            [region],
        ).fetchall()
        if not inventory:
            raise LineUpgradeArtifactError(f"no inventory lines for region {region!r}")
        records: list[LineUpgradeRecord] = []
        for line_id, base_kv, rating, length_km in inventory:
            key = LineKey(line_id=line_id, region=region, scenario_id=scenario_id)
            row = rows.get(line_id, {})
            records.append(
                score_line(
                    key=key,
                    provenance=provenance,
                    congestion=congestion.get(line_id),
                    static_rating_mw=rating,
                    interventions=_interventions(
                        key=key,
                        static_rating_mw=rating,
                        base_kv=base_kv,
                        length_km=length_km,
                        artifact_row=row,
                        provenance=provenance,
                    ),
                    owner=row.get("owner")
                    if isinstance(row.get("owner"), str)
                    else None,
                )
            )
        ranking = persist_ranking(records, storage)
        if write:
            write_ranking(con, ranking)
        return ranking
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    """Build a ranking only from explicit DB, line, and congestion artifacts."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--congestion", type=Path, required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--scenario-id", required=True)
    args = parser.parse_args(argv)
    try:
        ranking = score_lines(
            db_path=args.db,
            artifact_path=args.artifact,
            congestion_path=args.congestion,
            region=args.region,
            scenario_id=args.scenario_id,
        )
    except (LineUpgradeArtifactError, duckdb.Error, ValueError) as exc:
        print(f"pipelines.line_upgrade: unavailable: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "scored": len(ranking.score_rows),
                "unavailable": len(ranking.unavailable),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

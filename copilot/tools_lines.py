"""Bounded, read-only access to one persisted line-ranking partition."""

from __future__ import annotations

from pathlib import Path

import duckdb

from copilot.config import Settings
from copilot.tools.schemas import (
    ArtifactRef,
    LinesData,
    LineSummary,
    TopLinesInput,
    UnavailableOutput,
    unavailable_output,
)


class TopLinesReader:
    """Read one unambiguous `(region, scenario_id)` ranking without mutating DuckDB."""

    def __init__(self, database_path: Path | str) -> None:
        self._database_path = Path(database_path)

    def top_lines(
        self, region: str, tech: str, n: int = 10
    ) -> LinesData | UnavailableOutput:
        try:
            request = TopLinesInput(region=region, tech=tech, n=n)
        except ValueError:
            return unavailable_output(
                "unsupported_request", "top_lines filters are invalid"
            )
        region, tech, n = request.region, request.tech, request.n
        if not self._database_path.is_file():
            return unavailable_output(
                "artifact_unavailable", "line-ranking database is unavailable"
            )
        try:
            with duckdb.connect(str(self._database_path), read_only=True) as con:
                partitions = con.execute(
                    """SELECT DISTINCT s.scenario_id, s.ranking_version, s.computed_at,
                              s.source_name, s.source_ref, s.source_kind
                       FROM line_upgrade_scores AS s
                       JOIN line_upgrade_detail AS d USING (line_id, scenario_id)
                       WHERE d.region = ? AND s.mw_per_musd IS NOT NULL
                       ORDER BY s.scenario_id, s.ranking_version, s.computed_at""",
                    [region],
                ).fetchall()
                if not partitions:
                    return unavailable_output(
                        "artifact_unavailable",
                        "no line-ranking artifact exists for the requested region",
                    )
                if len(partitions) != 1:
                    return unavailable_output(
                        "insufficient_evidence",
                        "multiple line-ranking scenario artifacts match the requested region",
                    )
                (
                    scenario_id,
                    ranking_version,
                    computed_at,
                    source_name,
                    source_ref,
                    artifact_source_kind,
                ) = partitions[0]
                where_tech = "" if tech == "any" else "AND d.best_tech = ?"
                params: list[object] = [region, scenario_id]
                if tech != "any":
                    params.append(tech)
                params.append(n)
                rows = con.execute(
                    f"""SELECT s.line_id, s.congestion_usd_yr, s.dlr_uplift_mw,
                               s.reconductor_uplift_mw, s.dlr_cost_usd, s.reconductor_cost_usd,
                               s.mw_per_musd, s.ferc_screen_pass, s.spark_eligible,
                               s.simulation_run_id,
                               d.best_tech, d.congestion_method, d.region,
                               line.from_bus, line.to_bus, line.base_kv
                        FROM line_upgrade_scores AS s
                        JOIN line_upgrade_detail AS d USING (line_id, scenario_id)
                        JOIN lines AS line ON line.line_id = s.line_id
                        WHERE d.region = ? AND s.scenario_id = ? {where_tech}
                        ORDER BY s.mw_per_musd DESC, CASE WHEN d.best_tech = 'dlr' THEN s.dlr_cost_usd ELSE s.reconductor_cost_usd END ASC, s.line_id ASC
                        LIMIT ?""",
                    params,
                ).fetchall()
        except duckdb.Error:
            return unavailable_output(
                "artifact_unavailable", "line-ranking artifact cannot be read"
            )
        artifact_id = f"line-upgrade:{scenario_id}:{ranking_version}"
        source_class = {"exact": "observed", "fuzzy": "observed", "twin_proxy": "proxy"}
        lines = []
        for row in rows:
            (
                line_id,
                congestion,
                dlr_uplift,
                recon_uplift,
                dlr_cost,
                recon_cost,
                score,
                ferc,
                spark,
                run_id,
                best,
                method,
                _row_region,
                from_bus,
                to_bus,
                kv,
            ) = row
            uplift, cost = (
                (dlr_uplift, dlr_cost) if best == "dlr" else (recon_uplift, recon_cost)
            )
            if best not in {"dlr", "reconductor"} or (
                not run_id and method not in source_class
            ):
                return unavailable_output(
                    "insufficient_evidence",
                    "line-ranking artifact has unsupported source metadata",
                )
            kind = "simulated" if run_id else source_class[method]
            lines.append(
                LineSummary(
                    line_id=str(line_id),
                    scenario_id=scenario_id,
                    artifact_id=artifact_id,
                    source_class=kind,
                    intervention_type=best,
                    status="available",
                    from_bus=str(from_bus),
                    to_bus=str(to_bus),
                    kv=kv,
                    congestion_usd_yr=congestion or 0.0,
                    uplift_mw=uplift,
                    cost_usd=cost,
                    mw_per_musd=score,
                    ferc_screen_pass=bool(ferc),
                    spark_eligible=bool(spark),
                )
            )
        if artifact_source_kind is None:
            return unavailable_output(
                "insufficient_evidence",
                "line-ranking artifact has unsupported provenance",
            )
        provenance = [
            ArtifactRef(
                artifact_id=artifact_id,
                artifact_version=str(computed_at),
                source_kind=artifact_source_kind,
                source_ref=str(source_ref or source_name),
            )
        ]
        return LinesData(
            status="available",
            provenance=provenance,
            region=region,
            scenario_id=scenario_id,
            artifact_id=artifact_id,
            tech=tech,
            lines=lines,
        )


def top_lines(region: str, tech: str, n: int = 10) -> LinesData | UnavailableOutput:
    """Read the frozen model-facing signature from the configured DuckDB artifact."""
    return TopLinesReader(Settings().duckdb_path).top_lines(region, tech, n)

"""Concrete, bounded handlers for Flux's frozen non-interactive tool contract.

The dispatcher owns provider-loop validation.  This module owns the deployment
binding from the nine historical tool names to local readers and executors.  A
missing artifact or an executor that has not been registered is returned as the
normal typed unavailable result; handlers never infer results from the user's
question or make a network request.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import duckdb
from pydantic import BaseModel, ValidationError

from copilot.retrieval.search import SparseIndex, retrieve
from copilot.tools.causal_query import CausalArtifactReader
from copilot.tools.schemas import (
    ArtifactRef,
    CascadeData,
    CausalQueryInput,
    CiteData,
    CiteInput,
    CompareInterventionsInput,
    CriticalElementsData,
    InterventionsData,
    PredictOutageData,
    PredictOutageInput,
    RunCascadeInput,
    ScoreSiteInput,
    SiteScoreData,
    SqlInput,
    TopCriticalElementsInput,
    TopLinesInput,
    UnavailableOutput,
    unavailable_output,
)
from copilot.tools.sql import MinnesotaSqlExecutor
from copilot.tools_lines import TopLinesReader

ToolHandler = Callable[
    [BaseModel, Mapping[str, object]], Awaitable[Mapping[str, object]]
]
"""Structural copy of the dispatcher handler signature, kept import-free."""

ResultExecutor = Callable[
    [BaseModel], Mapping[str, object] | Awaitable[Mapping[str, object]]
]


@dataclass(frozen=True)
class NonInteractiveToolServices:
    """Local capabilities a deployment deliberately makes available to tools.

    ``database_path`` is the one shared artifact dependency.  The four callback
    slots cover stateful compute/persisted-score owners whose exact runner is a
    deployment decision.  They receive already-validated Pydantic inputs and
    must return one of the frozen tool output shapes.
    """

    database_path: Path | str
    sql_executor: MinnesotaSqlExecutor | None = None
    retrieval_index: SparseIndex | None = None
    causal_reader: CausalArtifactReader | None = None
    cascade_executor: ResultExecutor | None = None
    site_score_executor: ResultExecutor | None = None
    comparison_reader: ResultExecutor | None = None
    critical_elements_reader: ResultExecutor | None = None

    @property
    def path(self) -> Path:
        return Path(self.database_path)


def _unavailable(code: str, reason: str) -> dict[str, object]:
    return unavailable_output(code, reason).model_dump(mode="json")  # type: ignore[arg-type]


async def _call(executor: ResultExecutor, payload: BaseModel) -> Mapping[str, object]:
    """Invoke a local deployment callback without treating sync work as a provider call."""

    value = executor(payload)
    if inspect.isawaitable(value):
        value = await value
    if not isinstance(value, Mapping):
        raise TypeError("tool executor returned a non-mapping result")
    return value


def _as_output(
    model: type[BaseModel], value: Mapping[str, object]
) -> dict[str, object]:
    """Validate a concrete result at the handler boundary before dispatcher use."""

    if value.get("status") == "unavailable":
        return UnavailableOutput.model_validate(value).model_dump(mode="json")
    return model.model_validate(value).model_dump(mode="json")


async def _executor_output(
    executor: ResultExecutor,
    payload: BaseModel,
    output_model: type[BaseModel],
    capability: str,
) -> dict[str, object]:
    """Return a callback result only when it fits the registered wire model.

    Executor registration is deployment configuration.  A stale callback or a
    malformed result must therefore be an explicit unavailable tool result,
    never an uncaught provider-loop failure or a partially trusted mapping.
    """

    try:
        return _as_output(output_model, await _call(executor, payload))
    except (TypeError, ValidationError):
        return _unavailable(
            "invalid_prerequisite",
            f"the local {capability} executor did not return a contract-valid result",
        )


def _artifact(kind: str, version: str, source_ref: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=kind,
        artifact_version=version,
        source_kind="observed",
        source_ref=source_ref,
    )


def _timestamp(value: object) -> str:
    if not isinstance(value, datetime):
        raise TypeError("persisted prediction timestamp is invalid")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _predict_outage(path: Path, payload: PredictOutageInput) -> dict[str, object]:
    """Read qualified persisted predictions; never recompute a forecast here."""

    if not path.is_file():
        return _unavailable(
            "artifact_unavailable", "outage prediction database is unavailable"
        )
    try:
        with duckdb.connect(str(path), read_only=True) as connection:
            rows = connection.execute(
                """SELECT p.ts, p.p_out, p.customers_at_risk, p.driver,
                          p.source_ref, p.source_version, c.name
                     FROM outage_predictions AS p
                     JOIN counties AS c ON c.county_fips = p.county_fips
                     JOIN prediction_provenance AS v
                       ON (v.scenario_id, v.county_fips, v.ts)
                        = (p.scenario_id, p.county_fips, p.ts)
                     JOIN evaluation_artifacts AS e
                       ON e.evaluation_sha256 = v.evaluation_sha256
                    WHERE p.scenario_id = ? AND p.county_fips = ?
                      AND e.qualified = TRUE
                    ORDER BY p.ts ASC LIMIT ?""",
                [payload.scenario_id, payload.county_fips, payload.horizon_h],
            ).fetchall()
    except duckdb.Error:
        return _unavailable(
            "artifact_unavailable",
            "qualified outage-prediction artifacts cannot be read",
        )
    if not rows:
        return _unavailable(
            "insufficient_evidence",
            "no qualified outage prediction matches this county and scenario",
        )
    try:
        points = [
            {
                "ts": _timestamp(row[0]),
                "p_out": float(row[1]),
                "customers_at_risk": int(row[2]),
            }
            for row in rows
        ]
        peak_index = max(
            range(len(points)),
            key=lambda index: (points[index]["p_out"], points[index]["ts"]),
        )
        peak = points[peak_index]
        driver, source_ref, source_version, county_name = rows[peak_index][3:]
        if not all(
            isinstance(item, str) and item
            for item in (driver, source_ref, source_version, county_name)
        ):
            raise ValueError("persisted prediction evidence is incomplete")
        return PredictOutageData(
            status="available",
            provenance=[_artifact("outage_predictions", source_version, source_ref)],
            county_fips=payload.county_fips,
            county_name=county_name,
            scenario_id=payload.scenario_id,
            horizon_h=payload.horizon_h,
            peak_p_out=float(peak["p_out"]),
            peak_ts=cast(str, peak["ts"]),
            customers_at_risk=int(peak["customers_at_risk"]),
            driver=driver,
            series=_downsample(points, max_points=24),
        ).model_dump(mode="json")
    except (KeyError, TypeError, ValidationError, ValueError):
        return _unavailable(
            "artifact_unavailable", "prediction artifact does not fit the tool contract"
        )


def _downsample(
    points: list[dict[str, object]], *, max_points: int
) -> list[dict[str, object]]:
    """Keep chronological endpoints while reducing a persisted horizon to its cap."""

    if len(points) <= max_points:
        return points
    indices = [
        round(index * (len(points) - 1) / (max_points - 1))
        for index in range(max_points)
    ]
    return [points[index] for index in indices]


def _persisted_cascade(path: Path, payload: RunCascadeInput) -> dict[str, object]:
    """Read an exact persisted result; this handler never reruns a cascade implicitly."""
    if not path.is_file():
        return _unavailable("artifact_unavailable", "cascade database is unavailable")
    try:
        with duckdb.connect(str(path), read_only=True) as connection:
            row = connection.execute(
                """SELECT run_id, tripped_element_ids_json, lost_load_mw,
                          counties_dark_json, critical_loads_lost_json,
                          source_ref, source_version
                     FROM cascade_runs
                    WHERE scenario_id = ? AND hour = ?
                    ORDER BY run_id ASC LIMIT 1""",
                [payload.scenario_id, payload.hour],
            ).fetchone()
    except duckdb.Error:
        return _unavailable("artifact_unavailable", "cascade artifact cannot be read")
    if row is None:
        return _unavailable(
            "insufficient_evidence",
            "cascade artifact has no result for the requested hour",
        )
    try:
        import json

        (
            run_id,
            tripped_json,
            lost_load,
            counties_json,
            critical_json,
            source_ref,
            source_version,
        ) = row
        tripped = (
            json.loads(tripped_json) if isinstance(tripped_json, str) else tripped_json
        )
        counties = (
            json.loads(counties_json)
            if isinstance(counties_json, str)
            else counties_json
        )
        critical = (
            json.loads(critical_json)
            if isinstance(critical_json, str)
            else critical_json
        )
        if (
            not isinstance(tripped, list)
            or not isinstance(counties, list)
            or not isinstance(critical, list)
        ):
            raise TypeError("persisted cascade values must be JSON arrays")
        observed = {
            item.get("element_id") for item in tripped if isinstance(item, Mapping)
        }
        if not set(payload.element_ids) <= observed:
            return _unavailable(
                "insufficient_evidence",
                "no persisted cascade result matches the requested elements",
            )
        if (
            not isinstance(source_ref, str)
            or not source_ref
            or not isinstance(source_version, str)
            or not source_version
        ):
            raise ValueError
        critical_loads = [
            {
                "id": item["cl_id"],
                "name": item["name"],
                "kind": item["kind"],
                "hour_lost": payload.hour,
            }
            for item in critical
            if isinstance(item, Mapping)
        ]
        if len(critical_loads) != len(critical):
            raise ValueError
        return CascadeData(
            status="available",
            provenance=[
                ArtifactRef(
                    artifact_id=f"cascade:{run_id}",
                    artifact_version=source_version,
                    source_kind="simulated",
                    source_ref=source_ref,
                )
            ],
            run_id=cast(str, run_id),
            scenario_id=payload.scenario_id,
            hour=payload.hour,
            tripped_element_ids=tripped,
            lost_load_mw=float(lost_load),
            counties_dark=counties,
            critical_loads_lost=critical_loads,
            steps=len(tripped),
        ).model_dump(mode="json")
    except (KeyError, TypeError, ValidationError, ValueError):
        return _unavailable(
            "artifact_unavailable", "cascade artifact does not fit the tool contract"
        )


def non_interactive_tool_handlers(
    services: NonInteractiveToolServices,
) -> dict[str, ToolHandler]:
    """Bind all nine frozen names to local, evidence-preserving capabilities."""

    async def predict(
        payload: BaseModel, _: Mapping[str, object]
    ) -> Mapping[str, object]:
        return _predict_outage(
            services.path, PredictOutageInput.model_validate(payload)
        )

    async def cascade(
        payload: BaseModel, _: Mapping[str, object]
    ) -> Mapping[str, object]:
        value = RunCascadeInput.model_validate(payload)
        if services.cascade_executor is not None:
            return await _executor_output(
                services.cascade_executor, value, CascadeData, "cascade"
            )
        return _persisted_cascade(services.path, value)

    async def score_site(
        payload: BaseModel, _: Mapping[str, object]
    ) -> Mapping[str, object]:
        value = ScoreSiteInput.model_validate(payload)
        if services.site_score_executor is not None:
            return await _executor_output(
                services.site_score_executor, value, SiteScoreData, "site-score"
            )
        return _unavailable(
            "invalid_prerequisite",
            "no local site-score executor with protected-load evidence is registered",
        )

    async def top_lines(
        payload: BaseModel, _: Mapping[str, object]
    ) -> Mapping[str, object]:
        value = TopLinesInput.model_validate(payload)
        result = TopLinesReader(services.path).top_lines(
            value.region, value.tech, value.n
        )
        return result.model_dump(mode="json")

    async def sql(payload: BaseModel, _: Mapping[str, object]) -> Mapping[str, object]:
        value = SqlInput.model_validate(payload)
        if services.sql_executor is None:
            return _unavailable(
                "invalid_prerequisite",
                "no approved local SQL-view registry is registered for this deployment",
            )
        return (await services.sql_executor.execute(value)).model_dump(mode="json")

    async def cite(payload: BaseModel, _: Mapping[str, object]) -> Mapping[str, object]:
        value = CiteInput.model_validate(payload)
        response = retrieve(value.query, services.retrieval_index, limit=value.k)
        if response.status == "unavailable":
            assert response.unavailable is not None
            return unavailable_output(
                response.unavailable.code,
                response.unavailable.reason,
            ).model_dump(mode="json")
        hits = [item.hit() for item in response.hits]
        return CiteData(
            status="available",
            provenance=[
                ArtifactRef(
                    artifact_id=f"retrieval:{item.chunk_id}",
                    artifact_version=item.version,
                    source_kind="retrieval",
                    source_ref=item.source,
                )
                for item in response.hits
            ],
            hits=hits,
        ).model_dump(mode="json")

    async def compare(
        payload: BaseModel, _: Mapping[str, object]
    ) -> Mapping[str, object]:
        value = CompareInterventionsInput.model_validate(payload)
        if services.comparison_reader is not None:
            return await _executor_output(
                services.comparison_reader, value, InterventionsData, "comparison"
            )
        return _unavailable(
            "invalid_prerequisite",
            "no local persisted-comparison reader is registered for this deployment",
        )

    async def critical(
        payload: BaseModel, _: Mapping[str, object]
    ) -> Mapping[str, object]:
        value = TopCriticalElementsInput.model_validate(payload)
        if services.critical_elements_reader is not None:
            return await _executor_output(
                services.critical_elements_reader,
                value,
                CriticalElementsData,
                "critical-elements",
            )
        return _unavailable(
            "invalid_prerequisite",
            "no local critical-elements reader is registered for this deployment",
        )

    async def causal(
        payload: BaseModel, _: Mapping[str, object]
    ) -> Mapping[str, object]:
        value = CausalQueryInput.model_validate(payload)
        if services.causal_reader is None:
            return _unavailable(
                "artifact_unavailable",
                "causal artifact bindings are unavailable for this deployment",
            )
        return services.causal_reader.query(value).model_dump(mode="json")

    return {
        "predict_outage": predict,
        "run_cascade": cascade,
        "score_site": score_site,
        "top_lines": top_lines,
        "sql": sql,
        "cite": cite,
        "compare_interventions": compare,
        "top_critical_elements": critical,
        "causal_query": causal,
    }

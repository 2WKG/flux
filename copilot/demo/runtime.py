"""Explicit runtime composition for the real synthetic cascade demo backend."""

from __future__ import annotations

import asyncio
from pathlib import Path

from copilot.demo.ask_backend import CascadeRunner, CoreCascadeEvidence, DemoAskBackend
from copilot.demo.jepa import DEFAULT_JEPA_ARTIFACT
from copilot.runtime import AsyncNarrationProvider
from copilot.tools.schemas import ArtifactRef, ToolOutput, unavailable_output


class CoreCascadeRunner:
    """Adapter for ``twin.cascade.run_cascade`` that preserves raw core output."""

    def __init__(self, *, duckdb_path: Path, case_path: Path | None = None) -> None:
        self._duckdb_path = duckdb_path
        self._case_path = case_path

    async def run(
        self, *, element_ids: list[str], scenario_id: str, hour: int
    ) -> CoreCascadeEvidence | ToolOutput:
        return await asyncio.to_thread(
            self._run, element_ids=element_ids, scenario_id=scenario_id, hour=hour
        )

    def _run(
        self, *, element_ids: list[str], scenario_id: str, hour: int
    ) -> CoreCascadeEvidence | ToolOutput:
        try:
            from twin.cascade import run_cascade
            from twin.contracts import (
                SimulationInputError,
                SimulationSolveError,
                SimulationUnavailableError,
            )
        except ImportError:
            return unavailable_output(
                "artifact_unavailable", "Synthetic cascade core is not installed."
            )
        try:
            result = run_cascade(
                element_ids,
                scenario_id,
                hour,
                case_path=self._case_path,
                db_path=self._duckdb_path,
                write=False,
            )
        except SimulationInputError:
            return unavailable_output(
                "invalid_prerequisite", "The selected synthetic grid element is invalid."
            )
        except SimulationUnavailableError:
            return unavailable_output(
                "artifact_unavailable", "Synthetic cascade inputs are unavailable."
            )
        except SimulationSolveError:
            return unavailable_output(
                "artifact_unavailable", "The synthetic cascade solver did not produce a result."
            )
        if not isinstance(result, dict) or result.get("synthetic") is not True:
            return unavailable_output(
                "invalid_prerequisite", "The cascade core returned an invalid synthetic result."
            )
        return CoreCascadeEvidence(
            result=result,
            provenance=(
                ArtifactRef(
                    artifact_id="tx:synthetic:activsg2000",
                    artifact_version="current",
                    source_kind="simulated",
                    source_ref=str(self._case_path or "default ACTIVSg2000 MATPOWER case"),
                ),
                ArtifactRef(
                    artifact_id="tx:context:grid-duckdb",
                    artifact_version="current",
                    source_kind="observed",
                    source_ref=str(self._duckdb_path),
                ),
            ),
            limitations=(
                "Synthetic (ACTIVSg2000) topology only; not a physical asset map.",
                "Physical-inventory connectivity is not inferred from this result.",
            ),
        )


def build_demo_ask_backend(
    *,
    duckdb_path: Path,
    cascade_runner: CascadeRunner | None = None,
    provider: AsyncNarrationProvider | None = None,
    case_path: Path | None = None,
    jepa_artifact_path: Path = DEFAULT_JEPA_ARTIFACT,
) -> DemoAskBackend:
    """Build the opt-in primary ``/ask`` backend; no module-global wiring."""

    runner = cascade_runner or CoreCascadeRunner(
        duckdb_path=duckdb_path, case_path=case_path
    )
    return DemoAskBackend(runner, provider, jepa_artifact_path=jepa_artifact_path)

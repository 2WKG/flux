import type { ClientState } from "../data/client-state";
import { ArtifactPanelState } from "./ArtifactPanelState";
import type { ArtifactRef, InterventionsResult } from "./copilot-contracts";
import { formatCount, formatMetric } from "./panel-format";

export const NO_INTERVENTIONS_MESSAGE = "No interventions were returned by the server.";
export const NO_ASSUMPTIONS_MESSAGE = "Assumptions: none were returned by the server.";
export const NO_PROVENANCE_MESSAGE = "Source: no artifact provenance returned.";
export const HEURISTIC_CAVEAT = "Heuristic result: not a learned-model estimate.";

function Provenance({ provenance }: Readonly<{ provenance: readonly ArtifactRef[] }>) {
  if (provenance.length === 0) return <p>{NO_PROVENANCE_MESSAGE}</p>;
  return <>
    <ul aria-label="Artifact provenance">{provenance.map((artifact) => <li key={`${artifact.artifact_id}:${artifact.artifact_version}`}>{artifact.source_kind} · {artifact.artifact_id} · {artifact.artifact_version} · {artifact.source_ref}</li>)}</ul>
    {provenance.some((artifact) => artifact.source_kind === "heuristic") && <p>{HEURISTIC_CAVEAT}</p>}
  </>;
}

/** Renders the `compare_interventions` result (`InterventionsData | UnavailableOutput`, spec 00-overview A8). */
export function InterventionComparisonPanel({ state }: Readonly<{ state: ClientState<InterventionsResult> }>) {
  return <ArtifactPanelState state={state}>{(result) => result.status === "unavailable"
    ? <section aria-label="Intervention comparison unavailable"><h2>Intervention comparison</h2><p>{result.unavailable.code}: {result.unavailable.reason}</p><Provenance provenance={result.provenance} /></section>
    : <section aria-label="Intervention comparison"><h2>Intervention comparison</h2><p>Scenario: {result.scenario_id}</p><p>Baseline run: {result.baseline_run_id}</p>{result.interventions.length === 0
      ? <p>{NO_INTERVENTIONS_MESSAGE}</p>
      : <ul>{result.interventions.map((intervention) => <li key={`${intervention.kind}:${intervention.intervention_id}:${intervention.run_id}`}>{intervention.intervention_id} ({intervention.kind}, run {intervention.run_id}): {formatMetric(intervention.lol_reduction_mwh, "MWh loss-of-load reduction")} · {formatMetric(intervention.customer_hours_avoided, "customer-hours avoided")} · {formatCount(intervention.critical_loads_protected)} critical loads protected</li>)}</ul>}{result.assumptions.length === 0
      ? <p>{NO_ASSUMPTIONS_MESSAGE}</p>
      : <><p>Assumptions:</p><ul aria-label="Assumptions">{result.assumptions.map((assumption, index) => <li key={`${index}:${assumption}`}>{assumption}</li>)}</ul></>}<Provenance provenance={result.provenance} /></section>}</ArtifactPanelState>;
}

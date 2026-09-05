import type { ClientState } from "../data/client-state";
import { ArtifactPanelState, ArtifactProvenance } from "./ArtifactPanelState";
import type { InterventionsResult } from "./copilot-contracts";

export function InterventionComparisonPanel({ state }: Readonly<{ state: ClientState<InterventionsResult> }>) {
  return <ArtifactPanelState state={state}>{(result) => result.status === "unavailable" ? <section><h2>Intervention comparison</h2><p>{result.unavailable.code}: {result.unavailable.reason}</p><ArtifactProvenance provenance={result.provenance} /></section> : <section><h2>Intervention comparison</h2><p>Scenario: {result.scenario_id}</p><p>Baseline run: {result.baseline_run_id}</p><ul>{result.interventions.map((intervention) => <li key={intervention.intervention_id}>{intervention.intervention_id} ({intervention.kind}): {intervention.lol_reduction_mwh} MWh loss-of-load reduction · {intervention.customer_hours_avoided} customer-hours avoided · {intervention.critical_loads_protected.length} critical loads protected</li>)}</ul>{result.assumptions.length > 0 && <p>Assumptions: {result.assumptions.join("; ")}</p>}<ArtifactProvenance provenance={result.provenance} /></section>}</ArtifactPanelState>;
}

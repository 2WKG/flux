import type { ClientState } from "../data/client-state";
import { ArtifactPanelState, type Provenance } from "./ArtifactPanelState";
export type Comparison=Readonly<{scenario_id:string; intervention_id:string; status:string; value:number|null; source_class:string; provenance:Provenance}>;
export function InterventionComparisonPanel({state}:{state:ClientState<Comparison>}) { return <ArtifactPanelState state={state}>{x=><section><h2>Intervention comparison</h2><p>Scenario: {x.scenario_id}</p><p>Intervention: {x.intervention_id}</p><p>Status: {x.status}</p><p>Value: {x.value??"unavailable"}</p><p>Source: {x.source_class} · {x.provenance.artifact_id}</p></section>}</ArtifactPanelState>; }

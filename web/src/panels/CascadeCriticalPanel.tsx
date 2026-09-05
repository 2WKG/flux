import type { ClientState } from "../data/client-state";
import { ArtifactPanelState, ArtifactProvenance } from "./ArtifactPanelState";
import type { CriticalElementsResult } from "./copilot-contracts";

export function CascadeCriticalPanel({ state }: Readonly<{ state: ClientState<CriticalElementsResult> }>) {
  return <ArtifactPanelState state={state}>{(result) => result.status === "unavailable" ? <section><h2>Cascade and critical elements</h2><p>{result.unavailable.code}: {result.unavailable.reason}</p><ArtifactProvenance provenance={result.provenance} /></section> : <section><h2>Cascade and critical elements</h2><p>Scenarios: {result.scenario_ids.join(", ")}</p><p>Requested elements: {result.n}{result.partial ? " (partial results)" : ""}</p>{result.elements.length === 0 ? <p>No critical elements were returned by the server.</p> : <ul>{result.elements.map((element) => <li key={element.element_id}>{element.element_id} ({element.kind}): {element.lost_load_mw} MW lost load · {element.runs} runs</li>)}</ul>}<ArtifactProvenance provenance={result.provenance} /></section>}</ArtifactPanelState>;
}

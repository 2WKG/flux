import type { ClientState } from "../data/client-state";
import { ArtifactPanelState, ArtifactProvenance } from "./ArtifactPanelState";
import type { CriticalElementsResult } from "./copilot-contracts";
import { formatMetric } from "./panel-format";

export const NO_CRITICAL_ELEMENTS_MESSAGE = "No critical elements were returned by the server.";

export function CascadeCriticalPanel({ state }: Readonly<{ state: ClientState<CriticalElementsResult> }>) {
  return <ArtifactPanelState state={state}>{(result) => result.status === "unavailable" ? <section aria-label="Cascade and critical elements unavailable"><h2>Cascade and critical elements</h2><p>{result.unavailable.code}: {result.unavailable.reason}</p><ArtifactProvenance provenance={result.provenance} /></section> : <section aria-label="Cascade and critical elements"><h2>Cascade and critical elements</h2><p>Scenarios: {result.scenario_ids.join(", ")}</p><p>Requested elements: {formatMetric(result.n)}{result.partial ? " (partial results)" : ""}</p>{result.elements.length === 0 ? <p>{NO_CRITICAL_ELEMENTS_MESSAGE}</p> : <ul>{result.elements.map((element) => <li key={`${element.kind}:${element.element_id}`}>{element.element_id} ({element.kind}): {formatMetric(element.lost_load_mw, "MW lost load")} · {formatMetric(element.runs, "runs")}</li>)}</ul>}<ArtifactProvenance provenance={result.provenance} /></section>}</ArtifactPanelState>;
}

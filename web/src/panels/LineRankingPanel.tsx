import type { ClientState } from "../data/client-state";
import { ArtifactPanelState, ArtifactProvenance } from "./ArtifactPanelState";
import type { LinesResult } from "./copilot-contracts";

export function LineRankingPanel({ state }: Readonly<{ state: ClientState<LinesResult> }>) {
  return <ArtifactPanelState state={state}>{(result) => result.status === "unavailable" ? <section><h2>Line ranking</h2><p>{result.unavailable.code}: {result.unavailable.reason}</p><ArtifactProvenance provenance={result.provenance} /></section> : <section><h2>Line ranking</h2><p>Region: {result.region} · Technology: {result.tech}</p>{result.lines.length === 0 ? <p>No ranked lines were returned by the server.</p> : <ul>{result.lines.map((line) => <li key={line.line_id}>{line.line_id}: {line.mw_per_musd} MW/$M · {line.uplift_mw} MW uplift · {line.ferc_screen_pass ? "FERC screen passed" : "FERC screen not passed"}</li>)}</ul>}<ArtifactProvenance provenance={result.provenance} /></section>}</ArtifactPanelState>;
}

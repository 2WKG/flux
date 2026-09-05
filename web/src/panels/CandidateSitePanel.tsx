import type { ClientState } from "../data/client-state";
import { ArtifactPanelState, type Provenance } from "./ArtifactPanelState";
export type CandidateSite = Readonly<{ site_id: string; name: string; scenario_id: string; status: string; safety_score: number | null; grid_value_score: number | null; provenance: Provenance }>;
export function CandidateSitePanel({ state }: Readonly<{ state: ClientState<CandidateSite> }>) {
  return <ArtifactPanelState state={state}>{(site) => <section aria-label="Candidate site"><h2>{site.name}</h2><p>Scenario: {site.scenario_id}</p><p>Status: {site.status}</p><p>Safety score: {site.safety_score ?? "unavailable"}</p><p>Grid value score: {site.grid_value_score ?? "unavailable"}</p><p>Source: {site.provenance.source_kind} · {site.provenance.artifact_id} · {site.provenance.artifact_version}</p></section>}</ArtifactPanelState>;
}

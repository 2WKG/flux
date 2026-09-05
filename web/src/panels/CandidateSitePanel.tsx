import type { ClientState } from "../data/client-state";
import { ArtifactPanelState, ArtifactProvenance } from "./ArtifactPanelState";
import type { SiteScoreResult } from "./copilot-contracts";
import { formatCount, formatMetric } from "./panel-format";

export function CandidateSitePanel({ state }: Readonly<{ state: ClientState<SiteScoreResult> }>) {
  return <ArtifactPanelState state={state}>{(site) => site.status === "unavailable" ? <section aria-label="Candidate site unavailable"><h2>Candidate site</h2><p>{site.unavailable.code}: {site.unavailable.reason}</p><ArtifactProvenance provenance={site.provenance} /></section> : <section aria-label="Candidate site"><h2>{site.name}</h2><p>Scenario: {site.scenario_id}</p><p>Unit: {formatMetric(site.unit_mw, "MW")}</p><p>Safety score: {formatMetric(site.safety_score)}</p><p>Grid value score: {formatMetric(site.grid_value_score)}</p><p>Loss-of-load reduction: {formatMetric(site.lol_reduction_mwh, "MWh")}</p><p>Protected critical loads: {formatCount(site.critical_loads_protected)}</p><ArtifactProvenance provenance={site.provenance} /></section>}</ArtifactPanelState>;
}

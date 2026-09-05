import type { ClientState } from "../data/client-state";
import { ArtifactPanelState, ArtifactProvenance } from "./ArtifactPanelState";
import type { PredictOutageResult } from "./copilot-contracts";

export function PredictionPanel({ state }: Readonly<{ state: ClientState<PredictOutageResult> }>) {
  return <ArtifactPanelState state={state}>{(prediction) => prediction.status === "unavailable" ? <section aria-label="Outage prediction unavailable"><h2>Outage prediction</h2><p>{prediction.unavailable.code}: {prediction.unavailable.reason}</p><ArtifactProvenance provenance={prediction.provenance} /></section> : <section aria-label="Outage prediction"><h2>Outage prediction</h2><p>Scenario: {prediction.scenario_id}</p><p>County: {prediction.county_fips} ({prediction.county_name})</p><p>Peak probability: {prediction.peak_p_out}</p><p>Peak time: {prediction.peak_ts}</p><p>Customers at risk: {prediction.customers_at_risk}</p><p>Driver: {prediction.driver}</p><p>Series points: {prediction.series.length}</p><ArtifactProvenance provenance={prediction.provenance} /></section>}</ArtifactPanelState>;
}

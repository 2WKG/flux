import type { ClientState } from "../data/client-state";
import { ArtifactPanelState, type Provenance } from "./ArtifactPanelState";

export type Prediction = Readonly<{ county_fips: string; scenario_id: string; p_out: number | null; customers_at_risk: number | null; driver: string | null; model_kind: "lightgbm" | "heuristic"; model_version: string; provenance: Provenance }>;
export function PredictionPanel({ state }: Readonly<{ state: ClientState<Prediction> }>) {
  return <ArtifactPanelState state={state}>{(prediction) => <section aria-label="Outage prediction"><h2>Outage prediction</h2><p>Scenario: {prediction.scenario_id}</p><p>County: {prediction.county_fips}</p><p>Probability: {prediction.p_out ?? "unavailable"}</p><p>Customers at risk: {prediction.customers_at_risk ?? "unavailable"}</p><p>Driver: {prediction.driver ?? "unavailable"}</p><p>Model: {prediction.model_kind} · {prediction.model_version}</p><p>Source: {prediction.provenance.source_kind} · {prediction.provenance.artifact_id} · {prediction.provenance.artifact_version}</p>{prediction.model_kind === "heuristic" && <p>Heuristic result: not a learned-model estimate.</p>}</section>}</ArtifactPanelState>;
}

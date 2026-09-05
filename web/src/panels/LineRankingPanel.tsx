import type { ClientState } from "../data/client-state";
import { ArtifactPanelState, type Provenance } from "./ArtifactPanelState";
export type LineRank = Readonly<{ line_id:string; scenario_id:string; intervention:string; score:number|null; source_class:string; provenance:Provenance }>;
export function LineRankingPanel({state}:{state:ClientState<readonly LineRank[]>}) { return <ArtifactPanelState state={state}>{rows=><section><h2>Line ranking</h2><ul>{rows.map(row=><li key={row.line_id}>{row.line_id}: {row.score??"unavailable"} · scenario {row.scenario_id} · intervention {row.intervention} · source {row.source_class} · {row.provenance.artifact_id}</li>)}</ul></section>}</ArtifactPanelState>; }

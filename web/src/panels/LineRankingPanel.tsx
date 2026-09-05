import type { ClientState } from "../data/client-state";
import { ArtifactPanelState } from "./ArtifactPanelState";
import type { ArtifactRef, LinesResult } from "./copilot-contracts";
import { formatMetric } from "./panel-format";

export const NO_RANKED_LINES_MESSAGE = "No ranked lines were returned by the server.";
export const NO_PROVENANCE_MESSAGE = "Source: no artifact provenance returned.";
export const HEURISTIC_CAVEAT = "Heuristic result: not a learned-model estimate.";

function Provenance({ provenance }: Readonly<{ provenance: readonly ArtifactRef[] }>) {
  if (provenance.length === 0) return <p>{NO_PROVENANCE_MESSAGE}</p>;
  return <>
    <ul aria-label="Artifact provenance">{provenance.map((artifact) => <li key={`${artifact.artifact_id}:${artifact.artifact_version}`}>{artifact.source_kind} · {artifact.artifact_id} · {artifact.artifact_version} · {artifact.source_ref}</li>)}</ul>
    {provenance.some((artifact) => artifact.source_kind === "heuristic") && <p>{HEURISTIC_CAVEAT}</p>}
  </>;
}

/** Renders the `top_lines` result (`LinesData | UnavailableOutput` in copilot/tools/schemas.py). */
export function LineRankingPanel({ state }: Readonly<{ state: ClientState<LinesResult> }>) {
  return <ArtifactPanelState state={state}>{(result) => result.status === "unavailable"
    ? <section aria-label="Line ranking unavailable"><h2>Line ranking</h2><p>{result.unavailable.code}: {result.unavailable.reason}</p><Provenance provenance={result.provenance} /></section>
    : <section aria-label="Line ranking"><h2>Line ranking</h2><p>Region: {result.region} · Technology: {result.tech}</p>{result.lines.length === 0
      ? <p>{NO_RANKED_LINES_MESSAGE}</p>
      : <ul>{result.lines.map((line) => <li key={`${result.tech}:${line.line_id}`}>{line.line_id}: {formatMetric(line.mw_per_musd, "MW/$M")} · {formatMetric(line.uplift_mw, "MW uplift")} · {formatMetric(line.kv, "kV")} · {line.ferc_screen_pass ? "FERC screen passed" : "FERC screen not passed"}</li>)}</ul>}<Provenance provenance={result.provenance} /></section>}</ArtifactPanelState>;
}

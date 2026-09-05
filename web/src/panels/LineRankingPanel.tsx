import type { ClientState } from "../data/client-state";
import { ArtifactPanelState, ArtifactProvenance } from "./ArtifactPanelState";
import type { LinesResult } from "./copilot-contracts";
import { formatMetric } from "./panel-format";

export const NO_RANKED_LINES_MESSAGE = "No ranked lines were returned by the server.";

/** Renders the `top_lines` result (`LinesData | UnavailableOutput` in copilot/tools/schemas.py). */
export function LineRankingPanel({ state }: Readonly<{ state: ClientState<LinesResult> }>) {
  return <ArtifactPanelState state={state}>{(result) => result.status === "unavailable"
    ? <section aria-label="Line ranking unavailable"><h2>Line ranking</h2><p>{result.unavailable.code}: {result.unavailable.reason}</p><ArtifactProvenance provenance={result.provenance} /></section>
    : <section aria-label="Line ranking"><h2>Line ranking</h2><p>Region: {result.region} · Technology: {result.tech}</p>{result.lines.length === 0
      ? <p>{NO_RANKED_LINES_MESSAGE}</p>
      : <ul>{result.lines.map((line) => <li key={`${result.tech}:${line.line_id}`}>{line.line_id}: {formatMetric(line.mw_per_musd, "MW/$M")} · {formatMetric(line.uplift_mw, "MW uplift")} · {formatMetric(line.kv, "kV")} · {line.ferc_screen_pass ? "FERC screen passed" : "FERC screen not passed"}</li>)}</ul>}<ArtifactProvenance provenance={result.provenance} /></section>}</ArtifactPanelState>;
}

import type { ClientState } from "../data/client-state";
import type { RedundancyView } from "../data/interactive-client";
import { fromClientState } from "../failure-states/adapters";
import { FailureState } from "../failure-states/FailureState";
import { STATUS_COPY } from "../source-truth";

export type { RedundancyView } from "../data/interactive-client";

export interface RedundancyPanelProps {
  /** Supplied by the shared interactive client; this panel makes no request itself. */
  readonly state: ClientState<RedundancyView>;
  readonly title?: string;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

/**
 * A presentational bus inspector over `/interactive/redundancy`.
 *
 * It makes no request and derives no score, topology, contingency, flow, or
 * distance value in the browser. The topology line renders the adapter's
 * `topology` field, which is the repository's one asserted topology token when
 * and only when the server set `synthetic_topology: true`; when it did not, the
 * panel says the topology is unavailable rather than implying source support.
 */
export function RedundancyPanel({ state, title = "Redundancy inspector" }: RedundancyPanelProps) {
  if (state.kind !== "ready") {
    const failure = fromClientState(state);
    return failure ? <FailureState state={failure} /> : null;
  }

  const result = state.data;
  const truth = result.topology === null ? "unavailable" : "synthetic";
  return <section aria-label={title} data-redundancy-truth={truth}>
    <header>
      <h2>{title}</h2>
      <p>Model bus {result.busId}</p>
      <p data-redundancy-topology={result.topology ?? ""}>
        {result.topology === null
          ? `${STATUS_COPY.unavailable}: this response asserts no topology, so no topology claim is displayed.`
          : `${STATUS_COPY.synthetic} model evidence · ${result.topology}.`}
      </p>
      <p>This response identifies a model bus only. Consumer-site mapping is unavailable.</p>
    </header>

    <section aria-label="Reachability evidence">
      <h3>Reachability screening</h3>
      <dl>
        <div><dt>N-1 survivability</dt><dd>{formatNumber(result.components.nMinusOneSurvivability)}</dd></div>
        <div><dt>Edge-disjoint paths</dt><dd>{formatNumber(result.components.edgeDisjointPaths)}</dd></div>
        <div><dt>Edge-disjoint path score</dt><dd>{formatNumber(result.components.edgeDisjointPathScore)}</dd></div>
        <div><dt>Alternative-source proximity</dt><dd>{formatNumber(result.components.alternativeSourceProximity)}</dd></div>
        <div><dt>Server-provided redundancy score</dt><dd data-redundancy-score>{formatNumber(result.score)}</dd></div>
      </dl>
    </section>

    {result.worstContingency ? <section aria-label="Worst-contingency evidence">
      <h3>Worst contingency</h3>
      <p>{result.worstContingency.branchId}</p>
      <p>Source reachable: {result.worstContingency.sourceReachable ? "yes" : "no"}</p>
      <p>Impact: {formatNumber(result.worstContingency.impact)}</p>
    </section> : null}

    {result.components.alternativeSourceHops !== null ? <section aria-label="Screening-distance evidence">
      <h3>Screening distance</h3>
      <p>{formatNumber(result.components.alternativeSourceHops)} graph hops</p>
      <p>Graph hops are supplied screening evidence, not geographic distance.</p>
    </section> : null}

    <section aria-label="Evidence and limits">
      <h3>Evidence and limits</h3>
      <dl>
        <div><dt>Evidence status</dt><dd>{result.evidence.status}</dd></div>
        <div><dt>Scenario</dt><dd>{result.evidence.scenarioId} · hour {result.evidence.hour}</dd></div>
        <div><dt>Branch selection</dt><dd>{result.evidence.branchSelection}</dd></div>
        <div><dt>Persistence</dt><dd>{result.evidence.persistence}</dd></div>
        <div><dt>Cascade</dt><dd>{result.evidence.cascade}</dd></div>
        <div><dt>Contingencies evaluated</dt><dd>{result.evidence.contingenciesEvaluated ?? STATUS_COPY.unavailable}</dd></div>
        <div><dt>Active branches</dt><dd>{result.evidence.activeBranchCount ?? STATUS_COPY.unavailable}</dd></div>
        <div><dt>Source buses</dt><dd>{result.evidence.sourceBuses.join(", ") || STATUS_COPY.unavailable}</dd></div>
      </dl>
      {result.evidence.reason ? <p>Reason: {result.evidence.reason}</p> : null}
    </section>
  </section>;
}

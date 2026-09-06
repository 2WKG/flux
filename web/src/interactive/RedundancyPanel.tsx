import type { ClientState } from "../data/client-state";
import { isRedundancyResponse, type RedundancyResponse } from "../data/interactive-client";
import { fromClientState } from "../failure-states/adapters";
import { FailureState } from "../failure-states/FailureState";

export type { RedundancyResponse } from "../data/interactive-client";

export interface RedundancyPanelProps {
  /** Supplied by the shared interactive client; this panel makes no request itself. */
  readonly state: ClientState<RedundancyResponse>;
  readonly title?: string;
}

function malformedState() {
  return {
    kind: "malformed" as const,
    message: "The redundancy response did not include a usable synthetic-bus record.",
  };
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

function provenanceText(item: RedundancyResponse["evidence"]["provenance"][number]): string {
  return `${item.sourceId} · ${item.sourceRef}${item.version ? ` · ${item.version}` : ""}`;
}

/**
 * A presentational bus inspector over the typed `/redundancy?bus_id` result.
 * It makes no request and derives no topology, site, contingency, flow, or
 * distance value in the browser. The shared client rejects a response without
 * provenance before it reaches this component.
 */
export function RedundancyPanel({ state, title = "Redundancy inspector" }: RedundancyPanelProps) {
  if (state.kind !== "ready") {
    const failure = fromClientState(state);
    return failure ? <FailureState state={failure} /> : null;
  }

  // This protects direct consumers that bypass the client's guarded boundary.
  if (!isRedundancyResponse(state.data)) {
    return <FailureState state={malformedState()} />;
  }

  const result = state.data;
  return <section aria-label={title} data-redundancy-truth={result.evidence.artifactTruth}>
    <header>
      <h2>{title}</h2>
      <p>Synthetic bus {result.busId}</p>
      <p>This response identifies a model bus only. Consumer-site mapping is unavailable.</p>
    </header>

    <section aria-label="Reachability evidence">
      <h3>Reachability screening</h3>
      <dl>
        <div><dt>N-1 survivability</dt><dd>{formatNumber(result.components.nMinusOneSurvivability)}</dd></div>
        <div><dt>Edge-disjoint paths</dt><dd>{formatNumber(result.components.edgeDisjointPaths)}</dd></div>
        <div><dt>Server-provided redundancy score</dt><dd>{formatNumber(result.score)}</dd></div>
      </dl>
    </section>

    {result.worstContingency ? <section aria-label="Worst-contingency evidence">
      <h3>Worst contingency</h3>
      <p>{result.worstContingency.branchId}</p>
      <p>Source reachable: {result.worstContingency.sourceReachable ? "yes" : "no"}</p>
    </section> : null}

    {result.components.alternativeSourceHops !== null ? <section aria-label="Screening-distance evidence">
      <h3>Screening distance</h3>
      <p>{formatNumber(result.components.alternativeSourceHops)} graph hops</p>
      <p>Graph hops are supplied screening evidence, not geographic distance.</p>
    </section> : null}

    <section aria-label="Evidence and limits">
      <h3>Evidence and limits</h3>
      <p>Synthetic screening result. No physical-topology or live-response claim is made here.</p>
      <h4>Server provenance</h4>
      <ul>{result.evidence.provenance.map((item) => <li key={`${item.sourceId}:${item.sourceRef}`}>{provenanceText(item)}</li>)}</ul>
      {result.assumptions.length > 0 ? <><h4>Server assumptions</h4><ul>{result.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></> : null}
      {result.limitations.length > 0 ? <><h4>Server limitations</h4><ul>{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul></> : null}
    </section>
  </section>;
}

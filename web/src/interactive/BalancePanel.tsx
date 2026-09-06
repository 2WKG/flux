import type { ClientState } from "../data/client-state";
import type { BalanceView } from "../data/interactive-client";
import { fromClientState } from "../failure-states/adapters";
import { FailureState } from "../failure-states/FailureState";
import { STATUS_COPY } from "../source-truth";

export interface BalancePanelProps {
  /** Supplied by the shared interactive client; this panel makes no request itself. */
  readonly state: ClientState<BalanceView>;
  readonly title?: string;
}

function mw(value: number): string {
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value)} MW`;
}

/**
 * A presentational, evidence-safe panel over `/interactive/balance`.
 *
 * Every displayed MW figure is a field of the payload `twin/balance.py`
 * emitted. In particular `headroomMw` is rendered as the server sent it and is
 * never recomputed as `capabilityMw - drawMw`: the accounting rule belongs to
 * the server, and `BalancePanel.test.mjs` proves the difference with a payload
 * whose headroom deliberately disagrees with that subtraction.
 *
 * The balance route carries no provenance record and no artifact-truth field,
 * so this panel states that absence by name instead of labelling the figures
 * with a truth it was not given.
 */
export function BalancePanel({ state, title = "Supply and draw" }: BalancePanelProps) {
  if (state.kind !== "ready") {
    const failure = fromClientState(state);
    return failure ? <FailureState state={failure} /> : null;
  }

  const balance = state.data;
  const resources = [
    ["Wind capability", balance.resourceCapabilityMw.wind],
    ["Solar capability", balance.resourceCapabilityMw.solar],
    ["Firm capability", balance.resourceCapabilityMw.firm],
    ["Unclassified capability", balance.resourceCapabilityMw.unclassified],
  ] as const;

  return <section aria-label={title} data-balance-panel="server-supplied" data-balance-provenance="unavailable">
    <header>
      <h2>{title}</h2>
      <p data-balance-basis>Capability basis: {balance.capabilityBasis}</p>
      <p>{STATUS_COPY.unavailable}: this balance response carries no provenance record, so no source claim is made for these figures.</p>
      <p>Scope: {balance.scope} · Edit hash: {balance.editHash}</p>
    </header>

    <dl>
      <div><dt>Consumer draw</dt><dd>{mw(balance.drawMw)}</dd></div>
      <div><dt>Producer capability</dt><dd>{mw(balance.capabilityMw)}</dd></div>
      <div><dt>Scheduled dispatch</dt><dd>{mw(balance.dispatchMw)}</dd></div>
      <div><dt>Headroom (server-supplied)</dt><dd data-balance-headroom>{mw(balance.headroomMw)}</dd></div>
      <div><dt>Reserve margin</dt><dd>{balance.reserveMargin === null ? STATUS_COPY.unavailable : balance.reserveMargin}</dd></div>
    </dl>

    <section aria-label="Capability by resource"><h3>Capability by resource, as supplied</h3><dl>
      {resources.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{mw(value)}</dd></div>)}
    </dl></section>

    <section aria-label="Evidence and limits"><h3>Evidence and limits</h3>
      <ul>{balance.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
    </section>
  </section>;
}

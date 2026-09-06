import type { ClientState } from "../data/client-state";
import type { BalanceResponse } from "../data/interactive-client";
import { fromClientState } from "../failure-states/adapters";
import { FailureState } from "../failure-states/FailureState";

export interface BalancePanelProps {
  /** Supplied by the shared interactive client; this panel makes no request itself. */
  readonly state: ClientState<BalanceResponse>;
  readonly title?: string;
}

const metricLabels = {
  served_load_mw: "Served load",
  generation_mw: "Generation",
  slack_mw: "Slack",
  residual_mw: "Residual",
} as const;

function mw(value: number): string {
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value)} MW`;
}

function sourceDisclosure(balance: BalanceResponse): string {
  const { artifactTruth, capabilityBasis, topology } = balance.evidence;
  const disclosures: string[] = [];
  if (artifactTruth === "synthetic") {
    disclosures.push(`Synthetic model evidence${topology ? ` · ${topology}` : ""}.`);
  }
  if (capabilityBasis === "nameplate") {
    disclosures.push("Nameplate accounting: capacity is not an operating-generation or reliability claim.");
  }
  return disclosures.join(" ") || "Server-supplied balance evidence.";
}

/**
 * A presentational, evidence-safe panel. Every displayed metric is a field from
 * the `/balance` payload; no residual, slack, fuel amount, or edit delta is
 * calculated in the browser.
 */
export function BalancePanel({ state, title = "Supply and draw" }: BalancePanelProps) {
  if (state.kind !== "ready") {
    const failure = fromClientState(state);
    return failure ? <FailureState state={failure} /> : null;
  }

  const balance = state.data;
  const fuel = Object.entries(balance.fuelSplitMw ?? {});
  return <section aria-label={title} data-balance-truth={balance.evidence.artifactTruth}>
    <header>
      <h2>{title}</h2>
      <p>{sourceDisclosure(balance)}</p>
      <p>Scope: {balance.scope} · Scenario: {balance.scenarioId}</p>
    </header>

    <dl>
      <div><dt>Served load</dt><dd>{mw(balance.servedLoadMw)}</dd></div>
      <div><dt>Generation</dt><dd>{mw(balance.generationMw)}</dd></div>
      <div><dt>Slack</dt><dd>{mw(balance.slackMw)}</dd></div>
      <div><dt>Residual</dt><dd>{mw(balance.residualMw)}</dd></div>
    </dl>

    {fuel.length > 0 ? <section aria-label="Fuel split"><h3>Fuel split supplied by server</h3><dl>
      {fuel.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{mw(value)}</dd></div>)}
    </dl></section> : null}

    {balance.editDelta && balance.editDelta.length > 0 ? <section aria-label="Edit delta"><h3>Server-supplied edit delta</h3><dl>
      {balance.editDelta.map((delta) => <div key={delta.metric}><dt>{metricLabels[delta.metric]}</dt><dd>{mw(delta.valueMw)}</dd></div>)}
    </dl></section> : null}

    <section aria-label="Evidence and limits"><h3>Evidence and limits</h3>
      <p>Capability basis: {balance.evidence.capabilityBasis.replace("_", " ")}.</p>
      <ul>{balance.evidence.provenance.map((item) => <li key={`${item.sourceId}:${item.sourceRef}`}>{item.sourceId} · {item.sourceRef}{item.version ? ` · ${item.version}` : ""}</li>)}</ul>
      {balance.assumptions.length > 0 ? <><h4>Server assumptions</h4><ul>{balance.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></> : null}
      {balance.limitations.length > 0 ? <><h4>Server limitations</h4><ul>{balance.limitations.map((item) => <li key={item}>{item}</li>)}</ul></> : null}
    </section>
  </section>;
}

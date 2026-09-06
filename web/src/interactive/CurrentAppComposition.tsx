import { useState } from "react";

import { AgentSimulationAdapter } from "./AgentSimulationAdapter";
import { BalancePanel } from "./BalancePanel";
import { CascadePlaybackPanel, type CascadeRequest, type InteractiveCascadeData, type InteractiveEnvelope, type ScenarioEditData, type ScenarioEditRequest } from "./CascadePlaybackPanel";
import { RedundancyPanel } from "./RedundancyPanel";
import { ScenarioEditPanel, type GridEdit } from "./ScenarioEditPanel";
import { SitingPanel } from "./SitingPanel";

const INTERACTIVE_UNAVAILABLE = "The interactive simulation HTTP surface is not available at this origin yet. No fixture result is shown.";

function unavailableCascade<T>(_request: ScenarioEditRequest | CascadeRequest, _signal: AbortSignal): Promise<InteractiveEnvelope<T>> {
  return Promise.reject({ kind: "unavailable", message: INTERACTIVE_UNAVAILABLE });
}

/**
 * Composition for simulation panels that do not have a current server binding.
 * The main shell owns the one real Ask v1 dock and its trace; this adapter keeps
 * the other panels mounted with a named server refusal until 436 is available.
 */
export function CurrentAppComposition() {
  const [ops, setOps] = useState<readonly GridEdit[]>([]);
  const [scenarioId, setScenarioId] = useState("");
  const unavailableState = { kind: "unavailable" as const, source: "server" as const, message: INTERACTIVE_UNAVAILABLE, retryAfterSeconds: null, requestId: "interactive-surface-pending" };
  const noElements: readonly { id: string; label: string; kind: "generator" }[] = [];

  return <section aria-label="Current application controls" data-current-app-composition="mounted" style={{ display: "grid", gap: 16, marginTop: 16 }}>
    <section aria-label="Interactive service status" style={{ border: "1px solid #694f2f", borderRadius: 12, padding: 14 }}>
      <h2>Interactive controls</h2>
      <p>All numerical and feasibility results await a server response. This browser does not calculate power flow, feasibility, balance, redundancy, cascade, or siting values.</p>
    </section>

    <ScenarioEditPanel baseScenarioId={scenarioId} onBaseScenarioIdChange={setScenarioId} ops={ops} onOpsChange={setOps} serverState={{ kind: "unavailable", reason: INTERACTIVE_UNAVAILABLE }} />
    <CascadePlaybackPanel elements={noElements} scenarioId={scenarioId} hour={0} prepareEdit={unavailableCascade<ScenarioEditData>} runCascade={unavailableCascade<InteractiveCascadeData>} />
    <BalancePanel state={unavailableState} />
    <RedundancyPanel state={unavailableState} />
    <SitingPanel input={{ state: "unavailable", message: INTERACTIVE_UNAVAILABLE }} />
    <AgentSimulationAdapter events={[]} />
  </section>;
}

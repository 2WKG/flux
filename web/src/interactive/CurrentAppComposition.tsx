import { useCallback, useMemo, useRef, useState } from "react";

import { MainAssistant } from "../main-assistant/MainAssistant";
import { createRunState, runReducer } from "../ask/run-state/reducer";
import type { RunEvent, RunIdentity, RunState } from "../ask/run-state/types";
import type { AskRequestBody, SceneContext } from "../chat/ask-contract";
import { AgentSimulationAdapter } from "./AgentSimulationAdapter";
import { BalancePanel } from "./BalancePanel";
import { CascadePlaybackPanel, type CascadeRequest, type InteractiveCascadeData, type InteractiveEnvelope, type ScenarioEditData, type ScenarioEditRequest } from "./CascadePlaybackPanel";
import { RedundancyPanel } from "./RedundancyPanel";
import { ScenarioEditPanel, type GridEdit } from "./ScenarioEditPanel";
import { SitingPanel } from "./SitingPanel";
import { FailureState } from "../failure-states/FailureState";

const INTERACTIVE_UNAVAILABLE = "The interactive simulation HTTP surface is not available at this origin yet. No fixture result is shown.";
const EMPTY_CONTEXT: SceneContext = {
  scenario_id: null,
  hour: null,
  selected_site_id: null,
  compare_site_id: null,
  selected_element_id: null,
  unit_mw: null,
};

function identity(number: number): RunIdentity {
  return { attemptId: `main-scene-attempt-${String(number).padStart(4, "0")}`, contextRevision: "main-scene-v1" };
}

function unavailableCascade<T>(_request: ScenarioEditRequest | CascadeRequest, _signal: AbortSignal): Promise<InteractiveEnvelope<T>> {
  return Promise.reject({ kind: "unavailable", message: INTERACTIVE_UNAVAILABLE });
}

/** Read only generic, server-emitted ask v1 events; unknown payloads are left to the reducer's protocol checks. */
async function consumeAsk(
  response: Response,
  signal: AbortSignal,
  onEvent: (event: RunEvent) => void,
  onMalformed: (message: string) => void,
) {
  const contentType = response.headers.get("content-type") ?? "";
  if (!response.ok || !contentType.toLowerCase().startsWith("text/event-stream")) {
    throw new Error(response.status === 404
      ? "The same-origin /ask endpoint is not mounted."
      : "The same-origin /ask endpoint did not return the required event stream.");
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error("The /ask response did not expose an event stream body.");
  const decoder = new TextDecoder();
  let buffered = "";
  while (!signal.aborted) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffered += decoder.decode(chunk.value, { stream: true });
    const frames = buffered.split(/\r?\n\r?\n/);
    buffered = frames.pop() ?? "";
    for (const frame of frames) {
      const lines = frame.split(/\r?\n/);
      const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
      if (!data) continue;
      const id = lines.find((line) => line.startsWith("id:"))?.slice(3).trim();
      const type = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
      try {
        const payload: unknown = JSON.parse(data);
        if (!payload || typeof payload !== "object" || Array.isArray(payload) || !id || !type) {
          onMalformed("The /ask stream supplied a frame without the required event, id, and JSON object fields.");
          continue;
        }
        onEvent({ ...(payload as object), id, type } as RunEvent);
      } catch {
        onMalformed("The /ask stream supplied malformed JSON. No event payload was accepted.");
      }
    }
  }
}

/**
 * The page-level composition point. Each leaf remains responsible for its own
 * presentation contract; this module supplies only current, truthful state.
 */
export function CurrentAppComposition() {
  const [ops, setOps] = useState<readonly GridEdit[]>([]);
  const [context, setContext] = useState<SceneContext>(EMPTY_CONTEXT);
  const [identityNumber, setIdentityNumber] = useState(1);
  const currentIdentity = useMemo(() => identity(identityNumber), [identityNumber]);
  const [run, setRun] = useState<RunState>(() => createRunState(identity(1), "synthetic"));
  const [askFailure, setAskFailure] = useState<string | null>(null);
  const askController = useRef<AbortController | null>(null);

  const onSend = useCallback((request: AskRequestBody) => {
    askController.current?.abort();
    const controller = new AbortController();
    askController.current = controller;
    setAskFailure(null);
    setRun(createRunState(currentIdentity, "synthetic"));
    void fetch("/ask", {
      method: "POST",
      signal: controller.signal,
      headers: { "content-type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(request),
    }).then((response) => consumeAsk(response, controller.signal, (event) => {
      setRun((previous) => runReducer(previous, { type: "event", identity: currentIdentity, event }));
    }, (message) => {
      setRun((previous) => runReducer(previous, { type: "malformed", identity: currentIdentity, message }));
    })).catch((error: unknown) => {
      if (!controller.signal.aborted) setAskFailure(error instanceof Error ? error.message : "The /ask request could not be started.");
    }).finally(() => {
      if (askController.current === controller) askController.current = null;
    });
  }, [currentIdentity]);

  const cancelAsk = useCallback(() => {
    askController.current?.abort();
    setRun((previous) => runReducer(previous, { type: "cancel_requested", identity: currentIdentity }));
  }, [currentIdentity]);

  const newAttempt = useCallback(() => {
    askController.current?.abort();
    setIdentityNumber((number) => number + 1);
    setAskFailure(null);
  }, []);

  const unavailableState = { kind: "unavailable" as const, source: "server" as const, message: INTERACTIVE_UNAVAILABLE, retryAfterSeconds: null, requestId: "interactive-surface-pending" };
  const noElements: readonly { id: string; label: string; kind: "generator" }[] = [];

  return <section aria-label="Current application controls" data-current-app-composition="mounted" style={{ display: "grid", gap: 16, marginTop: 16 }}>
    <section aria-label="Interactive service status" style={{ border: "1px solid #694f2f", borderRadius: 12, padding: 14 }}>
      <h2>Interactive controls</h2>
      <p>All numerical and feasibility results await a server response. This browser does not calculate power flow, feasibility, balance, redundancy, cascade, or siting values.</p>
    </section>

    <ScenarioEditPanel baseScenarioId={context.scenario_id ?? ""} onBaseScenarioIdChange={(scenario_id) => setContext((current) => ({ ...current, scenario_id: scenario_id || null }))} ops={ops} onOpsChange={setOps} serverState={{ kind: "unavailable", reason: INTERACTIVE_UNAVAILABLE }} />
    <CascadePlaybackPanel elements={noElements} scenarioId={context.scenario_id ?? ""} hour={context.hour ?? 0} prepareEdit={unavailableCascade<ScenarioEditData>} runCascade={unavailableCascade<InteractiveCascadeData>} />
    <BalancePanel state={unavailableState} />
    <RedundancyPanel state={unavailableState} />
    <SitingPanel input={{ state: "unavailable", message: INTERACTIVE_UNAVAILABLE }} />

    <section aria-label="Assistant surface" style={{ display: "grid", gap: 12 }}>
      <MainAssistant
        chat={{ contextRevision: currentIdentity.contextRevision, context, attemptId: currentIdentity.attemptId, sourceLabel: "Current synthetic simulation scene", sourceStatus: "synthetic", onSend, onRetry: newAttempt, onContextChange: setContext }}
        run={run}
        onCancelRun={cancelAsk}
      />
      {askFailure && <FailureState state={{ kind: "unavailable", message: askFailure, code: "ask_sse_unavailable" }} onRetry={newAttempt} />}
      <AgentSimulationAdapter events={run.trace} />
    </section>
  </section>;
}

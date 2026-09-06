import { useEffect, useReducer, useRef } from "react";
import { createRunState, runReducer } from "./reducer";
import type { RunEvent, RunIdentity, SourceStatus } from "./types";

const sourceStatusLabel: Record<SourceStatus, string> = {
  source_supported: "Source-supported",
  source_screened: "Source-screened",
  hypothetical: "Hypothetical",
  synthetic: "Synthetic",
  unavailable: "Unavailable",
  request_failed: "Request-failed",
};

export interface RunTraceProps {
  state: ReturnType<typeof createRunState>;
  onCancel?: (identity: RunIdentity) => void;
}

/** Presentational trace. It never reads a stream or invents a terminal outcome. */
export function RunTrace({ state, onCancel }: RunTraceProps) {
  const active = state.phase === "idle" || state.phase === "active" || state.phase === "cancelling";

  const cancel = () => onCancel?.(state.identity);

  return (
    <section aria-label="Run progress" data-run-phase={state.phase} data-source-status={state.sourceStatus}>
      <p>Run {state.phase === "cancelling" ? "cancellation requested" : state.phase}</p>
      <p role="status">Source status: {sourceStatusLabel[state.sourceStatus]}</p>
      {active && onCancel ? <button type="button" onClick={cancel} disabled={state.phase === "cancelling"}>Cancel run</button> : null}
      <ol aria-label="Tool trace">
        {Object.values(state.tools).map((tool) => <li key={tool.callId}><details><summary>{tool.tool}: {tool.result ? tool.result.ok ? "completed" : "failed" : "running"}</summary><pre>{JSON.stringify(tool.result?.ok ? tool.result.result : tool.result?.error ?? tool.input, null, 2)}</pre></details></li>)}
      </ol>
      {state.text ? <p>{state.text}</p> : null}
      {state.terminal?.type === "error" ? <p role="alert">{state.terminal.error.message}</p> : null}
      {state.issues.map((item, index) => <p role="alert" key={`${item.kind}-${index}`}>{item.message}</p>)}
      <output hidden data-next-seq={state.expectedSeq} />
    </section>
  );
}

/**
 * A concrete browser seam for the parent chat dock. The parent supplies the
 * parser's arrival-ordered event list and a request-safe cancellation callback.
 */
export function RunTraceHarness({ identity, sourceStatus, events, onCancel }: { identity: RunIdentity; sourceStatus: SourceStatus; events: readonly RunEvent[]; onCancel?: (identity: RunIdentity) => void }) {
  return <RunTraceSession key={`${identity.attemptId}\u0000${identity.contextRevision}`} identity={identity} sourceStatus={sourceStatus} events={events} onCancel={onCancel} />;
}

function RunTraceSession({ identity, sourceStatus, events, onCancel }: { identity: RunIdentity; sourceStatus: SourceStatus; events: readonly RunEvent[]; onCancel?: (identity: RunIdentity) => void }) {
  const [state, dispatch] = useReducer(runReducer, createRunState(identity, sourceStatus));
  const processed = useRef(0);
  useEffect(() => {
    for (const event of events.slice(processed.current)) dispatch({ type: "event", identity, event });
    processed.current = events.length;
  }, [events, identity]);
  useEffect(() => dispatch({ type: "source_status", identity, sourceStatus }), [identity, sourceStatus]);
  return <RunTrace state={state} onCancel={(run) => { dispatch({ type: "cancel_requested", identity: run }); onCancel?.(run); }} />;
}

import type { ErrorEvent, RunAction, RunEvent, RunIdentity, RunState, SourceStatus, TraceIssue } from "./types";

export function createRunState(identity: RunIdentity, sourceStatus: SourceStatus = "source_supported"): RunState {
  return { identity, sourceStatus, phase: "idle", expectedSeq: 1, text: "", trace: [], tools: {}, issues: [] };
}

function sameIdentity(left: RunIdentity, right: RunIdentity): boolean {
  return left.attemptId === right.attemptId && left.contextRevision === right.contextRevision;
}

function issue(state: RunState, next: TraceIssue, phase: RunState["phase"] = state.phase): RunState {
  return { ...state, phase, issues: [...state.issues, next] };
}

function protocolError(state: RunState, message: string, event?: RunEvent): RunState {
  return issue(state, { kind: "out_of_order", message, event }, "protocol_error");
}

function isTerminal(state: RunState): boolean {
  return state.phase === "completed" || state.phase === "failed" || state.phase === "cancelled" || state.phase === "protocol_error";
}

function applyEvent(state: RunState, event: RunEvent): RunState {
  if (!Number.isSafeInteger(event.seq) || event.seq < 1 || event.id !== String(event.seq)) {
    return issue(state, { kind: "malformed", message: "The stream event has an invalid or mismatched id/sequence.", event }, "protocol_error");
  }
  if (isTerminal(state)) {
    return issue(state, { kind: "after_terminal", message: "An event arrived after this run had already terminated.", event });
  }
  if (event.seq !== state.expectedSeq) {
    return protocolError(state, `Expected event ${state.expectedSeq}, received ${event.seq}. The trace was not reordered.`, event);
  }
  if (event.seq === 1 && event.type !== "lifecycle") {
    return protocolError(state, "The first application event was not a lifecycle start.", event);
  }
  if (state.expectedSeq > 1 && event.type === "lifecycle") {
    return protocolError(state, "A lifecycle start appeared after the run had started.", event);
  }

  const advanced = { ...state, expectedSeq: event.seq + 1, trace: [...state.trace, event], phase: state.phase === "idle" ? "active" : state.phase } as RunState;
  switch (event.type) {
    case "text":
      return { ...advanced, text: `${advanced.text}${event.delta}` };
    case "tool_call":
      if (advanced.tools[event.callId]) {
        return issue(advanced, { kind: "duplicate_call", message: `Tool call ${event.callId} was emitted more than once.`, event }, "protocol_error");
      }
      return { ...advanced, tools: { ...advanced.tools, [event.callId]: { callId: event.callId, tool: event.tool, input: event.input } } };
    case "tool_result": {
      const tool = advanced.tools[event.callId];
      if (!tool || tool.tool !== event.tool) {
        return issue(advanced, { kind: "unknown_call", message: `Tool result ${event.callId} has no matching tool call.`, event }, "protocol_error");
      }
      return { ...advanced, tools: { ...advanced.tools, [event.callId]: { ...tool, result: event } } };
    }
    case "done":
      return { ...advanced, phase: "completed", terminal: event };
    case "error":
      return { ...advanced, phase: event.error.code === "cancelled" ? "cancelled" : "failed", terminal: event };
    default:
      return advanced;
  }
}

export function runReducer(state: RunState, action: RunAction): RunState {
  if (!sameIdentity(state.identity, action.identity)) {
    return issue(state, { kind: "stale", message: "A response for an older attempt or context revision was ignored." });
  }
  if (action.type === "source_status") {
    return { ...state, sourceStatus: action.sourceStatus };
  }
  if (action.type === "cancel_requested") {
    return state.phase === "active" || state.phase === "idle"
      ? { ...state, phase: "cancelling" }
      : state;
  }
  if (action.type === "malformed") {
    return issue(state, { kind: "malformed", message: action.message }, "protocol_error");
  }
  return applyEvent(state, action.event);
}

export function terminalError(state: RunState): ErrorEvent | undefined {
  return state.terminal?.type === "error" ? state.terminal : undefined;
}

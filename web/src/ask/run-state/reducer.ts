import {
  MAX_EVENTS_PER_ATTEMPT,
  STREAM_ENDED_WITHOUT_TERMINAL,
  SCHEMA_VERSION,
  TERMINAL_ERROR_CODES,
  TEXT_DELTA_MAX_BYTES,
} from "./types";
import type {
  ErrorEvent,
  RunAction,
  RunEvent,
  RunIdentity,
  RunState,
  SourceStatus,
  StreamCloseReason,
  TraceIssue,
} from "./types";

const STREAM_CLOSE_MESSAGE: Record<StreamCloseReason, string> = {
  eof: "The stream ended without the required terminal done or error event, so this answer is incomplete.",
  abort: "The stream was aborted before the required terminal done or error event, so this answer is incomplete.",
  network: "The connection was lost before the required terminal done or error event, so this answer is incomplete.",
};

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

const utf8 = new TextEncoder();

function utf8Bytes(value: string): number {
  return utf8.encode(value).length;
}

function isTerminalErrorCode(code: unknown): boolean {
  return typeof code === "string" && (TERMINAL_ERROR_CODES as readonly string[]).includes(code);
}

function applyEvent(state: RunState, event: RunEvent): RunState {
  if (event.v !== SCHEMA_VERSION) {
    return issue(
      state,
      { kind: "unsupported_version", message: `The stream declared schema version ${String(event.v)}; this client only reads v${SCHEMA_VERSION}.`, event },
      "protocol_error",
    );
  }
  if (!Number.isSafeInteger(event.seq) || event.seq < 1 || event.id !== String(event.seq)) {
    return issue(state, { kind: "malformed", message: "The stream event has an invalid or mismatched id/sequence.", event }, "protocol_error");
  }
  if (isTerminal(state)) {
    return issue(state, { kind: "after_terminal", message: "An event arrived after this run had already terminated.", event });
  }
  if (state.trace.length >= MAX_EVENTS_PER_ATTEMPT) {
    return issue(
      state,
      { kind: "limit_exceeded", message: `This attempt exceeded the ${MAX_EVENTS_PER_ATTEMPT}-event v1 limit; the remaining events were not applied.`, event },
      "protocol_error",
    );
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

  // Per-type payload validation runs before the event joins the trace, so an
  // invalid payload never contributes fabricated content or advances the run.
  if (event.type === "text") {
    if (typeof event.delta !== "string") {
      return issue(state, { kind: "malformed", message: "A text event arrived without a string delta; no text was appended.", event }, "protocol_error");
    }
    if (utf8Bytes(event.delta) > TEXT_DELTA_MAX_BYTES) {
      return issue(
        state,
        { kind: "limit_exceeded", message: `A text delta exceeded the ${TEXT_DELTA_MAX_BYTES}-byte v1 limit; no text was appended.`, event },
        "protocol_error",
      );
    }
  }
  if (event.type === "error" && !isTerminalErrorCode(event.error?.code)) {
    return issue(
      state,
      { kind: "invalid_error_code", message: `The terminal error code ${JSON.stringify(event.error?.code)} is not in the closed v1 code set.`, event },
      "protocol_error",
    );
  }

  const advanced = { ...state, expectedSeq: event.seq + 1, trace: [...state.trace, event], phase: state.phase === "idle" ? "active" : state.phase } as RunState;
  switch (event.type) {
    case "text":
      return { ...advanced, text: `${advanced.text}${event.delta}` };
    case "tool_call":
      if (advanced.tools[event.call_id]) {
        return issue(advanced, { kind: "duplicate_call", message: `Tool call ${event.call_id} was emitted more than once.`, event }, "protocol_error");
      }
      return { ...advanced, tools: { ...advanced.tools, [event.call_id]: { callId: event.call_id, tool: event.tool, input: event.input } } };
    case "tool_result": {
      const tool = advanced.tools[event.call_id];
      if (!tool || tool.tool !== event.tool) {
        return issue(advanced, { kind: "unknown_call", message: `Tool result ${event.call_id} has no matching tool call.`, event }, "protocol_error");
      }
      return { ...advanced, tools: { ...advanced.tools, [event.call_id]: { ...tool, result: event } } };
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
  if (action.type === "stream_closed") {
    // OQ-1, decided: the schema guarantees exactly one terminal event per
    // attempt, so a close with neither `done` nor `error` is a broken contract
    // and the run is `failed` -> `request_failed`. A close *after* a terminal
    // event is the normal end of a stream and changes nothing.
    if (isTerminal(state)) return state;
    return {
      ...issue(
        state,
        { kind: "stream_ended_without_terminal", message: STREAM_CLOSE_MESSAGE[action.reason ?? "eof"] },
        "failed",
      ),
      failureCode: STREAM_ENDED_WITHOUT_TERMINAL,
    };
  }
  if (action.type === "malformed") {
    return issue(state, { kind: "malformed", message: action.message }, "protocol_error");
  }
  return applyEvent(state, action.event);
}

export function terminalError(state: RunState): ErrorEvent | undefined {
  return state.terminal?.type === "error" ? state.terminal : undefined;
}

/**
 * The named cause of a failure the server never explained. `undefined` for
 * every run that terminated normally, so a caller cannot mistake a silent
 * close for a server-supplied error.
 */
export function streamFailureCode(state: RunState): RunState["failureCode"] {
  return state.failureCode;
}

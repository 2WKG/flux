/**
 * A browser-local mirror of docs/research/sse-event-schema.md v1.  The SSE
 * parser supplies `id` from the SSE frame; it is deliberately kept separate
 * from the opaque request attempt id.
 */
export type SourceStatus =
  | "source_supported"
  | "source_screened"
  | "hypothetical"
  | "synthetic"
  | "unavailable"
  | "request_failed";

export interface RunIdentity {
  attemptId: string;
  contextRevision: string;
}

interface Envelope {
  id: string;
  /** Wire-supplied and untrusted: the reducer rejects anything but `SCHEMA_VERSION`. */
  v: number;
  seq: number;
}

export interface LifecycleEvent extends Envelope {
  type: "lifecycle";
  status: "started";
}

export interface TextEvent extends Envelope {
  type: "text";
  delta: string;
}

export interface ToolCallEvent extends Envelope {
  type: "tool_call";
  call_id: string;
  tool: string;
  input: unknown;
}

export interface ToolResultEvent extends Envelope {
  type: "tool_result";
  call_id: string;
  tool: string;
  ok: boolean;
  elapsed_ms: number;
  result?: unknown;
  /** A tool-level failure. Its `code` is tool-defined and is NOT the closed terminal-error set. */
  error?: { code: string; message: string };
}

export interface CitationEvent extends Envelope {
  type: "citation";
  citation_id: string;
  doc: string;
  title: string;
  page: number;
  chunk_id: string;
}

export interface DoneEvent extends Envelope {
  type: "done";
  status: "completed";
  verified: boolean;
  unverified_numbers: readonly string[];
  usage?: Record<string, unknown>;
}

/** The closed v1 terminal error code set from the schema document. */
export const TERMINAL_ERROR_CODES = [
  "invalid_request",
  "unavailable",
  "deadline",
  "upstream_error",
  "tool_error",
  "refusal",
  "cancelled",
  "protocol_error",
] as const;

export type TerminalErrorCode = (typeof TERMINAL_ERROR_CODES)[number];

/** The v1 producer limits this consumer enforces on arrival. */
export const SCHEMA_VERSION = 1;
export const TEXT_DELTA_MAX_BYTES = 4 * 1024;
export const MAX_EVENTS_PER_ATTEMPT = 1000;

export interface ErrorEvent extends Envelope {
  type: "error";
  status: "failed";
  error: { code: TerminalErrorCode; message: string; retryable: boolean };
}

export type RunEvent = LifecycleEvent | TextEvent | ToolCallEvent | ToolResultEvent | CitationEvent | DoneEvent | ErrorEvent;

export type RunPhase = "idle" | "active" | "cancelling" | "completed" | "failed" | "cancelled" | "protocol_error";

export interface TraceIssue {
  kind:
    | "stale"
    | "out_of_order"
    | "malformed"
    | "after_terminal"
    | "duplicate_call"
    | "unknown_call"
    | "unsupported_version"
    | "invalid_error_code"
    | "limit_exceeded";
  message: string;
  event?: Pick<RunEvent, "id" | "seq" | "type">;
}

/** Reduced state, not a wire payload: `callId` is this module's own field. */
export interface ToolTrace {
  callId: string;
  tool: string;
  input: unknown;
  result?: ToolResultEvent;
}

export interface RunState {
  identity: RunIdentity;
  sourceStatus: SourceStatus;
  phase: RunPhase;
  expectedSeq: number;
  text: string;
  trace: readonly RunEvent[];
  tools: Readonly<Record<string, ToolTrace>>;
  terminal?: DoneEvent | ErrorEvent;
  issues: readonly TraceIssue[];
}

export type RunAction =
  | { type: "event"; identity: RunIdentity; event: RunEvent }
  | { type: "cancel_requested"; identity: RunIdentity }
  | { type: "source_status"; identity: RunIdentity; sourceStatus: SourceStatus }
  | { type: "malformed"; identity: RunIdentity; message: string };

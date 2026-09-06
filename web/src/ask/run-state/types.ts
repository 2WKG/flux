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
  v: 1;
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
  callId: string;
  tool: string;
  input: unknown;
}

export interface ToolResultEvent extends Envelope {
  type: "tool_result";
  callId: string;
  tool: string;
  ok: boolean;
  elapsedMs: number;
  result?: unknown;
  error?: { code: string; message: string };
}

export interface CitationEvent extends Envelope {
  type: "citation";
  citationId: string;
  doc: string;
  title: string;
  page: number;
  chunkId: string;
}

export interface DoneEvent extends Envelope {
  type: "done";
  status: "completed";
  verified: boolean;
  unverifiedNumbers: readonly string[];
  usage?: Record<string, unknown>;
}

export interface ErrorEvent extends Envelope {
  type: "error";
  status: "failed";
  error: { code: "invalid_request" | "unavailable" | "deadline" | "upstream_error" | "tool_error" | "refusal" | "cancelled" | "protocol_error"; message: string; retryable: boolean };
}

export type RunEvent = LifecycleEvent | TextEvent | ToolCallEvent | ToolResultEvent | CitationEvent | DoneEvent | ErrorEvent;

export type RunPhase = "idle" | "active" | "cancelling" | "completed" | "failed" | "cancelled" | "protocol_error";

export interface TraceIssue {
  kind: "stale" | "out_of_order" | "malformed" | "after_terminal" | "duplicate_call" | "unknown_call";
  message: string;
  event?: Pick<RunEvent, "id" | "seq" | "type">;
}

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

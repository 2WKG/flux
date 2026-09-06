import type { ClientState, NetworkFailureReason } from "../data/client-state";
import {
  STREAM_CLOSE_MESSAGE,
  STREAM_ENDED_WITHOUT_TERMINAL,
  failureStatusFor,
  type FailureKind,
  type FailureStateInput,
  type FailureStatus,
  type StreamCloseReason,
} from "./types";

export type { StreamCloseReason };

const NETWORK_REASON_KIND = {
  unreachable: "network_failure",
  cancelled: "cancelled",
  timeout: "timeout",
  response_too_large: "oversized",
  invalid_options: "failed",
} as const satisfies Record<NetworkFailureReason, FailureKind>;

/** Preserve the existing HTTP client's distinctions in a source-neutral UI. */
export function fromClientState<T>(state: ClientState<T>, retainedContext?: FailureStateInput["retainedContext"]): FailureStateInput | null {
  switch (state.kind) {
    case "loading":
      return { kind: "loading", retainedContext };
    case "empty":
      return { kind: "empty", retainedContext };
    case "unavailable":
      return { kind: "unavailable", message: state.message, retryAfterSeconds: state.retryAfterSeconds, retainedContext };
    case "invalid":
      return { kind: state.reason === "version_mismatch" ? "version_mismatch" : "malformed", message: state.message, retainedContext };
    case "failed":
      return {
        kind: state.source === "network" ? NETWORK_REASON_KIND[state.reason ?? "unreachable"] : "failed",
        message: state.message,
        retainedContext,
      };
    case "ready":
      return null;
  }
}

/**
 * The closed v1 terminal-error code set from `docs/research/sse-event-schema.md`.
 * Adding a code there is a typecheck failure here, not a blank card.
 */
export type SseTerminalErrorCode =
  | "invalid_request"
  | "unavailable"
  | "deadline"
  | "upstream_error"
  | "tool_error"
  | "refusal"
  | "cancelled"
  | "protocol_error";

const SSE_CODE_KIND = {
  invalid_request: "failed",
  unavailable: "unavailable",
  deadline: "timeout",
  upstream_error: "failed",
  tool_error: "failed",
  refusal: "failed",
  cancelled: "cancelled",
  protocol_error: "malformed",
} as const satisfies Record<SseTerminalErrorCode, FailureKind>;

export interface SseTerminalError {
  code: SseTerminalErrorCode | (string & {});
  message?: string;
  retryAfterSeconds?: number | null;
}

/**
 * Map an SSE terminal `error` frame onto the failure surface. An unlisted code
 * is *not* guessed at: it becomes the frozen `request_failed` token with the
 * raw code preserved in `code`, so an unrecognised producer is visible.
 */
export function fromSseTerminalError(
  error: SseTerminalError,
  retainedContext?: FailureStateInput["retainedContext"],
): FailureStateInput {
  const known: FailureKind | undefined = (SSE_CODE_KIND as Record<string, FailureKind>)[error.code];
  return {
    kind: known ?? "failed",
    message: error.message,
    retryAfterSeconds: error.retryAfterSeconds,
    code: error.code,
    retainedContext,
  };
}

/**
 * OQ-1, decided: a stream that closes with neither a terminal `done` nor a
 * terminal `error` is `request_failed`.
 *
 * The kind is `failed` (not `unavailable`: nothing told us a dependency was
 * missing) and the code is the named `stream_ended_without_terminal`, so the
 * screen shows the frozen token plus the cause rather than a prose apology.
 * `retryAfterSeconds` is deliberately absent -- the server supplied no advice.
 */
export function fromStreamClose(
  close: { reason?: StreamCloseReason; message?: string } = {},
  retainedContext?: FailureStateInput["retainedContext"],
): FailureStateInput {
  return {
    kind: "failed",
    message: close.message ?? STREAM_CLOSE_MESSAGE[close.reason ?? "eof"],
    code: STREAM_ENDED_WITHOUT_TERMINAL,
    retainedContext,
  };
}

/** The frozen Gate-0 token a mapped state asserts, or `null` when it asserts none. */
export function statusOf(input: FailureStateInput): FailureStatus | null {
  return failureStatusFor(input.kind);
}

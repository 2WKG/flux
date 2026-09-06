import type { ReactNode } from "react";

import type { AssetStatus } from "../labels";

/**
 * The Gate-0 frozen UI status vocabulary
 * (`docs/design/minnesota-gate-0-approval.md` §3, bound to server fields by
 * `docs/design/minnesota-demo-narrative-ia.md`). It is written once in
 * `src/labels.ts` and re-exported here under the name PR #213 uses for the same
 * union (`SourceStatus` in `src/ask/run-state/types.ts`), so the two surfaces
 * are import-compatible instead of carrying rival vocabularies. Widening the
 * set is a Gate-0 decision, not a code change.
 */
export type SourceStatus = AssetStatus;

/** The two frozen tokens a request-outcome surface is allowed to emit. */
export type FailureStatus = Extract<SourceStatus, "unavailable" | "request_failed">;

/**
 * The finer cause, carried *alongside* the frozen token and never in place of
 * it. A producer that only understands the frozen vocabulary reads `status`; a
 * producer that wants to explain the failure reads `kind` (and `code`).
 */
export type FailureKind =
  | "loading"
  | "empty"
  | "partial"
  | "unavailable"
  | "malformed"
  | "version_mismatch"
  | "network_failure"
  | "cancelled"
  | "timeout"
  | "oversized"
  | "failed";

/**
 * Frozen-token binding for every kind. `null` means the kind is not a request
 * *outcome* status: `loading` is still in flight, and `empty`/`partial` are
 * successful responses whose truth label comes from the result itself.
 */
export const FAILURE_STATUS_BY_KIND = {
  loading: null,
  empty: null,
  partial: null,
  unavailable: "unavailable",
  malformed: "request_failed",
  version_mismatch: "request_failed",
  network_failure: "request_failed",
  cancelled: "request_failed",
  timeout: "request_failed",
  oversized: "request_failed",
  failed: "request_failed",
} as const satisfies Record<FailureKind, FailureStatus | null>;

/** The frozen machine token for a kind, or `null` when the kind asserts none. */
export function failureStatusFor(kind: FailureKind): FailureStatus | null {
  return FAILURE_STATUS_BY_KIND[kind];
}

/**
 * The named cause of the one failure the *client* is entitled to declare on its
 * own: the transport ended (EOF, abort, or network loss) while the run had
 * neither a terminal `done` nor a terminal `error`.
 *
 * `docs/research/sse-event-schema.md` requires exactly one terminal event per
 * attempt -- never both and never neither -- so a stream that closes silently
 * has broken the server's own contract. Per OQ-1
 * (`docs/specs/spec-code-reconciliation.md`) that case is normative
 * `request_failed`, never `unavailable` and never a bare rendered sentence: the
 * dependency was reachable, the request is what failed. The code travels with
 * the frozen token so the surface says *which* failure it is.
 */
export const STREAM_ENDED_WITHOUT_TERMINAL = "stream_ended_without_terminal";

export interface FailureStateInput {
  kind: FailureKind;
  /** Safe, source-supplied explanation. Omit to use the canonical local copy. */
  message?: string;
  /** A source-provided description of what remains usable; it is never inferred. */
  retainedContext?: ReactNode;
  retryAfterSeconds?: number | null;
  /**
   * The raw producer code (e.g. an SSE `error.code`) preserved verbatim so an
   * unrecognised value is visible rather than replaced by a plausible default.
   */
  code?: string;
}

export interface FailureStateProps {
  state: FailureStateInput;
  onRetry?: () => void;
  onReset?: () => void;
}

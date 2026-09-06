import type { ReactNode } from "react";

/**
 * A presentation input, not a request or stream state machine. Producers must
 * supply the actual outcome; this component never turns a failure into data.
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
  | "failed";

export interface FailureStateInput {
  kind: FailureKind;
  /** Safe, source-supplied explanation. Omit to use the canonical local copy. */
  message?: string;
  /** A source-provided description of what remains usable; it is never inferred. */
  retainedContext?: ReactNode;
  retryAfterSeconds?: number | null;
}

export interface FailureStateProps {
  state: FailureStateInput;
  onRetry?: () => void;
  onReset?: () => void;
}

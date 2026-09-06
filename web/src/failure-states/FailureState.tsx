import { failureStatusFor, type FailureKind, type FailureStateProps } from "./types";

const copy = {
  loading: ["Loading", "The request is still in progress."],
  empty: ["Nothing is available", "The source returned no entries for this view."],
  partial: ["Partial result", "Only the source-provided portion of this view is available."],
  unavailable: ["Unavailable", "This source is currently unavailable."],
  malformed: ["Response could not be used", "The response did not match the expected contract."],
  version_mismatch: ["Version mismatch", "The source response uses an incompatible API version."],
  network_failure: ["Connection failed", "The service could not be reached."],
  cancelled: ["Request cancelled", "The request stopped before it returned a complete answer."],
  timeout: ["Request timed out", "The service did not respond before the request deadline."],
  oversized: ["Response too large", "The response exceeded the size limit and was discarded unread."],
  failed: ["Request failed", "The service did not return a usable result."],
} as const satisfies Record<FailureKind, readonly [string, string]>;

const retryable = new Set<FailureKind>([
  "unavailable",
  "network_failure",
  "cancelled",
  "timeout",
  "oversized",
  "failed",
  "malformed",
  "version_mismatch",
]);

/**
 * Reusable, source-neutral recovery surface. It displays supplied context but
 * has no transport, provider, map, or geometry behavior of its own.
 */
export function FailureState({ state, onRetry, onReset }: FailureStateProps) {
  const [heading, fallback] = copy[state.kind];
  const status = failureStatusFor(state.kind);
  const retryDelay = state.retryAfterSeconds ? ` Retry after ${state.retryAfterSeconds} seconds if the source remains unavailable.` : "";
  const message = `${state.message ?? fallback}${state.kind === "unavailable" ? retryDelay : ""}`;
  const role = retryable.has(state.kind) ? "alert" : "status";

  return (
    <section
      aria-label="Request state"
      data-request-state={state.kind}
      data-request-status={status ?? undefined}
      data-request-code={state.code}
      role={role}
    >
      <h2>{heading}</h2>
      <p>{message}</p>
      {state.retainedContext ? <div aria-label="Retained context">{state.retainedContext}</div> : null}
      {onRetry && retryable.has(state.kind) ? <button type="button" onClick={onRetry}>Retry</button> : null}
      {onReset && state.kind !== "loading" ? <button type="button" onClick={onReset}>Reset view</button> : null}
    </section>
  );
}

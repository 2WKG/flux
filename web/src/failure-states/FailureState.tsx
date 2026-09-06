import type { FailureStateProps } from "./types";

const copy = {
  loading: ["Loading", "The request is still in progress."],
  empty: ["Nothing is available", "The source returned no entries for this view."],
  partial: ["Partial result", "Only the source-provided portion of this view is available."],
  unavailable: ["Unavailable", "This source is currently unavailable."],
  malformed: ["Response could not be used", "The response did not match the expected contract."],
  network_failure: ["Connection failed", "The service could not be reached."],
  cancelled: ["Request cancelled", "The request stopped before it returned a complete answer."],
  failed: ["Request failed", "The service did not return a usable result."],
} as const;

const retryable = new Set(["unavailable", "network_failure", "cancelled", "failed", "malformed"]);

/**
 * Reusable, source-neutral recovery surface. It displays supplied context but
 * has no transport, provider, map, or geometry behavior of its own.
 */
export function FailureState({ state, onRetry, onReset }: FailureStateProps) {
  const [heading, fallback] = copy[state.kind];
  const retryDelay = state.retryAfterSeconds ? ` Retry after ${state.retryAfterSeconds} seconds if the source remains unavailable.` : "";
  const message = `${state.message ?? fallback}${state.kind === "unavailable" ? retryDelay : ""}`;
  const role = retryable.has(state.kind) ? "alert" : "status";

  return (
    <section aria-label="Request state" data-request-state={state.kind} role={role}>
      <h2>{heading}</h2>
      <p>{message}</p>
      {state.retainedContext ? <div aria-label="Retained context">{state.retainedContext}</div> : null}
      {onRetry && retryable.has(state.kind) ? <button type="button" onClick={onRetry}>Retry</button> : null}
      {onReset ? <button type="button" onClick={onReset}>Reset view</button> : null}
    </section>
  );
}

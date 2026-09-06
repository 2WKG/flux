import type { ClientState } from "../data/client-state";
import type { FailureStateInput } from "./types";

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
      return { kind: "malformed", message: state.message, retainedContext };
    case "failed":
      return { kind: state.source === "network" ? "network_failure" : "failed", message: state.message, retainedContext };
    case "ready":
      return null;
  }
}

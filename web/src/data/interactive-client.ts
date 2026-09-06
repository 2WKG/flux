/**
 * The HTTP boundary for the interactive cascade routes.
 *
 * `CascadePlaybackPanel` holds no `fetch`; this module is the single place the
 * two POST routes are called, and it reuses the repo's shared transport
 * (`./transport`) and response validator (`./validation`) rather than adding a
 * second fetch implementation.
 *
 * The routes are PR #331's (`codex/2wkg-436-437-http-clean`,
 * `copilot/interactive_routes.py`): `POST /interactive/scenario/edit` and
 * `POST /interactive/cascade`, each answering with that file's `_result()`
 * envelope. No such route exists on `master` yet, so on the shipped build these
 * calls fail and the panel lands in its named `unavailable` state with the
 * transport's own reason — a named fallback, never a fabricated result.
 */
import type { CascadeData } from "../contracts/copilot-tools";
import type {
  CascadeRequest,
  InteractiveEnvelope,
  ScenarioEditData,
  ScenarioEditRequest,
} from "../interactive/CascadePlaybackPanel";
import {
  NETWORK_FAILURE_MESSAGE,
  toClientState,
  transportFailure,
  type ClientState,
  type Transport,
} from "./client-state";
import { fetchWithPolicy } from "./transport";
import { validateJsonResponse } from "./validation";

export const INTERACTIVE_SCENARIO_EDIT_ROUTE = "/interactive/scenario/edit";
export const INTERACTIVE_CASCADE_ROUTE = "/interactive/cascade";

/**
 * PR #331 only serves its one static synthetic context. Sending any other
 * identity would relabel the same baseline, which the route refuses by name.
 */
export const INTERACTIVE_SCENARIO_ID = "interactive";
export const INTERACTIVE_HOUR = 0;
export const INTERACTIVE_SEED = 0;

export type InteractiveFailureKind = "unavailable" | "timeout" | "cancelled" | "failed";

/**
 * The client returns discriminated `ClientState`s; the panel's two callbacks
 * are promises, so a non-ready state is raised as this typed error. `kind`
 * carries the client's own classification so the panel can name the state
 * instead of collapsing every failure into one sentence.
 */
export class InteractiveRequestError extends Error {
  readonly kind: InteractiveFailureKind;

  constructor(kind: InteractiveFailureKind, message: string) {
    super(message);
    this.name = "InteractiveRequestError";
    this.kind = kind;
  }
}

/** Translate a client state into the panel's named failure, with no invented copy. */
export function interactiveFailure(state: ClientState<unknown>): InteractiveRequestError {
  switch (state.kind) {
    case "unavailable":
      return new InteractiveRequestError("unavailable", state.message);
    case "invalid":
      return new InteractiveRequestError("failed", state.message);
    case "empty":
      return new InteractiveRequestError("failed", "The interactive route returned an empty body.");
    case "failed":
      if (state.reason === "cancelled") return new InteractiveRequestError("cancelled", state.message);
      if (state.reason === "timeout") return new InteractiveRequestError("timeout", state.message);
      if (state.reason === "unreachable") return new InteractiveRequestError("unavailable", state.message);
      return new InteractiveRequestError("failed", state.message);
    default:
      return new InteractiveRequestError("unavailable", NETWORK_FAILURE_MESSAGE);
  }
}

function isEnvelope(value: unknown): value is InteractiveEnvelope<unknown> {
  if (typeof value !== "object" || value === null) return false;
  const envelope = value as Record<string, unknown>;
  return typeof envelope.model_fidelity === "string"
    && typeof envelope.network_provenance === "string"
    && Array.isArray(envelope.limitations)
    && envelope.limitations.every((item) => typeof item === "string")
    && typeof envelope.data === "object"
    && envelope.data !== null;
}

async function post<T>(
  transport: Transport,
  route: string,
  body: unknown,
  signal: AbortSignal,
): Promise<InteractiveEnvelope<T>> {
  let state: ClientState<InteractiveEnvelope<T>>;
  try {
    const response = await transport(route, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal,
      retries: 0,
    });
    state = toClientState(
      await validateJsonResponse(
        response,
        (value): value is InteractiveEnvelope<T> => isEnvelope(value),
      ),
      () => false,
    );
  } catch (error) {
    // The shared client already names cancellation, deadline and size failures.
    state = transportFailure<InteractiveEnvelope<T>>(error);
  }
  if (state.kind === "ready") return state.data;
  throw interactiveFailure(state);
}

export interface InteractiveClient {
  prepareEdit(request: ScenarioEditRequest, signal: AbortSignal): Promise<InteractiveEnvelope<ScenarioEditData>>;
  runCascade(request: CascadeRequest, signal: AbortSignal): Promise<InteractiveEnvelope<CascadeData>>;
}

export function createInteractiveClient(transport: Transport = fetchWithPolicy): InteractiveClient {
  return {
    prepareEdit: (request, signal) =>
      post<ScenarioEditData>(transport, INTERACTIVE_SCENARIO_EDIT_ROUTE, request, signal),
    runCascade: (request, signal) =>
      post<CascadeData>(transport, INTERACTIVE_CASCADE_ROUTE, request, signal),
  };
}

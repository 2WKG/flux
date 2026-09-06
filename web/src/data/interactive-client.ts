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

/**
 * The three labels `interactive_labels()` puts on every interactive success
 * body. `copilot/interactive_routes.py`'s `_result()` returns the payload
 * UNWRAPPED — the solver's own keys sit at the top level beside these three,
 * and `_result()` refuses a payload that would shadow any of them — so the
 * body is a flat mapping, not `{data: …}`.
 */
const LABEL_KEYS = ["model_fidelity", "network_provenance", "limitations"] as const;

function isLabelledBody(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const body = value as Record<string, unknown>;
  return typeof body.model_fidelity === "string"
    && typeof body.network_provenance === "string"
    && Array.isArray(body.limitations)
    && body.limitations.every((item) => typeof item === "string");
}

/**
 * Re-nest the flat route body into the shape the panel renders. The labels are
 * lifted out and everything else becomes `data`; nothing is invented and
 * nothing is dropped. The panel keeps one shape whether or not the route ever
 * moves back to a wrapped body.
 */
export function toEnvelope<T>(body: Record<string, unknown>): InteractiveEnvelope<T> {
  const data: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(body)) {
    if ((LABEL_KEYS as readonly string[]).includes(key)) continue;
    data[key] = item;
  }
  return {
    data: data as T,
    model_fidelity: body.model_fidelity as string,
    network_provenance: body.network_provenance as string,
    limitations: body.limitations as readonly string[],
  };
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
    const validated = toClientState(
      await validateJsonResponse(
        response,
        (value): value is Record<string, unknown> => isLabelledBody(value),
      ),
      () => false,
    );
    state = validated.kind === "ready"
      ? { ...validated, data: toEnvelope<T>(validated.data) }
      : (validated as ClientState<InteractiveEnvelope<T>>);
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

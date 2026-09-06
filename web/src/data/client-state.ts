import {
  API_VERSION,
  MALFORMED_RESPONSE_MESSAGE,
  VERSION_MISMATCH_MESSAGE,
  type FailureEnvelope,
  type PayloadGuard,
  type ValidatedJsonResponse,
  validateJsonResponse,
} from "./validation";
import { fetchWithPolicy, type TransportOptions } from "./transport";

/** A single renderable state for all read API and SSE client outcomes. */
export type ClientState<T> =
  | { kind: "loading" }
  | { kind: "ready"; data: T }
  | { kind: "empty" }
  | {
      kind: "unavailable";
      source: "server";
      message: string;
      retryAfterSeconds: number | null;
      requestId: string;
    }
  | {
      kind: "invalid";
      reason: "version_mismatch" | "malformed_response";
      message: typeof VERSION_MISMATCH_MESSAGE | typeof MALFORMED_RESPONSE_MESSAGE;
    }
  | {
      kind: "failed";
      source: "network" | "server";
      /**
       * Why a client-side failure happened. Cancellation, deadline, and
       * size-cap breaches are real, distinct outcomes; collapsing them into
       * "unreachable" would tell a user who cancelled that the service is down.
       */
      reason?: NetworkFailureReason;
      message: string;
      requestId?: string;
    };

/** The client-side causes `createReadApiClient`/`createSseClient` can observe. */
export type NetworkFailureReason =
  | "unreachable"
  | "cancelled"
  | "timeout"
  | "response_too_large"
  | "invalid_options";

export const NETWORK_FAILURE_MESSAGE =
  "Unable to reach the service. Check your connection and try again.";
export const CANCELLED_MESSAGE = "The request was cancelled before it returned a result.";
export const TIMEOUT_MESSAGE =
  "The request timed out before the service responded. Nothing was returned.";
export const RESPONSE_TOO_LARGE_MESSAGE =
  "The response exceeded the client size limit and was discarded unread.";
export const INVALID_OPTIONS_MESSAGE =
  "The request could not be made because its options were invalid.";

export type EmptyGuard<T> = (value: T) => boolean;
export type Transport = typeof fetchWithPolicy;

export interface ReadApiClient {
  get<T>(
    input: RequestInfo | URL,
    isPayload: PayloadGuard<T>,
    isEmpty: EmptyGuard<T>,
    options?: TransportOptions,
  ): Promise<ClientState<T>>;
}

export type SseEventDecoder<TEvent> = (frame: string) => TEvent | null;

export interface SseConnection<TEvent> {
  /** The caller owns frame splitting; this layer only owns HTTP and state. */
  readonly reader: ReadableStreamDefaultReader<Uint8Array>;
  readonly decode: SseEventDecoder<TEvent>;
  close(): void;
}

export interface SseClient {
  connect<TEvent>(
    input: RequestInfo | URL,
    decode: SseEventDecoder<TEvent>,
    options?: Omit<TransportOptions, "method">,
  ): Promise<ClientState<SseConnection<TEvent>>>;
}

function serverFailureState<T>(failure: FailureEnvelope): ClientState<T> {
  if (failure.status === "unavailable" || failure.error.code === "unavailable") {
    return {
      kind: "unavailable",
      source: "server",
      message: failure.error.message,
      retryAfterSeconds: failure.error.retry_after_s,
      requestId: failure.meta.request_id,
    };
  }
  return {
    kind: "failed",
    source: "server",
    message: failure.error.message,
    requestId: failure.meta.request_id,
  };
}

/** Map the response validator's transport-neutral result into renderable UI state. */
export function toClientState<T>(
  result: ValidatedJsonResponse<T>,
  isEmpty: EmptyGuard<T>,
): ClientState<T> {
  switch (result.kind) {
    case "ok":
      return isEmpty(result.data) ? { kind: "empty" } : { kind: "ready", data: result.data };
    case "failure":
      return serverFailureState(result.failure);
    case "version_mismatch":
      return { kind: "invalid", reason: "version_mismatch", message: result.message };
    case "malformed_response":
      return { kind: "invalid", reason: "malformed_response", message: result.message };
  }
}

/** Network and cancellation failures stay distinct from a server unavailable envelope. */
export function networkFailure<T>(): ClientState<T> {
  return {
    kind: "failed",
    source: "network",
    reason: "unreachable",
    message: NETWORK_FAILURE_MESSAGE,
  };
}

function errorName(error: unknown): string {
  return error instanceof Error || (typeof error === "object" && error !== null && "name" in error)
    ? String((error as { name?: unknown }).name ?? "")
    : "";
}

/**
 * Classify a thrown transport error by its `name`, so a cancelled request, an
 * expired deadline, and a discarded oversized body are not all reported as
 * "unable to reach the service". Names (not `instanceof`) are used so a value
 * thrown from another realm still classifies correctly.
 */
export function transportFailure<T>(error: unknown): ClientState<T> {
  switch (errorName(error)) {
    case "AbortError":
      return { kind: "failed", source: "network", reason: "cancelled", message: CANCELLED_MESSAGE };
    case "RequestTimeoutError":
      return { kind: "failed", source: "network", reason: "timeout", message: TIMEOUT_MESSAGE };
    case "ResponseSizeError":
      return {
        kind: "failed",
        source: "network",
        reason: "response_too_large",
        message: RESPONSE_TOO_LARGE_MESSAGE,
      };
    case "RangeError":
      return {
        kind: "failed",
        source: "network",
        reason: "invalid_options",
        message: INVALID_OPTIONS_MESSAGE,
      };
    default:
      return networkFailure();
  }
}

export function createReadApiClient(transport: Transport = fetchWithPolicy): ReadApiClient {
  return {
    async get<T>(
      input: RequestInfo | URL,
      isPayload: PayloadGuard<T>,
      isEmpty: EmptyGuard<T>,
      options: TransportOptions = {},
    ): Promise<ClientState<T>> {
      try {
        const response = await transport(input, { ...options, method: "GET" });
        return toClientState(await validateJsonResponse(response, isPayload), isEmpty);
      } catch (error) {
        return transportFailure(error);
      }
    },
  };
}

function isSseResponse(response: Response): boolean {
  const contentType = response.headers.get("content-type") ?? "";
  return response.ok && contentType.toLowerCase().startsWith("text/event-stream");
}

function connectSignal(callerSignal: AbortSignal | null | undefined): {
  signal: AbortSignal;
  close: () => void;
} {
  const controller = new AbortController();
  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) {
    abortFromCaller();
  } else {
    callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
  }
  return {
    signal: controller.signal,
    close: () => {
      callerSignal?.removeEventListener("abort", abortFromCaller);
      controller.abort();
    },
  };
}

/**
 * Create the POST/SSE typed client. Event framing/parsing remains a caller
 * concern, while this client applies the shared transport and response states.
 */
export function createSseClient(transport: Transport = fetchWithPolicy): SseClient {
  return {
    async connect<TEvent>(
      input: RequestInfo | URL,
      decode: SseEventDecoder<TEvent>,
      options: Omit<TransportOptions, "method"> = {},
    ): Promise<ClientState<SseConnection<TEvent>>> {
      const { signal: callerSignal, ...requestOptions } = options;
      const request = connectSignal(callerSignal);
      try {
        const response = await transport(input, {
          ...requestOptions,
          method: "POST",
          signal: request.signal,
        });
        if (isSseResponse(response) && response.body) {
          const reader = response.body.getReader();
          return {
            kind: "ready",
            data: {
              reader,
              decode,
              close: () => {
                void reader.cancel().catch(() => undefined);
                request.close();
              },
            },
          };
        }
        request.close();
        return toClientState(
          await validateJsonResponse(response, (_value): _value is never => false),
          () => false,
        );
      } catch (error) {
        request.close();
        return transportFailure(error);
      }
    },
  };
}

export { API_VERSION, MALFORMED_RESPONSE_MESSAGE, VERSION_MISMATCH_MESSAGE };

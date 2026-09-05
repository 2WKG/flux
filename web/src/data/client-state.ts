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
  | { kind: "failed"; source: "network" | "server"; message: string; requestId?: string };

export const NETWORK_FAILURE_MESSAGE =
  "Unable to reach the service. Check your connection and try again.";

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
  return { kind: "failed", source: "network", message: NETWORK_FAILURE_MESSAGE };
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
      } catch {
        return networkFailure();
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
      } catch {
        request.close();
        return networkFailure();
      }
    },
  };
}

export { API_VERSION, MALFORMED_RESPONSE_MESSAGE, VERSION_MISMATCH_MESSAGE };

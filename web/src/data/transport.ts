/**
 * The shared HTTP policy for Flux's read-only browser client.
 *
 * A timeout applies to each fetch attempt and returned response body. Callers
 * can cancel the complete request with `signal`; cancellation is never retried.
 * Automatic retries are deliberately limited to safe read-like methods (GET,
 * HEAD, OPTIONS), so a transient network failure cannot repeat a mutation.
 */
export const DEFAULT_TIMEOUT_MS = 10_000;
export const DEFAULT_RETRIES = 2;
/** Default maximum body size for a read response (5 MiB). */
export const DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024;
/** A healthy SSE connection sends the server heartbeat every 10 seconds. */
export const DEFAULT_SSE_IDLE_TIMEOUT_MS = 30_000;
export const SAFE_RETRY_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export type FetchImplementation = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface TransportOptions extends RequestInit {
  /** Per-attempt timeout. Must be a positive, finite number. */
  timeoutMs?: number;
  /** Number of retry attempts after the initial request (0–5). */
  retries?: number;
  /**
   * Maximum response-body size in bytes. Set a smaller endpoint-specific cap
   * for compact JSON endpoints; layer/Arrow callers can opt into their known
   * larger limit.
   */
  maxResponseBytes?: number;
  /** Injected only for deterministic tests; production uses global fetch. */
  fetchImplementation?: FetchImplementation;
}

export class RequestTimeoutError extends Error {
  constructor(public readonly timeoutMs: number) {
    super(`Request timed out after ${timeoutMs} ms`);
    this.name = "RequestTimeoutError";
  }
}

export class ResponseSizeError extends Error {
  constructor(public readonly maxResponseBytes: number) {
    super(`Response body exceeds the ${maxResponseBytes}-byte limit`);
    this.name = "ResponseSizeError";
  }
}

const RETRIABLE_STATUSES = new Set([408, 429, 500, 502, 503, 504]);
const MAX_RETRIES = 5;

function validatedTimeout(timeoutMs: number | undefined): number {
  const value = timeoutMs ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isFinite(value) || value <= 0) {
    throw new RangeError("timeoutMs must be a positive, finite number");
  }
  return value;
}

function validatedRetries(retries: number | undefined): number {
  const value = retries ?? DEFAULT_RETRIES;
  if (!Number.isInteger(value) || value < 0 || value > MAX_RETRIES) {
    throw new RangeError(`retries must be an integer between 0 and ${MAX_RETRIES}`);
  }
  return value;
}

function validatedMaxResponseBytes(maxResponseBytes: number | undefined): number {
  const value = maxResponseBytes ?? DEFAULT_MAX_RESPONSE_BYTES;
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new RangeError("maxResponseBytes must be a positive, safe integer");
  }
  return value;
}

function retryDelayMs(retryNumber: number): number {
  // 100 ms, 200 ms, then 400 ms; bounded even if the maximum is increased.
  return Math.min(100 * 2 ** (retryNumber - 1), 1_000);
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function shouldRetryResponse(response: Response): boolean {
  return RETRIABLE_STATUSES.has(response.status);
}

function canRetry(method: string, attempt: number, retries: number): boolean {
  return SAFE_RETRY_METHODS.has(method) && attempt < retries;
}

function abortableDelay(delayMs: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason ?? new DOMException("Request aborted", "AbortError"));
      return;
    }

    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, delayMs);
    const onAbort = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      reject(signal.reason ?? new DOMException("Request aborted", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

async function fetchAttempt(
  input: RequestInfo | URL,
  init: RequestInit,
  timeoutMs: number,
  callerSignal: AbortSignal | null | undefined,
  fetchImplementation: FetchImplementation,
): Promise<Response> {
  const timeoutController = new AbortController();
  const requestController = new AbortController();
  const timeout = setTimeout(() => timeoutController.abort(), timeoutMs);

  const onCallerAbort = () => requestController.abort(callerSignal?.reason);
  const onTimeout = () => requestController.abort(timeoutController.signal.reason);
  callerSignal?.addEventListener("abort", onCallerAbort, { once: true });
  timeoutController.signal.addEventListener("abort", onTimeout, { once: true });

  try {
    return await fetchImplementation(input, { ...init, signal: requestController.signal });
  } catch (error) {
    if (callerSignal?.aborted) {
      throw error;
    }
    if (timeoutController.signal.aborted) {
      throw new RequestTimeoutError(timeoutMs);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    callerSignal?.removeEventListener("abort", onCallerAbort);
    timeoutController.signal.removeEventListener("abort", onTimeout);
  }
}

async function cancelResponseBody(response: Response): Promise<void> {
  try {
    await response.body?.cancel();
  } catch {
    // Retrying must not be blocked by an already-broken discarded body.
  }
}

function responseInit(response: Response): ResponseInit {
  return {
    headers: response.headers,
    status: response.status,
    statusText: response.statusText,
  };
}

async function responseWithBoundedBody(
  response: Response,
  timeoutMs: number,
  maxResponseBytes: number,
): Promise<Response> {
  if (response.body === null) {
    return response;
  }

  const contentLength = response.headers.get("content-length");
  if (contentLength !== null && Number(contentLength) > maxResponseBytes) {
    await cancelResponseBody(response);
    throw new ResponseSizeError(maxResponseBytes);
  }

  const reader = response.body.getReader();
  let bytesRead = 0;
  let terminalError: Error | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const finish = () => {
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
  };
  const fail = (error: Error) => {
    if (terminalError !== undefined) {
      return;
    }
    terminalError = error;
    finish();
    void reader.cancel(error).catch(() => undefined);
  };

  timer = setTimeout(() => fail(new RequestTimeoutError(timeoutMs)), timeoutMs);

  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (terminalError !== undefined) {
        controller.error(terminalError);
        return;
      }

      try {
        const { done, value } = await reader.read();
        if (terminalError !== undefined) {
          controller.error(terminalError);
          return;
        }
        if (done) {
          finish();
          controller.close();
          return;
        }

        bytesRead += value.byteLength;
        if (bytesRead > maxResponseBytes) {
          const error = new ResponseSizeError(maxResponseBytes);
          fail(error);
          controller.error(error);
          return;
        }
        controller.enqueue(value);
      } catch (error) {
        finish();
        controller.error(terminalError ?? error);
      }
    },
    async cancel(reason) {
      finish();
      await reader.cancel(reason);
    },
  });

  return new Response(body, responseInit(response));
}

async function responseWithSseIdleBody(response: Response): Promise<Response> {
  if (response.body === null) {
    return response;
  }

  const reader = response.body.getReader();
  let terminalError: RequestTimeoutError | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const clearIdleTimer = () => {
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
  };
  const failForIdle = () => {
    if (terminalError !== undefined) {
      return;
    }
    terminalError = new RequestTimeoutError(DEFAULT_SSE_IDLE_TIMEOUT_MS);
    clearIdleTimer();
    void reader.cancel(terminalError).catch(() => undefined);
  };
  const resetIdleTimer = () => {
    clearIdleTimer();
    timer = setTimeout(failForIdle, DEFAULT_SSE_IDLE_TIMEOUT_MS);
  };

  resetIdleTimer();
  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (terminalError !== undefined) {
        controller.error(terminalError);
        return;
      }

      try {
        const { done, value } = await reader.read();
        if (terminalError !== undefined) {
          controller.error(terminalError);
          return;
        }
        if (done) {
          clearIdleTimer();
          controller.close();
          return;
        }
        resetIdleTimer();
        controller.enqueue(value);
      } catch (error) {
        clearIdleTimer();
        controller.error(terminalError ?? error);
      }
    },
    async cancel(reason) {
      clearIdleTimer();
      await reader.cancel(reason);
    },
  });

  return new Response(body, responseInit(response));
}

function isSseResponse(response: Response): boolean {
  return response.headers.get("content-type")?.toLowerCase().startsWith("text/event-stream") ?? false;
}

/**
 * Fetch with Flux's browser-safe policy. It returns the final Response so
 * response-envelope validation remains owned by the client validation layer.
 */
export async function fetchWithPolicy(
  input: RequestInfo | URL,
  options: TransportOptions = {},
): Promise<Response> {
  const {
    timeoutMs: requestedTimeout,
    retries: requestedRetries,
    maxResponseBytes: requestedMaxResponseBytes,
    fetchImplementation = fetch,
    signal: callerSignal,
    method: requestedMethod,
    ...init
  } = options;
  const timeoutMs = validatedTimeout(requestedTimeout);
  const retries = validatedRetries(requestedRetries);
  const maxResponseBytes = validatedMaxResponseBytes(requestedMaxResponseBytes);
  const method = (requestedMethod ?? "GET").toUpperCase();
  const signal = callerSignal ?? new AbortController().signal;

  if (signal.aborted) {
    throw signal.reason ?? new DOMException("Request aborted", "AbortError");
  }

  for (let attempt = 0; ; attempt += 1) {
    try {
      const response = await fetchAttempt(
        input,
        { ...init, method },
        timeoutMs,
        signal,
        fetchImplementation,
      );
      if (!shouldRetryResponse(response) || !canRetry(method, attempt, retries)) {
        if (isSseResponse(response)) {
          return responseWithSseIdleBody(response);
        }
        return responseWithBoundedBody(response, timeoutMs, maxResponseBytes);
      }
      await cancelResponseBody(response);
    } catch (error) {
      if (
        signal.aborted
        || isAbortError(error)
        || error instanceof ResponseSizeError
        || !canRetry(method, attempt, retries)
      ) {
        throw error;
      }
    }

    await abortableDelay(retryDelayMs(attempt + 1), signal);
  }
}

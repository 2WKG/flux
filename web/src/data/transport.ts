/**
 * The shared HTTP policy for Flux's read-only browser client.
 *
 * A timeout applies to each fetch attempt. Callers can cancel the complete
 * request with `signal`; cancellation is never retried. Automatic retries are
 * deliberately limited to safe read-like methods (GET, HEAD, OPTIONS), so a
 * transient network failure cannot repeat a mutation.
 */
export const DEFAULT_TIMEOUT_MS = 10_000;
export const DEFAULT_RETRIES = 2;
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
  /** Injected only for deterministic tests; production uses global fetch. */
  fetchImplementation?: FetchImplementation;
}

export class RequestTimeoutError extends Error {
  constructor(public readonly timeoutMs: number) {
    super(`Request timed out after ${timeoutMs} ms`);
    this.name = "RequestTimeoutError";
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
    fetchImplementation = fetch,
    signal: callerSignal,
    method: requestedMethod,
    ...init
  } = options;
  const timeoutMs = validatedTimeout(requestedTimeout);
  const retries = validatedRetries(requestedRetries);
  const method = (requestedMethod ?? "GET").toUpperCase();
  const signal = callerSignal ?? new AbortController().signal;

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
        return response;
      }
    } catch (error) {
      if (signal.aborted || isAbortError(error) || !canRetry(method, attempt, retries)) {
        throw error;
      }
    }

    await abortableDelay(retryDelayMs(attempt + 1), signal);
  }
}

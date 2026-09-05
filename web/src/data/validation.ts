/** Runtime validation for the Copilot HTTP contract's JSON responses.
 *
 * The API intentionally envelopes failures only: successful route payloads
 * stay unwrapped because some routes return arrays or Arrow bytes. A caller
 * supplies a narrow guard before a successful JSON payload is used. Invalid
 * data and incompatible envelope versions become safe, stable client states;
 * server-provided details are never used as their display messages.
 *
 * Failure envelopes are checked strictly on their required fields (presence,
 * type, range) and tolerantly on additive ones: a server that adds a field to
 * `error`, `meta`, or the envelope root must not turn every failure into
 * "invalid response". Because success payloads are unwrapped, `api_version`
 * (and therefore a version mismatch) is only observable on failure envelopes;
 * success payloads are validated by their route guards alone.
 */
export const API_VERSION = "v1";

export const VERSION_MISMATCH_MESSAGE =
  "The service returned an incompatible response. Refresh and try again.";
export const MALFORMED_RESPONSE_MESSAGE =
  "The service returned an invalid response. Try again.";

export type FailureStatus = "unavailable" | "error";
export type FailureCode = "unavailable" | "invalid_input" | "not_found" | "internal_error";

export interface FailureEnvelope {
  status: FailureStatus;
  data: null;
  error: {
    code: FailureCode;
    message: string;
    retryable: boolean;
    retry_after_s: number | null;
    details: Record<string, string>;
  };
  meta: {
    api_version: typeof API_VERSION;
    request_id: string;
    generated_at: string;
  };
}

export type PayloadGuard<T> = (value: unknown) => value is T;

export type ValidatedJsonResponse<T> =
  | { kind: "ok"; data: T; requestId: string | null }
  | { kind: "failure"; failure: FailureEnvelope }
  | {
      kind: "version_mismatch";
      expectedVersion: typeof API_VERSION;
      receivedVersion: string;
      message: typeof VERSION_MISMATCH_MESSAGE;
    }
  | { kind: "malformed_response"; message: typeof MALFORMED_RESPONSE_MESSAGE };

type ParsedFailure =
  | { kind: "failure"; failure: FailureEnvelope }
  | { kind: "version_mismatch"; receivedVersion: string }
  | { kind: "malformed" };

const FAILURE_CODES = new Set<FailureCode>([
  "unavailable",
  "invalid_input",
  "not_found",
  "internal_error",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown, maximumLength: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximumLength;
}

function isUtcTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || Number.isNaN(Date.parse(value))) {
    return false;
  }
  return /(?:Z|[+-]00:00)$/.test(value);
}

function parseFailureEnvelope(value: unknown): ParsedFailure {
  if (!isRecord(value) || !isRecord(value.meta)) {
    return { kind: "malformed" };
  }

  const version = value.meta.api_version;
  if (typeof version === "string" && version !== API_VERSION) {
    return { kind: "version_mismatch", receivedVersion: version };
  }

  if (
    (value.status !== "unavailable" && value.status !== "error") ||
    value.data !== null ||
    !isRecord(value.error) ||
    !FAILURE_CODES.has(value.error.code as FailureCode) ||
    !isNonEmptyString(value.error.message, 1_024) ||
    typeof value.error.retryable !== "boolean" ||
    !(
      value.error.retry_after_s === null ||
      (Number.isInteger(value.error.retry_after_s) &&
        (value.error.retry_after_s as number) >= 1 &&
        (value.error.retry_after_s as number) <= 3_600)
    ) ||
    !isRecord(value.error.details) ||
    Object.keys(value.error.details).length > 10 ||
    !Object.entries(value.error.details).every(
      ([key, detail]) => typeof key === "string" && typeof detail === "string",
    ) ||
    version !== API_VERSION ||
    !isNonEmptyString(value.meta.request_id, 64) ||
    !isUtcTimestamp(value.meta.generated_at)
  ) {
    return { kind: "malformed" };
  }

  return { kind: "failure", failure: value as unknown as FailureEnvelope };
}

function isFailureCandidate(value: unknown): boolean {
  return isRecord(value) && (value.status === "unavailable" || value.status === "error");
}

/**
 * Parse a JSON response without exposing malformed payload content to callers.
 *
 * Successful payloads must satisfy `isPayload`. Non-JSON routes such as Arrow
 * IPC are intentionally outside this function and are validated by their own
 * binary decoders.
 */
export async function validateJsonResponse<T>(
  response: Response,
  isPayload: PayloadGuard<T>,
): Promise<ValidatedJsonResponse<T>> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return { kind: "malformed_response", message: MALFORMED_RESPONSE_MESSAGE };
  }

  if (isFailureCandidate(body) || !response.ok) {
    const parsed = parseFailureEnvelope(body);
    if (parsed.kind === "failure") {
      return parsed;
    }
    if (parsed.kind === "version_mismatch") {
      return {
        kind: "version_mismatch",
        expectedVersion: API_VERSION,
        receivedVersion: parsed.receivedVersion,
        message: VERSION_MISMATCH_MESSAGE,
      };
    }
    return { kind: "malformed_response", message: MALFORMED_RESPONSE_MESSAGE };
  }

  if (!isPayload(body)) {
    return { kind: "malformed_response", message: MALFORMED_RESPONSE_MESSAGE };
  }

  return { kind: "ok", data: body, requestId: response.headers.get("X-Request-ID") };
}

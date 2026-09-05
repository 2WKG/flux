import {
  MALFORMED_RESPONSE_MESSAGE,
  VERSION_MISMATCH_MESSAGE,
  type ClientState,
} from "./client-state";

// A compile-time contract: every renderable state has the fields a UI needs.
const everyState: ClientState<null>[] = [
  { kind: "loading" },
  { kind: "ready", data: null },
  { kind: "empty" },
  {
    kind: "unavailable",
    source: "server",
    message: "Artifact is not built.",
    retryAfterSeconds: 30,
    requestId: "request-123",
  },
  {
    kind: "invalid",
    reason: "version_mismatch",
    message: VERSION_MISMATCH_MESSAGE,
  },
  {
    kind: "invalid",
    reason: "malformed_response",
    message: MALFORMED_RESPONSE_MESSAGE,
  },
  {
    kind: "failed",
    source: "network",
    message: "Unable to reach the service.",
  },
  {
    kind: "failed",
    source: "server",
    message: "The server rejected the request.",
    requestId: "request-456",
  },
];

void everyState;

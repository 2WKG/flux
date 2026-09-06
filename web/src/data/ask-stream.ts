/**
 * The chat/results/run-trace read path: `POST /ask` as `text/event-stream`
 * (`copilot/routes/ask.py:139`), framed per `docs/research/sse-event-schema.md`.
 *
 * `src/data/client-state.ts` owns HTTP and the connection state and says frame
 * splitting is the caller's job; this module is that caller. It does three
 * things and nothing else:
 *
 * 1. Splits the byte stream on the SSE blank-line frame boundary and decodes
 *    each `data:` payload into a `RunEvent`. A frame that is not one is a
 *    named `malformed` action, never a dropped event.
 * 2. Feeds `runReducer`, which already owns ordering, limits, and the closed
 *    terminal-error set. Nothing about run semantics is restated here.
 * 3. Applies the terminal rule: a stream that closes without exactly one
 *    terminal `done` XOR `error` is a **failed request**, not a quiet end.
 *    `docs/design/texas-demo-narrative-ia.md` states the rule; before this it
 *    was implemented nowhere, so a truncated stream simply stopped.
 */

import { createSseClient, type ClientState, type SseClient } from "./client-state";
import { runReducer } from "../ask/run-state/reducer";
import type { RunAction, RunEvent, RunIdentity, RunState } from "../ask/run-state/types";
import type { AskRequestBody } from "../chat/ask-contract";

/** The named code a stream that ended with no terminal frame carries. */
export const NO_TERMINAL_EVENT_CODE = "protocol_error";
export const NO_TERMINAL_EVENT_MESSAGE =
  "The stream closed without a terminal done or error event, so the answer is not complete and no result is shown.";

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Decode one SSE frame's `data:` lines into a run event. Returns `null` for a
 * comment/heartbeat frame (which is not an event) and throws nothing: a frame
 * that carries data but is not an event becomes `undefined` so the caller can
 * raise it as `malformed` rather than skip it.
 */
export function decodeFrame(frame: string): RunEvent | null | undefined {
  const data = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (data === "") return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return undefined;
  }
  if (!record(parsed) || typeof parsed.type !== "string" || typeof parsed.id !== "string"
    || typeof parsed.seq !== "number" || typeof parsed.v !== "number") return undefined;
  return parsed as unknown as RunEvent;
}

/** Split a decoded chunk buffer into complete frames plus the unterminated tail. */
export function splitFrames(buffer: string): { frames: readonly string[]; rest: string } {
  const parts = buffer.split(/\r?\n\r?\n/);
  const rest = parts.pop() ?? "";
  return { frames: parts.filter((frame) => frame.trim() !== ""), rest };
}

export type AskStreamOutcome = {
  /** The reduced run, whatever happened. It is never fabricated or back-filled. */
  readonly state: RunState;
  /** Present when the connection itself never produced a stream. */
  readonly connection?: Exclude<ClientState<never>, { kind: "ready" }>;
};

/**
 * Open `POST /ask`, reduce every frame, and return the final run state.
 *
 * `initial` is the caller's own `createRunState(identity, sourceStatus)`: the
 * source status is supplied by the scene owner and never inferred here.
 */
export async function runAsk(
  body: AskRequestBody,
  identity: RunIdentity,
  initial: RunState,
  options: { client?: SseClient; signal?: AbortSignal; onState?: (state: RunState) => void } = {},
): Promise<AskStreamOutcome> {
  const client = options.client ?? createSseClient();
  let state = initial;
  const dispatch = (action: RunAction) => {
    state = runReducer(state, action);
    options.onState?.(state);
  };

  const connection = await client.connect<RunEvent | null | undefined>(
    "/ask",
    decodeFrame,
    {
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      body: JSON.stringify(body),
      ...(options.signal ? { signal: options.signal } : {}),
    },
  );
  if (connection.kind !== "ready") {
    return { state, connection: connection as Exclude<ClientState<never>, { kind: "ready" }> };
  }

  const decoder = new TextDecoder();
  let buffer = "";
  let closeReason: "eof" | "network" = "eof";
  try {
    for (;;) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await connection.data.reader.read();
      } catch (error) {
        // A caller-directed abort is intentional cancellation, not a stream
        // failure. The caller retains the rejected promise in that case -- but
        // the run still has to stop being `streaming`. Re-throwing straight out
        // of here skipped the `stream_closed` dispatch at the end of this
        // function entirely (the `finally` only closes the connection), so an
        // aborted run kept whatever phase it had and `chatStatusForRun` would
        // report `streaming` forever. Declare the close first, with its own
        // reason, and only then re-throw.
        if (options.signal?.aborted) {
          dispatch({ type: "stream_closed", identity, reason: "abort" });
          throw error; // `finally` below still closes the connection.
        }

        // Browser idle timeouts and broken sockets reject read() after the
        // stream was accepted instead of yielding EOF. Route that path through
        // the same single closure action as ordinary EOF.
        closeReason = "network";
        break;
      }
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const { frames, rest } = splitFrames(buffer);
      buffer = rest;
      for (const frame of frames) {
        const event = connection.data.decode(frame);
        if (event === null) continue;
        if (event === undefined) {
          dispatch({ type: "malformed", identity, message: "A stream frame was not a v1 event and was not applied." });
          continue;
        }
        dispatch({ type: "event", identity, event });
      }
    }
  } finally {
    connection.data.close();
  }

  dispatch({ type: "stream_closed", identity, reason: closeReason });
  return { state };
}

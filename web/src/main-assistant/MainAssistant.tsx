/**
 * The one chat seam of the main page.
 *
 * `src/pages/MainPage.tsx` mounts this and nothing else for chat: the third
 * parallel assembly of `ChatDock` + `RunTrace` that the page used to inline is
 * gone, so there is exactly one place where the reducer-validated `/ask` state
 * becomes a chat surface.
 *
 * It owns no provider selection, transport, scene mutation, or event parsing:
 * the caller supplies the reducer state produced from the one same-origin
 * `/ask` SSE stream, and every status, error, and availability claim below is
 * derived from that state.
 */
import { ChatDock, type ChatDockProps, type ChatError, type ChatStatus } from "../chat/ChatDock";
import { RunTrace } from "../ask/run-state/RunTrace";
import { streamFailureCode } from "../ask/run-state/reducer";
import { STREAM_ENDED_WITHOUT_TERMINAL } from "../ask/run-state/types";
import type { RunIdentity, RunState, ToolResultEvent } from "../ask/run-state/types";
import { FailureState } from "../failure-states/FailureState";
import { fromStreamClose } from "../failure-states/adapters";
// The generated browser mirror of `copilot/tools/schemas.py`. Every tool output
// the v1 `/ask` contract can carry is one of these, and each declares its own
// `status`. The shapes are imported, never restated here.
import type { ToolOutput, ToolStatus, Unavailable } from "../contracts/copilot-tools";

/**
 * What the caller knows that the stream itself has not said yet. It is narrow
 * on purpose: the run is the authority for everything that happened *inside* a
 * stream, and this only covers the window before one exists.
 */
export interface RequestOverlay {
  /** A `POST /ask` is in flight and no event has been reduced yet. */
  readonly pending?: boolean;
  /**
   * The connection never produced a stream at all (HTTP or network failure), so
   * there is no run to derive from. Ignored the moment the run leaves `idle`:
   * once events exist, the reducer outranks the caller.
   */
  readonly connectionError?: ChatError;
}

export interface MainAssistantProps {
  /**
   * Chat inputs and callbacks, excluding stream-derived fields.  The stream
   * state below is the only authority for status and terminal errors.
   */
  readonly chat: Omit<ChatDockProps, "status" | "error" | "onCancel">;
  /** Arrival-ordered, reducer-validated state for exactly `chat.attemptId`. */
  readonly run: RunState;
  /** Abort the caller-owned SSE request; cancellation remains pending until an error event confirms it. */
  readonly onCancelRun?: (identity: RunIdentity) => void;
  readonly request?: RequestOverlay;
}

/**
 * Whether the received tool results carry scene-usable evidence.
 *
 * The v1 `/ask` contract has no action, geometry, attribution, or reversal
 * field, so this never says *what* the scene should do -- no scene mutation is
 * inferred from a tool name, from answer prose, or from any field an arbitrary
 * result object happens to contain. What the contract *does* declare is
 * `ToolOutput.status` (`copilot-tools.d.ts`: `"available" | "unavailable"`),
 * and that is the only thing read here.
 */
export type SceneActionAvailability =
  | {
      readonly availability: "unavailable";
      readonly reason:
        /** No received tool result carried a contract-shaped output at all. */
        | "absent_from_received_ask_event_data"
        /** A contract-shaped output arrived and declared itself unavailable. */
        | "declared_unavailable_by_received_tool_output";
      /** The producer's own explanation, verbatim, when it supplied one. */
      readonly unavailable?: Unavailable;
    }
  | {
      readonly availability: "available";
      /** The received event this claim is read from; never a synthesized one. */
      readonly result: ToolResultEvent;
      /** `ToolOutput.status` as the producer sent it. */
      readonly status: Extract<ToolStatus, "available">;
    };

const NO_SCENE_ACTION: SceneActionAvailability = {
  availability: "unavailable",
  reason: "absent_from_received_ask_event_data",
};

/**
 * Narrow an untrusted `tool_result.result` to the contract's `ToolOutput`.
 *
 * A payload without a `status` of exactly `"available"` or `"unavailable"` is
 * not a v1 tool output and is not guessed at: a result carrying, say, a
 * `scene_action` field but no contract status stays invisible to this function.
 */
function toolOutput(value: unknown): ToolOutput | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
  const status = (value as { status?: unknown }).status;
  return status === "available" || status === "unavailable" ? (value as ToolOutput) : undefined;
}

/**
 * Derive the availability from the run's received tool results, in the order
 * the calls arrived. The first contract-shaped output that declares itself
 * available wins; otherwise a declared-unavailable output is reported with the
 * producer's own reason, and only a run with neither is "absent".
 */
export function sceneActionAvailability(run: RunState): SceneActionAvailability {
  let declinedBy: Unavailable | undefined;
  let declined = false;
  for (const trace of Object.values(run.tools)) {
    const result = trace.result;
    if (!result?.ok) continue;
    const output = toolOutput(result.result);
    if (!output) continue;
    if (output.status === "available") {
      return { availability: "available", result, status: "available" };
    }
    declined = true;
    declinedBy = declinedBy ?? output.unavailable ?? undefined;
  }
  if (!declined) return NO_SCENE_ACTION;
  return {
    availability: "unavailable",
    reason: "declared_unavailable_by_received_tool_output",
    ...(declinedBy ? { unavailable: declinedBy } : {}),
  };
}

/** Translate only reducer-confirmed phases to the dock's visible status. */
export function chatStatusForRun(run: RunState, request: RequestOverlay = {}): ChatStatus {
  switch (run.phase) {
    case "completed":
      return "done";
    case "failed":
    case "protocol_error":
      return "error";
    case "cancelled":
      return "cancelled";
    case "active":
    case "cancelling":
      return "streaming";
    case "idle":
      // No event has been reduced. Only here may the caller's own knowledge of
      // the request speak, and a failure outranks an in-flight claim.
      if (request.connectionError) return "error";
      return request.pending ? "streaming" : "idle";
  }
}

/** Pass the server terminal error through unchanged; never synthesize one. */
export function chatErrorForRun(run: RunState, request: RequestOverlay = {}): ChatError | undefined {
  const terminal = run.terminal;
  if (terminal?.type === "error") {
    return {
      code: terminal.error.code,
      message: terminal.error.message,
      retryable: terminal.error.retryable,
    };
  }
  if (run.phase === "idle" && request.connectionError) return request.connectionError;
  return undefined;
}

/**
 * OQ-1, decided: a stream that closed with neither a terminal `done` nor a
 * terminal `error` is `request_failed`.
 *
 * `src/data/ask-stream.ts` dispatches the `stream_closed` action on every EOF,
 * abort, and broken read, and the reducer sets `failureCode` when no terminal
 * event had arrived. This turns that state into the frozen request-outcome
 * surface: `FailureState` emits `data-request-status="request_failed"` and
 * `data-request-code="stream_ended_without_terminal"`, so the screen shows the
 * machine token and the named cause instead of a bare sentence. `undefined` for
 * every run that ended normally.
 */
export function streamCloseFailure(run: RunState) {
  if (streamFailureCode(run) !== STREAM_ENDED_WITHOUT_TERMINAL) return undefined;
  // The reducer already recorded the close reason's own copy; the adapter owns
  // the token and the kind. Neither is re-spelled here.
  const recorded = [...run.issues].reverse().find((issue) => issue.kind === "stream_ended_without_terminal");
  return fromStreamClose(recorded ? { message: recorded.message } : {});
}

function groundingCopy(run: RunState): string {
  if (run.terminal?.type === "done") {
    return run.terminal.verified
      ? "Verified against the received tool results and citations."
      : "The server reported unresolved answer evidence; review the received trace before relying on this response.";
  }
  if (run.terminal?.type === "error") {
    return run.terminal.error.code === "unavailable"
      ? "The requested provider or prerequisite is unavailable. No answer or scene action was inferred."
      : "The server ended this attempt with an error. No answer or scene action was inferred."
  }
  if (streamFailureCode(run) === STREAM_ENDED_WITHOUT_TERMINAL) {
    return "The stream closed before the server sent its one required terminal event, so this attempt has no result. No answer or scene action was inferred.";
  }
  return "Waiting for ordered tool results from the same-origin /ask stream. Scene actions are not inferred while a run is active.";
}

/**
 * Render the page's assistant. The page shell, routing, and transport stay
 * outside; everything this shows is read from `run`.
 */
export function MainAssistant({ chat, run, onCancelRun, request }: MainAssistantProps) {
  const sceneAction = sceneActionAvailability(run);
  const status = chatStatusForRun(run, request);
  const error = chatErrorForRun(run, request);
  const streamClose = streamCloseFailure(run);

  return (
    <section className="flux-main-assistant" aria-label="Main page assistant">
      <header className="flux-main-assistant__header">
        <p>Tool-grounded assistant</p>
        <h2>Ask Flux about the active scene</h2>
      </header>
      <p className="flux-main-assistant__grounding" data-grounding-phase={run.phase}>
        {groundingCopy(run)}
      </p>
      <section
        className="flux-main-assistant__scene-action"
        aria-label="Scene action availability"
        data-scene-action-availability={sceneAction.availability}
        data-scene-action-reason={sceneAction.availability === "unavailable" ? sceneAction.reason : undefined}
        data-scene-action-call={sceneAction.availability === "available" ? sceneAction.result.call_id : undefined}
      >
        <strong>Scene response</strong>
        {sceneAction.availability === "unavailable" ? (
          <p>
            {sceneAction.reason === "declared_unavailable_by_received_tool_output"
              ? `The received tool output declares itself unavailable${sceneAction.unavailable ? `: ${sceneAction.unavailable.reason}` : "."}`
              : "No scene action is available because the received /ask event data has no explicit action envelope."}
          </p>
        ) : (
          <p>
            Scene evidence available from tool result {sceneAction.result.call_id} ({sceneAction.result.tool}), which
            declares the contract status {sceneAction.status}. The action itself is still not inferred: v1 carries no
            action envelope.
          </p>
        )}
      </section>
      {streamClose ? <FailureState state={streamClose} onRetry={chat.onRetry} /> : null}
      <ChatDock
        {...chat}
        status={status}
        error={error}
        onCancel={onCancelRun ? () => onCancelRun(run.identity) : undefined}
      />
      <RunTrace state={run} onCancel={onCancelRun} />
    </section>
  );
}

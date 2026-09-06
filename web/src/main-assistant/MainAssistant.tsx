/**
 * The page-level assembly point for the existing chat dock and the validated
 * `/ask` event reducer.  It owns no provider selection, transport, scene
 * mutation, or event parsing: the caller supplies the reducer state produced
 * from the one same-origin `/ask` SSE stream.
 *
 * Provider PR #277 deliberately preserves the event vocabulary.  This
 * component therefore depends only on that stable vocabulary (`tool_call`,
 * `tool_result`, `done`, and `error`) and can be mounted once the main page's
 * stream owner is ready.
 */
import { ChatDock, type ChatDockProps, type ChatError, type ChatStatus } from "../chat/ChatDock";
import { RunTrace } from "../ask/run-state/RunTrace";
import type { RunIdentity, RunState, ToolResultEvent } from "../ask/run-state/types";
import { sceneActionFromResult, type ReceivedSceneAction } from "../interactive/AgentSimulationAdapter";

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
}

export type SceneActionAvailability =
  | { readonly availability: "unavailable"; readonly reason: "absent_from_received_ask_event_data" }
  | { readonly availability: "available"; readonly action: ReceivedSceneAction; readonly result: ToolResultEvent };

const NO_SCENE_ACTION: SceneActionAvailability = {
  availability: "unavailable",
  reason: "absent_from_received_ask_event_data",
};

/**
 * A scene change is never inferred from a tool name, answer prose, or an arbitrary
 * nested result object.  The only thing read here is the explicit additive
 * `tool_result.result.scene_action` envelope now declared in
 * `docs/research/sse-event-schema.md` § "`scene_action` (additive)", and it is read
 * through the ONE reader (`sceneActionFromResult`) that applies the shared kind
 * vocabulary and identity rule.  A run whose results carry no admissible, available
 * action stays unavailable, which is every v1 run that predates the envelope.
 */
export function sceneActionAvailability(run: RunState): SceneActionAvailability {
  for (const event of run.trace) {
    if (event.type !== "tool_result") continue;
    const action = sceneActionFromResult(event);
    if (action !== null && action.status === "available") {
      return { availability: "available", action, result: event };
    }
  }
  return NO_SCENE_ACTION;
}

/** Translate only reducer-confirmed phases to the dock's visible status. */
export function chatStatusForRun(run: RunState): ChatStatus {
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
      return "idle";
  }
}

/** Pass the server terminal error through unchanged; never synthesize one. */
export function chatErrorForRun(run: RunState): ChatError | undefined {
  const terminal = run.terminal;
  if (terminal?.type !== "error") return undefined;
  return {
    code: terminal.error.code,
    message: terminal.error.message,
    retryable: terminal.error.retryable,
  };
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
  return "Waiting for ordered tool results from the same-origin /ask stream. Scene actions are not inferred while a run is active.";
}

/**
 * Render a page-ready assistant without taking ownership of the page shell.
 * MainPage/router ownership stays external so this can land independently of
 * their work.
 */
export function MainAssistant({ chat, run, onCancelRun }: MainAssistantProps) {
  const sceneAction = sceneActionAvailability(run);
  const status = chatStatusForRun(run);
  const error = chatErrorForRun(run);

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
      >
        <strong>Scene response</strong>
        {sceneAction.availability === "unavailable" ? (
          <p>No scene action is available because the received /ask event data has no explicit action envelope.</p>
        ) : (
          <p>{sceneAction.action.kind} action supplied by tool result {sceneAction.result.call_id}.</p>
        )}
      </section>
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

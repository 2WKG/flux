import { FormEvent, useId, useState } from "react";
import {
  ASK_LIMITS,
  EMPTY_SCENE_CONTEXT,
  SCENE_CONTEXT_FIELDS,
  type AskHistoryMessage,
  type AskRequestBody,
  type SceneContext,
  buildAskRequest,
} from "./ask-contract";
import "./chat.css";

export type { SceneContext, AskRequestBody } from "./ask-contract";

/**
 * The IA's chat terminal contract: "exactly one terminal state ... either `done`
 * or `error`, never both and never a third. An unavailable dependency is not a
 * terminal state of its own -- it arrives as `error` whose `error.code` is
 * `unavailable`" (docs/design/minnesota-demo-narrative-ia.md, "Chat dock role").
 * `unavailable` is therefore an error code here, never a chat status.
 */
export type ChatStatus = "idle" | "streaming" | "done" | "error" | "cancelled";

/** The closed v1 `error.code` set — copilot/sse.py `_ERROR_CODES`. */
export type SseErrorCode =
  | "invalid_request"
  | "unavailable"
  | "deadline"
  | "upstream_error"
  | "tool_error"
  | "refusal"
  | "cancelled"
  | "protocol_error";

/** A terminal `error` event, as the server sends it. The dock never invents one. */
export type ChatError = {
  code: SseErrorCode;
  /** The server's safe, bounded user-facing message. */
  message: string;
  retryable?: boolean;
  /** `meta.request_id` where the server supplied one; the IA requires showing it. */
  requestId?: string;
};

export type SourceTruthLabel = "source_supported" | "source_screened" | "hypothetical" | "synthetic" | "unavailable" | "request_failed";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export type ChatDockProps = {
  /** Opaque producer version; a changed value refreshes the local editable draft. */
  contextRevision: string;
  context: SceneContext;
  /** The `attempt_id` the parent owns for this run; posted verbatim. */
  attemptId: string;
  /** Origin of the supplied context, such as "Scene selection" or "Fixture demo". */
  sourceLabel: string;
  /** Product truth status supplied by the scene/artifact owner; never inferred by the dock. */
  sourceStatus: SourceTruthLabel;
  status: ChatStatus;
  /** Required when `status` is "error": the server's terminal error event. */
  error?: ChatError;
  messages?: ChatMessage[];
  onSend?: (request: AskRequestBody) => void;
  onCancel?: () => void;
  onRetry?: () => void;
  onContextChange?: (context: SceneContext) => void;
};

const sourceStatusLabel: Record<SourceTruthLabel, string> = {
  source_supported: "Source-supported",
  source_screened: "Source-screened",
  hypothetical: "Hypothetical",
  synthetic: "Synthetic",
  unavailable: "Unavailable",
  request_failed: "Request failed",
};

const statusLabel: Record<ChatStatus, string> = {
  idle: "Ready",
  streaming: "Streaming",
  done: "Answer complete",
  error: "Error",
  cancelled: "Cancelled",
};

const displayValue = (value: string | number | null) =>
  value === null || value === "" ? "Not set" : String(value);

function cloneContext(context: SceneContext): SceneContext {
  return { ...context };
}

/** The last `history` messages the server will accept, in the shape it accepts. */
export function askHistory(messages: ChatMessage[]): AskHistoryMessage[] {
  return messages.slice(-ASK_LIMITS.historyMax).map(({ role, content }) => ({ role, content }));
}

function ErrorNotice({ error, onRetry }: { error?: ChatError; onRetry?: () => void }) {
  // The IA binds `error.code === "unavailable"` to the Unavailable label and a
  // named next step, and every other failure to a safe message plus request ID.
  const unavailable = error?.code === "unavailable";
  return (
    <div className={`flux-chat-notice ${unavailable ? "is-unavailable" : "is-error"}`} role="alert">
      <strong>{unavailable ? "Unavailable." : "Request failed."}</strong>{" "}
      {error ? (
        <>
          {error.message}{" "}
          <span className="flux-chat-error-meta">
            code <code>{error.code}</code>
            {error.requestId ? <> · request <code>{error.requestId}</code></> : null}
          </span>{" "}
          {unavailable
            ? "Next step: restore the missing prerequisite, then ask again. Your scene context is retained."
            : "The previous answer, if any, is retained as stale and is not current."}
        </>
      ) : (
        // No server error to show is itself a contract break, not a generic apology.
        <>The server did not supply a terminal error event, so no code, message, or request id can be shown.</>
      )}{" "}
      {onRetry && <button type="button" onClick={onRetry}>Retry</button>}
    </div>
  );
}

function StateNotice({ status, error, onCancel, onRetry }: Pick<ChatDockProps, "status" | "error" | "onCancel" | "onRetry">) {
  if (status === "idle") return null;
  if (status === "streaming") {
    return <div className="flux-chat-notice is-streaming" role="status"><span className="flux-chat-spinner" aria-hidden="true" />Preparing a grounded response… {onCancel && <button type="button" onClick={onCancel}>Stop</button>}</div>;
  }
  if (status === "done") {
    return <div className="flux-chat-notice is-done" role="status"><strong>Answer complete.</strong> This is the run's only terminal state; the scene context above is unchanged.</div>;
  }
  if (status === "cancelled") {
    return <div className="flux-chat-notice" role="status"><strong>Response stopped.</strong> Your scene context was retained. {onRetry && <button type="button" onClick={onRetry}>Try again</button>}</div>;
  }
  return <ErrorNotice error={error} onRetry={onRetry} />;
}

/**
 * A transport-free chat surface. The parent owns requests and run ordering; this
 * component only makes the exact submitted scene context visible and editable,
 * and hands the parent the exact body it would post to `POST /ask`.
 */
export function ChatDock({
  context,
  contextRevision,
  attemptId,
  sourceLabel,
  sourceStatus,
  status,
  error,
  messages = [],
  onSend,
  onCancel,
  onRetry,
  onContextChange,
}: ChatDockProps) {
  const [draft, setDraft] = useState<SceneContext>(() => cloneContext(context));
  const [prompt, setPrompt] = useState("");
  const [editing, setEditing] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  // The producer's own revision is the ONLY reset signal. Keying this on the
  // `context` object identity reset the draft on every re-render whose parent
  // rebuilt the object — which is every keystroke, because editing calls
  // onContextChange — so a field could not be typed into.
  const [syncedRevision, setSyncedRevision] = useState(contextRevision);
  if (syncedRevision !== contextRevision) {
    setSyncedRevision(contextRevision);
    setDraft(cloneContext(context));
  }
  const id = useId();

  const update = (next: Partial<SceneContext>) => {
    const updated = { ...draft, ...next };
    setDraft(updated);
    onContextChange?.(updated);
  };

  const clear = () => {
    setDraft(EMPTY_SCENE_CONTEXT);
    onContextChange?.(EMPTY_SCENE_CONTEXT);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (status === "streaming") return;
    const request = buildAskRequest({ attemptId, question: prompt, context: draft, history: askHistory(messages) });
    if (!request.ok) {
      setProblems(request.problems);
      return;
    }
    setProblems([]);
    onSend?.(request.body);
    setPrompt("");
  };

  const overLimit = prompt.trim().length > ASK_LIMITS.questionMax;

  return (
    <section className="flux-chat" aria-label="Copilot chat">
      <header className="flux-chat-header">
        <div><p>Flux Copilot</p><h2>Ask about this scene</h2></div>
        <span className={`flux-chat-state state-${status}`}>{statusLabel[status]}</span>
      </header>

      <div className="flux-chat-context" aria-label="Scene context">
        <div className="flux-chat-context-head">
          <div><strong>Scene context</strong><span>Source: {sourceLabel} · Truth: {sourceStatusLabel[sourceStatus]} · revision {contextRevision}</span></div>
          <div><button type="button" onClick={() => setEditing((open) => !open)} aria-expanded={editing}>{editing ? "Done editing" : "Edit"}</button><button type="button" className="flux-chat-quiet" onClick={clear}>Clear</button></div>
        </div>
        {editing ? (
          <div className="flux-chat-fields">
            <label htmlFor={`${id}-scenario_id`}>Scenario<input id={`${id}-scenario_id`} name="scenario_id" maxLength={ASK_LIMITS.idMax} value={draft.scenario_id ?? ""} onChange={(event) => update({ scenario_id: event.target.value || null })} placeholder="No scenario selected" /></label>
            <label htmlFor={`${id}-hour`}>Hour ({ASK_LIMITS.hourMin}–{ASK_LIMITS.hourMax})<input id={`${id}-hour`} name="hour" type="number" min={ASK_LIMITS.hourMin} max={ASK_LIMITS.hourMax} step={1} value={draft.hour ?? ""} onChange={(event) => update({ hour: event.target.value === "" ? null : Number(event.target.value) })} placeholder="No hour selected" /></label>
            <label htmlFor={`${id}-selected_site_id`}>Selected site<input id={`${id}-selected_site_id`} name="selected_site_id" maxLength={ASK_LIMITS.idMax} value={draft.selected_site_id ?? ""} onChange={(event) => update({ selected_site_id: event.target.value || null })} placeholder="No site selected" /></label>
            <label htmlFor={`${id}-compare_site_id`}>Compare site<input id={`${id}-compare_site_id`} name="compare_site_id" maxLength={ASK_LIMITS.idMax} value={draft.compare_site_id ?? ""} onChange={(event) => update({ compare_site_id: event.target.value || null })} placeholder="No comparison selected" /></label>
            <label htmlFor={`${id}-selected_element_id`}>Selected element<input id={`${id}-selected_element_id`} name="selected_element_id" maxLength={ASK_LIMITS.idMax} value={draft.selected_element_id ?? ""} onChange={(event) => update({ selected_element_id: event.target.value || null })} placeholder="No element selected" /></label>
            <label htmlFor={`${id}-unit_mw`}>Unit size (MW)<select id={`${id}-unit_mw`} name="unit_mw" value={draft.unit_mw ?? ""} onChange={(event) => update({ unit_mw: event.target.value === "" ? null : (Number(event.target.value) as 300 | 1000) })}><option value="">Not set</option>{ASK_LIMITS.unitMwChoices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}</select></label>
          </div>
        ) : <dl>{SCENE_CONTEXT_FIELDS.map(([field, label]) => <div key={field}><dt>{label}</dt><dd>{displayValue(draft[field])}</dd></div>)}</dl>}
      </div>

      <StateNotice status={status} error={error} onCancel={onCancel} onRetry={onRetry} />

      <div className="flux-chat-transcript" aria-live="polite" aria-label="Conversation">
        {messages.length === 0 ? <p className="flux-chat-empty">No messages yet. Your question will include the visible context above.</p> : messages.map((message) => <article className={`flux-chat-message role-${message.role}`} key={message.id}><span>{message.role === "user" ? "You" : "Copilot"}</span><p>{message.content}</p></article>)}
      </div>

      <form className="flux-chat-compose" onSubmit={submit}>
        <label htmlFor={`${id}-prompt`}>Question for Flux Copilot</label>
        <textarea id={`${id}-prompt`} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Ask what this scenario means…" rows={3} disabled={status === "streaming"} aria-describedby={problems.length ? `${id}-problems` : undefined} />
        {problems.length > 0 && (
          <ul className="flux-chat-problems" id={`${id}-problems`} role="alert">
            {problems.map((problem) => <li key={problem}>{problem}</li>)}
          </ul>
        )}
        <div><span>Context at revision {contextRevision} will be included, as attempt {attemptId}. {prompt.trim().length}/{ASK_LIMITS.questionMax} characters.</span><button type="submit" disabled={!prompt.trim() || overLimit || status === "streaming" || !onSend}>Send</button></div>
      </form>
    </section>
  );
}

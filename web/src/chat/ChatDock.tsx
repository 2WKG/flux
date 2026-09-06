import { FormEvent, useEffect, useId, useState } from "react";
import "./chat.css";

export type ChatStatus = "idle" | "streaming" | "error" | "cancelled" | "unavailable";
export type SourceTruthLabel = "source_supported" | "source_screened" | "hypothetical" | "synthetic" | "unavailable" | "request_failed";

export type SceneContext = {
  geography: string;
  layers: string[];
  facility: string | null;
  scenario: string;
  time: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export type ChatDockProps = {
  /** Opaque producer version; a changed value refreshes the local editable draft. */
  contextRevision: string;
  context: SceneContext;
  /** Origin of the supplied context, such as "Scene selection" or "Fixture demo". */
  sourceLabel: string;
  /** Product truth status supplied by the scene/artifact owner; never inferred by the dock. */
  sourceStatus: SourceTruthLabel;
  status: ChatStatus;
  messages?: ChatMessage[];
  onSend?: (prompt: string, context: SceneContext) => void;
  onCancel?: () => void;
  onRetry?: () => void;
  onContextChange?: (context: SceneContext) => void;
};

const EMPTY_CONTEXT: SceneContext = {
  geography: "",
  layers: [],
  facility: null,
  scenario: "",
  time: "",
};

const sourceStatusLabel: Record<SourceTruthLabel, string> = {
  source_supported: "Source-supported",
  source_screened: "Source-screened",
  hypothetical: "Hypothetical",
  synthetic: "Synthetic",
  unavailable: "Unavailable",
  request_failed: "Request failed",
};

const contextSummary = (context: SceneContext) => [
  ["Geography", context.geography],
  ["Layers", context.layers.length ? context.layers.join(", ") : "None selected"],
  ["Facility", context.facility || "None selected"],
  ["Scenario", context.scenario],
  ["Time", context.time],
] as const;

function cloneContext(context: SceneContext): SceneContext {
  return { ...context, layers: [...context.layers] };
}

function StateNotice({ status, onCancel, onRetry }: Pick<ChatDockProps, "status" | "onCancel" | "onRetry">) {
  if (status === "idle") return null;
  if (status === "streaming") {
    return <div className="flux-chat-notice is-streaming" role="status"><span className="flux-chat-spinner" aria-hidden="true" />Preparing a grounded response… {onCancel && <button type="button" onClick={onCancel}>Stop</button>}</div>;
  }
  if (status === "unavailable") {
    return <div className="flux-chat-notice" role="status"><strong>Agent unavailable.</strong> The scene context remains editable and can be used when the connection returns. {onRetry && <button type="button" onClick={onRetry}>Retry connection</button>}</div>;
  }
  if (status === "cancelled") {
    return <div className="flux-chat-notice" role="status"><strong>Response stopped.</strong> Your scene context was retained. {onRetry && <button type="button" onClick={onRetry}>Try again</button>}</div>;
  }
  return <div className="flux-chat-notice is-error" role="alert"><strong>Response interrupted.</strong> The agent did not return a complete answer. {onRetry && <button type="button" onClick={onRetry}>Retry</button>}</div>;
}

/**
 * A transport-free chat surface. The parent owns requests and run ordering; this
 * component only makes the exact submitted scene context visible and editable.
 */
export function ChatDock({
  context,
  contextRevision,
  sourceLabel,
  sourceStatus,
  status,
  messages = [],
  onSend,
  onCancel,
  onRetry,
  onContextChange,
}: ChatDockProps) {
  const [draft, setDraft] = useState<SceneContext>(() => cloneContext(context));
  const [prompt, setPrompt] = useState("");
  const [editing, setEditing] = useState(false);
  const [layerText, setLayerText] = useState(context.layers.join(", "));
  const id = useId();

  useEffect(() => {
    setDraft(cloneContext(context));
    setLayerText(context.layers.join(", "));
  }, [context, contextRevision]);

  const update = (next: Partial<SceneContext>) => {
    const updated = { ...draft, ...next };
    setDraft(updated);
    onContextChange?.(updated);
  };

  const clear = () => {
    setDraft(EMPTY_CONTEXT);
    setLayerText("");
    onContextChange?.(EMPTY_CONTEXT);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed || status === "streaming") return;
    onSend?.(trimmed, cloneContext(draft));
    setPrompt("");
  };

  return (
    <section className="flux-chat" aria-label="Copilot chat">
      <header className="flux-chat-header">
        <div><p>Flux Copilot</p><h2>Ask about this scene</h2></div>
        <span className={`flux-chat-state state-${status}`}>{status === "idle" ? "Ready" : status}</span>
      </header>

      <div className="flux-chat-context" aria-label="Scene context">
        <div className="flux-chat-context-head">
          <div><strong>Scene context</strong><span>Source: {sourceLabel} · Truth: {sourceStatusLabel[sourceStatus]} · revision {contextRevision}</span></div>
          <div><button type="button" onClick={() => setEditing((open) => !open)} aria-expanded={editing}>{editing ? "Done editing" : "Edit"}</button><button type="button" className="flux-chat-quiet" onClick={clear}>Clear</button></div>
        </div>
        {editing ? (
          <div className="flux-chat-fields">
            <label htmlFor={`${id}-geography`}>Geography<input id={`${id}-geography`} value={draft.geography} onChange={(event) => update({ geography: event.target.value })} placeholder="No geography selected" /></label>
            <label htmlFor={`${id}-layers`}>Visible layers<input id={`${id}-layers`} value={layerText} onChange={(event) => { setLayerText(event.target.value); update({ layers: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) }); }} placeholder="No layers selected" /></label>
            <label htmlFor={`${id}-facility`}>Facility<input id={`${id}-facility`} value={draft.facility || ""} onChange={(event) => update({ facility: event.target.value || null })} placeholder="No facility selected" /></label>
            <label htmlFor={`${id}-scenario`}>Scenario<input id={`${id}-scenario`} value={draft.scenario} onChange={(event) => update({ scenario: event.target.value })} placeholder="No scenario selected" /></label>
            <label htmlFor={`${id}-time`}>Time<input id={`${id}-time`} value={draft.time} onChange={(event) => update({ time: event.target.value })} placeholder="No time selected" /></label>
          </div>
        ) : <dl>{contextSummary(draft).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || "Not set"}</dd></div>)}</dl>}
      </div>

      <StateNotice status={status} onCancel={onCancel} onRetry={onRetry} />

      <div className="flux-chat-transcript" aria-live="polite" aria-label="Conversation">
        {messages.length === 0 ? <p className="flux-chat-empty">No messages yet. Your question will include the visible context above.</p> : messages.map((message) => <article className={`flux-chat-message role-${message.role}`} key={message.id}><span>{message.role === "user" ? "You" : "Copilot"}</span><p>{message.content}</p></article>)}
      </div>

      <form className="flux-chat-compose" onSubmit={submit}>
        <label htmlFor={`${id}-prompt`}>Question for Flux Copilot</label>
        <textarea id={`${id}-prompt`} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Ask what this scenario means…" rows={3} disabled={status === "streaming"} />
        <div><span>Context at revision {contextRevision} will be included.</span><button type="submit" disabled={!prompt.trim() || status === "streaming" || !onSend}>Send</button></div>
      </form>
    </section>
  );
}

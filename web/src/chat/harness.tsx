/**
 * Standalone ChatDock harness. It is not part of the shipped demo bundle; it is
 * built as its own esbuild entry:
 *
 *   cd web && FLUX_WEB_ENTRY=src/chat/harness.tsx FLUX_WEB_DIST=dist-chat-harness \
 *     node scripts/build.mjs
 *
 * which produces `dist-chat-harness/index.html` plus `assets/app.js`.
 * `web/test/chat-dock.test.mjs` builds it the same way, so the harness cannot
 * rot into an entry that never compiles.
 */
import { createRoot } from "react-dom/client";
import { useState } from "react";
import { ChatDock, type AskRequestBody, type ChatError, type ChatMessage, type ChatStatus } from "./ChatDock";
import { EMPTY_SCENE_CONTEXT, type SceneContext } from "./ask-contract";

const FIXTURE_ERROR: ChatError = {
  code: "unavailable",
  message: "The local Copilot backend is not configured.",
  retryable: false,
  requestId: "req_harness_fixture_0001",
};

function Harness() {
  const [context, setContext] = useState<SceneContext>(EMPTY_SCENE_CONTEXT);
  const [revision, setRevision] = useState("ui-fixture-r1");
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [posted, setPosted] = useState<AskRequestBody | null>(null);
  return <main style={{ maxWidth: 580, margin: "24px auto", padding: 12 }}>
    <nav aria-label="Harness controls" style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>{(["idle", "streaming", "done", "error", "cancelled"] as ChatStatus[]).map((value) => <button key={value} type="button" onClick={() => setStatus(value)}>{value}</button>)}</nav>
    <ChatDock
      context={context}
      contextRevision={revision}
      attemptId="harness_attempt_0000001"
      sourceLabel="Standalone UI fixture — no product data"
      sourceStatus="synthetic"
      status={status}
      error={status === "error" ? FIXTURE_ERROR : undefined}
      messages={messages}
      onContextChange={setContext}
      onCancel={() => setStatus("cancelled")}
      onRetry={() => setStatus("idle")}
      onSend={(request) => {
        setPosted(request);
        setMessages((items) => [...items, { id: crypto.randomUUID(), role: "user", content: request.question }, { id: crypto.randomUUID(), role: "assistant", content: `Harness retained revision ${revision}; it posted no request and reached no server.` }]);
        setStatus("done");
      }}
    />
    <button type="button" style={{ marginTop: 12 }} onClick={() => { setContext(EMPTY_SCENE_CONTEXT); setRevision((value) => `${value}-next`); }}>Restore supplied scene context</button>
    {posted && <pre aria-label="Last request body" style={{ marginTop: 12, overflowX: "auto" }}>{JSON.stringify(posted, null, 2)}</pre>}
  </main>;
}

createRoot(document.getElementById("root")!).render(<Harness />);

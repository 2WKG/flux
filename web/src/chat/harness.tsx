import { createRoot } from "react-dom/client";
import { useState } from "react";
import { ChatDock, ChatMessage, ChatStatus, SceneContext } from "./ChatDock";

const initialContext: SceneContext = { geography: "", layers: [], facility: null, scenario: "", time: "" };

function Harness() {
  const [context, setContext] = useState(initialContext);
  const [revision, setRevision] = useState("ui-fixture-r1");
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  return <main style={{ maxWidth: 580, margin: "24px auto", padding: 12 }}>
    <nav aria-label="Harness controls" style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>{(["idle", "streaming", "error", "cancelled", "unavailable"] as ChatStatus[]).map((value) => <button key={value} type="button" onClick={() => setStatus(value)}>{value}</button>)}</nav>
    <ChatDock context={context} contextRevision={revision} sourceLabel="Standalone UI fixture — no product data" sourceStatus="unavailable" status={status} messages={messages} onContextChange={setContext} onCancel={() => setStatus("cancelled")} onRetry={() => setStatus("idle")} onSend={(prompt, submittedContext) => { setMessages((items) => [...items, { id: crypto.randomUUID(), role: "user", content: prompt }, { id: crypto.randomUUID(), role: "assistant", content: `Harness retained revision ${revision}; context geography is ${submittedContext.geography || "not set"}.` }]); setStatus("idle"); }} />
    <button type="button" style={{ marginTop: 12 }} onClick={() => { setContext(initialContext); setRevision((value) => `${value}-next`); }}>Restore supplied scene context</button>
  </main>;
}

createRoot(document.getElementById("root")!).render(<Harness />);

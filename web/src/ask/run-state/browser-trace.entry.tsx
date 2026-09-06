import { useState } from "react";
import { createRoot } from "react-dom/client";
import { RunTraceHarness } from "./RunTrace";
import type { RunEvent, RunIdentity } from "./types";

const current: RunIdentity = { attemptId: "browser-current", contextRevision: "browser-rev-a" };
const replacement: RunIdentity = { attemptId: "browser-replacement", contextRevision: "browser-rev-b" };
const currentEvents: readonly RunEvent[] = [
  { type: "lifecycle", id: "1", v: 1, seq: 1, status: "started" },
  { type: "tool_call", id: "2", v: 1, seq: 2, call_id: "browser-call", tool: "score_site", input: { site_id: "site-browser" } },
];
const replacementEvents: readonly RunEvent[] = [{ type: "lifecycle", id: "1", v: 1, seq: 1, status: "started" }];

function BrowserTrace() {
  const [identity, setIdentity] = useState(current);
  const [cancelled, setCancelled] = useState(false);
  const isReplacement = identity.attemptId === replacement.attemptId;
  return (
    <main data-cancel-callback={cancelled ? "called" : "not-called"}>
      <button type="button" onClick={() => setIdentity(replacement)}>Switch to newer run</button>
      <RunTraceHarness
        identity={identity}
        sourceStatus={isReplacement ? "request_failed" : "source_screened"}
        events={isReplacement ? replacementEvents : currentEvents}
        onCancel={() => setCancelled(true)}
      />
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<BrowserTrace />);

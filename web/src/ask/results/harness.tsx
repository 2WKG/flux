import { createRoot } from "react-dom/client";
import { ResultCards, type AskResult } from "./index";

const results: AskResult[] = [{
  id: "citation-harness", answer: "The returned source supports the stated boundary [10cfr100 p.4].",
  scope: "Citation binding harness", status: { availability: "source_supported", verified: true },
  citations: [{ doc: "10cfr100", title: "10 CFR Part 100", page: 4, chunkId: "p4", text: "Returned citation excerpt.", version: "retrieval-v1" }],
  provenance: [{ artifact_id: "retrieval:10cfr100", artifact_version: "v1", source_kind: "retrieval", source_ref: "10cfr100 p.4" }],
  limitations: ["This harness uses a supplied citation frame."],
  action: { kind: "focus", id: "artifact-focus-1", revision: "artifact-v1", label: "Focus returned artifact", source: "server", geometry: "synthetic" },
}, {
  id: "unavailable-harness", answer: "", scope: "Unavailable action harness", status: { availability: "unavailable", reason: "No server geometry was returned." }, citations: [], provenance: [], limitations: [],
  action: { kind: "focus", id: "unknown", revision: "none", label: "Never rendered", source: "server", geometry: "unavailable" },
}, {
  id: "empty-harness", answer: "", scope: "Empty result harness", status: { availability: "source_screened", empty: true, reason: "The returned source contains no matching artifact." }, citations: [], provenance: [], limitations: [],
}, {
  id: "failure-harness", answer: "", scope: "Failure result harness", status: { availability: "request_failed", reason: "The request ended before an answer was returned." }, citations: [], provenance: [], limitations: [],
}];

createRoot(document.getElementById("root")!).render(<main><h1>Result cards harness</h1><output id="action-result" aria-live="polite" /><ResultCards results={results} onAction={(action) => { document.getElementById("action-result")!.textContent = `${action.kind}:${action.id}@${action.revision}`; }} onUndoAction={(action) => { document.getElementById("action-result")!.textContent = `undo:${action.kind}:${action.id}@${action.revision}`; }} /></main>);

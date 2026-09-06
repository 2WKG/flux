import { createRoot } from "react-dom/client";
import { ResultCards, type AskResult } from "./index";

const results: AskResult[] = [{
  id: "citation-harness", answer: "The returned source supports the stated boundary [10cfr100 p.4]; the exclusion radius is 1200 metres.",
  scope: "Citation binding harness", status: { availability: "source_supported", verified: true },
  citations: [{ doc: "10cfr100", title: "10 CFR Part 100", page: 4, chunk_id: "p4", text: "Returned citation excerpt.", version: "retrieval-v1", content_kind: "source", locator: "§ 100.11", source: "10 CFR Part 100", score: 0.82, citation_id: "cite_01harness" }],
  provenance: [{ artifact_id: "retrieval:10cfr100", artifact_version: "v1", source_kind: "retrieval", source_ref: "10cfr100 p.4" }],
  limitations: ["This harness uses a supplied citation frame."],
  numbers: [{ key: "exclusion_radius_m", value: 1200, display: "1200", citationChunkId: "p4" }],
  action: { kind: "focus", id: "artifact-focus-1", revision: "artifact-v1", label: "Focus returned artifact", source: "server", geometry: "synthetic" },
}, {
  id: "fixture-harness", answer: "The fixture corpus reports a shed of 640 MW.",
  scope: "Fixture citation harness", status: { availability: "synthetic", verified: false, unverifiedNumbers: ["640"] },
  citations: [{ doc: "fixture-brief", title: "Fixture briefing note", page: 1, chunk_id: "fx1", text: "Fixture excerpt.", version: "fixture-v1", content_kind: "fixture", locator: "§ 1", source: "fixture corpus", score: 0.41 }],
  provenance: [], limitations: ["The supporting corpus is a fixture, not a real source."],
}, {
  id: "unavailable-harness", answer: "", scope: "Unavailable action harness", status: { availability: "unavailable", reason: "No server geometry was returned." }, citations: [], provenance: [], limitations: [],
  action: { kind: "focus", id: "unknown", revision: "none", label: "Never rendered", source: "server", geometry: "unavailable" },
}, {
  id: "empty-harness", answer: "", scope: "Empty result harness", status: { availability: "source_screened", empty: true, reason: "The returned source contains no matching artifact." }, citations: [], provenance: [], limitations: [],
}, {
  id: "failure-harness", answer: "", scope: "Failure result harness", status: { availability: "request_failed", reason: "The request ended before an answer was returned." }, citations: [], provenance: [], limitations: [],
}];

createRoot(document.getElementById("root")!).render(<main><h1>Result cards harness</h1><output id="action-result" aria-live="polite" /><ResultCards results={results} onAction={(action) => { document.getElementById("action-result")!.textContent = `${action.kind}:${action.id}@${action.revision}`; }} onUndoAction={(action) => { document.getElementById("action-result")!.textContent = `undo:${action.kind}:${action.id}@${action.revision}`; }} /></main>);

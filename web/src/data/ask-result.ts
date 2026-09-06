/**
 * One reduced `/ask` run as the one result card the answer earned.
 *
 * Everything on the card comes from a frame the server actually sent. In
 * particular:
 *
 * - `availability` is the run's own source status, which the scene owner
 *   supplied and the reducer carried; it is never upgraded here.
 * - `verified` and `unverifiedNumbers` come from the terminal `done` frame, and
 *   are simply absent when the server did not send them. Absence means unknown,
 *   which `ResultCards` renders as "Verification status was not supplied".
 * - Citations come from `citation` frames. No number is bound to a citation
 *   here, so every numeric literal in the prose renders with the unverified
 *   marker until a caller supplies a real `numbers` binding.
 * - A run with no terminal frame, or a terminal `error`, produces **no card**.
 *   A partial answer is not a result.
 */

import type { RunState } from "../ask/run-state/types";
import type { AskResult, ResultCitation } from "../ask/results/types";

function citationsOf(state: RunState): readonly ResultCitation[] {
  return state.trace.flatMap((event) => event.type !== "citation" ? [] : [{
    doc: event.doc,
    title: event.title,
    page: event.page,
    chunk_id: event.chunk_id,
    text: "",
    version: "",
    content_kind: "document",
    locator: "",
    source: "retrieval",
    score: 0,
    citation_id: event.citation_id,
  } as unknown as ResultCitation]);
}

/** The card for a completed run, or `null` when the run produced no answer. */
export function resultFromRun(state: RunState): AskResult | null {
  const terminal = state.terminal;
  if (terminal === undefined || terminal.type !== "done") return null;
  return {
    id: `${state.identity.attemptId}:${state.identity.contextRevision}`,
    answer: state.text,
    status: {
      availability: state.sourceStatus,
      empty: state.text.trim() === "",
      ...(typeof terminal.verified === "boolean" ? { verified: terminal.verified } : {}),
      ...(terminal.unverified_numbers === undefined ? {} : { unverifiedNumbers: terminal.unverified_numbers }),
    },
    citations: citationsOf(state),
    provenance: [],
    limitations: [
      "Numbers in this answer are shown as unverified unless the caller bound them to a returned citation.",
    ],
  };
}

/** Every card a run produced. Zero or one today; a list so the card surface is stable. */
export function resultsFromRun(state: RunState): readonly AskResult[] {
  const result = resultFromRun(state);
  return result === null ? [] : [result];
}

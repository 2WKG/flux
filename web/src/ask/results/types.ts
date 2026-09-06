import type { ArtifactRef, CompareInterventionsInput, RetrievalHit, ScenarioId } from "../../contracts/copilot-tools";

/**
 * The citation frame this component renders.
 *
 * It is derived from the generated `RetrievalHit` contract rather than hand-typed, so a
 * rename or a removal on the backend (`copilot/tools/schemas.py`, exported by
 * `scripts/ci/export_tool_contracts.py`) fails `npm run typecheck` here instead of drifting
 * into a card that silently stops showing a field. Spec 05 requires `cite` to carry source
 * identity and the fixture classification through unchanged, so `content_kind`, `source`,
 * `score`, `locator` and `version` are part of the UI frame and not dropped by the adapter.
 *
 * `citation_id` is the one field the hit itself does not carry: it is the identifier from the
 * SSE `citation` envelope (`docs/research/sse-event-schema.md`). It is optional because a
 * citation resolved directly from a `cite` tool result has not been through the stream.
 */
export type ResultCitation = Pick<
  RetrievalHit,
  "doc" | "title" | "page" | "chunk_id" | "text" | "version" | "content_kind" | "locator" | "source" | "score"
> & {
  /** `citation.citation_id` from the SSE frame, when the answer was streamed. */
  citation_id?: string;
};

/**
 * One number the caller resolved from a tool result -- `CausalData.answer_numbers` or a typed
 * numeric field on another tool payload -- bound to the citation that supports it. The card
 * renders numbers from this list only; a number that appears in answer prose without a
 * traceable entry here is marked unverified rather than shown as evidence.
 */
export interface ResultNumber {
  /** The tool-result key, e.g. an `answer_numbers` key such as `effect`. */
  key: string;
  value: number;
  /** Rendered verbatim in the answer prose; must be the same literal the model wrote. */
  display: string;
  /** `chunk_id` of the supporting citation in `AskResult.citations`. */
  citationChunkId: string;
}

/** Frozen UI truth labels. The adapter passes the server/input status through unchanged. */
export type ResultAvailability =
  | "source_supported"
  | "source_screened"
  | "hypothetical"
  | "synthetic"
  | "unavailable"
  | "request_failed";

export interface ResultStatus {
  availability: ResultAvailability;
  /** A successful, source-labelled response with no matching artifact. */
  empty?: boolean;
  /** `done.verified`, when the server supplied it. Absence means it is unknown. */
  verified?: boolean;
  /** `done.unverified_numbers`: numeric literals the verifier could not trace. */
  unverifiedNumbers?: readonly string[];
  unverifiedCitations?: readonly string[];
  reason?: string;
}

/**
 * An action is supplied by the caller after it has resolved an actual tool result.
 * IDs and revisions are deliberately opaque: this component never derives geometry,
 * a filter, or a comparison request from prose in an answer.
 */
export interface ResultSceneAction {
  kind: "focus" | "filter" | "compare";
  id: string;
  revision: string;
  label: string;
  source: "server" | "fixture";
  geometry: "source_backed" | "synthetic" | "unavailable";
  /** Present only for the server-supported comparison tool. */
  comparison?: CompareInterventionsInput;
}

export interface AskResult {
  id: string;
  answer: string;
  status: ResultStatus;
  citations: readonly ResultCitation[];
  provenance: readonly ArtifactRef[];
  limitations: readonly string[];
  /** Numbers the caller traced to a tool result. Absent means the answer states none. */
  numbers?: readonly ResultNumber[];
  scope?: string;
  scenarioId?: ScenarioId;
  action?: ResultSceneAction;
}

export type ResultActionHandler = (action: ResultSceneAction) => void;

export const ACTION_KINDS = new Set<ResultSceneAction["kind"]>(["focus", "filter", "compare"]);

/**
 * Every action kind this component can offer is reversible in the caller's own scene state:
 * the card hands the same opaque action context back through `onUndoAction`, and it never
 * writes to a server. A kind that could not be undone locally must not be listed here.
 */
export const REVERSIBLE_ACTION_KINDS: readonly ResultSceneAction["kind"][] = ["focus", "filter", "compare"];

export function isSupportedResultAction(action: ResultSceneAction | undefined): action is ResultSceneAction {
  if (!action || !ACTION_KINDS.has(action.kind) || !action.id || !action.revision || !action.label) return false;
  if (action.geometry === "unavailable") return false;
  if (action.source === "fixture" && action.geometry !== "synthetic") return false;
  if (action.kind === "compare") return action.source === "server" && action.comparison !== undefined;
  return action.comparison === undefined;
}

/**
 * The set of numeric literals this card is allowed to present as evidence: those the caller
 * bound to a citation that is actually in `citations`, and that `done.unverified_numbers` did
 * not flag. Everything else in the prose is rendered with the unverified marker.
 */
export function traceableNumberLiterals(result: AskResult): ReadonlySet<string> {
  const unverified = new Set(result.status.unverifiedNumbers ?? []);
  const chunks = new Set(result.citations.map((citation) => citation.chunk_id));
  const literals = new Set<string>();
  for (const number of result.numbers ?? []) {
    if (!chunks.has(number.citationChunkId)) continue;
    if (unverified.has(number.display)) continue;
    literals.add(number.display);
  }
  return literals;
}

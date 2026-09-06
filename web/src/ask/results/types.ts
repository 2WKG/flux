import type { ArtifactRef, CompareInterventionsInput, RetrievalHit, ScenarioId } from "../../contracts/copilot-tools";
import type { AssetStatus } from "../../labels";

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

/**
 * Frozen UI truth labels. The adapter passes the server/input status through
 * unchanged. The six tokens are owned once by `src/labels.ts`; this name is an
 * alias for the result surface and never restates the list.
 */
export type ResultAvailability = AssetStatus;

/**
 * The artifact-provenance axis, which is NOT the UI status vocabulary above.
 * `docs/design/minnesota-gate-0-approval.md:51-66` freezes two separate layers:
 * artifact provenance is `source_backed · synthetic · unavailable`, while the UI
 * status is the six tokens of `src/labels.ts`. `docs/design/texas-demo-narrative-ia.md:77-82`
 * says the same ("Artifact provenance remains a separate three-value layer").
 *
 * So `source_backed` here is correct and must not be "fixed" to `source_supported`:
 * `src/labels.ts` says there is no `source_backed` *status* token, which is a claim
 * about the other axis. `src/status-vocabulary.test.mjs` pins both halves.
 */
export type ArtifactTruthLabel = "source_backed" | "synthetic" | "unavailable";

type AssertTrue<T extends true> = T;
type Equals<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;

/** The frozen three-value axis. Renaming a member fails `tsc --noEmit` here. */
type _ArtifactAxisIsFrozen = AssertTrue<Equals<ArtifactTruthLabel, "source_backed" | "synthetic" | "unavailable">>;
/** `source_backed` is on the provenance axis only; it is never a UI status token. */
type _SourceBackedIsNotAStatus = AssertTrue<Equals<Extract<ArtifactTruthLabel, AssetStatus>, "synthetic" | "unavailable">>;

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
 * The one scene-action vocabulary. Every surface that admits a scene action reads
 * these kinds and the identity rule below: the mounted result card (`ResultCards`),
 * the `/ask` adapter seam (`AgentSimulationAdapter`), and the main assistant.
 * Spec home: `docs/research/sse-event-schema.md` § "`scene_action` (additive)".
 * A new kind is added here first, and nowhere else.
 */
export type SceneActionKind = "focus" | "filter" | "compare" | "scenario_edit" | "cascade";

/**
 * The identity a scene action carries beyond its own opaque `id`. Both fields are
 * optional on the type because which one is REQUIRED depends on the kind; that is
 * decided in exactly one place, by `missingSceneActionIdentity`.
 */
export interface SceneActionIdentity {
  /** Names an edit. An edit hash is never a run identity. */
  editHash?: string;
  /** Names a cascade run. */
  cascadeId?: string;
}

const REQUIRED_SCENE_ACTION_IDENTITY: Readonly<Record<SceneActionKind, keyof SceneActionIdentity | null>> = {
  focus: null,
  filter: null,
  compare: null,
  scenario_edit: "editHash",
  cascade: "cascadeId",
};

const SCENE_ACTION_IDENTITY_WIRE_NAME: Readonly<Record<keyof SceneActionIdentity, string>> = {
  editHash: "edit_hash",
  cascadeId: "cascade_id",
};

/**
 * The wire name of the identity field this kind requires and did not carry, or `null`
 * when the action's identity is complete. Applied to EVERY kind, so no kind gets an
 * exemption by omission, and no surface may substitute one identity for another.
 */
export function missingSceneActionIdentity(kind: SceneActionKind, identity: SceneActionIdentity): string | null {
  const required = REQUIRED_SCENE_ACTION_IDENTITY[kind];
  if (required === null || required === undefined) return null;
  const value = identity[required];
  return value === undefined || value.length === 0 ? SCENE_ACTION_IDENTITY_WIRE_NAME[required] : null;
}

/**
 * An action is supplied by the caller after it has resolved an actual tool result.
 * IDs and revisions are deliberately opaque: this component never derives geometry,
 * a filter, or a comparison request from prose in an answer.
 */
export interface ResultSceneAction extends SceneActionIdentity {
  kind: SceneActionKind;
  id: string;
  revision: string;
  label: string;
  source: "server" | "fixture";
  /** Artifact provenance, not UI status. See `ArtifactTruthLabel` above. */
  geometry: ArtifactTruthLabel;
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

/** The whole vocabulary this admission test recognises as a scene action. */
export const ACTION_KINDS = new Set<SceneActionKind>(["focus", "filter", "compare", "scenario_edit", "cascade"]);

/**
 * The subset of `ACTION_KINDS` this component may OFFER, because each is reversible in the
 * caller's own scene state: the card hands the same opaque action context back through
 * `onUndoAction`, and it never writes to a server. A kind that could not be undone locally
 * must not be listed here -- `scenario_edit` and `cascade` name server-side runs, so they
 * are recognised by the vocabulary and never rendered as a button.
 */
export const REVERSIBLE_ACTION_KINDS: readonly SceneActionKind[] = ["focus", "filter", "compare"];

export function isSupportedResultAction(action: ResultSceneAction | undefined): action is ResultSceneAction {
  if (!action || !ACTION_KINDS.has(action.kind) || !action.id || !action.revision || !action.label) return false;
  // Identity is required of every kind, not only the ones this card can draw.
  if (missingSceneActionIdentity(action.kind, action) !== null) return false;
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

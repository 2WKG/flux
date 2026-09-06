import type { ArtifactRef, CompareInterventionsInput, ScenarioId } from "../../contracts/copilot-tools";

/** The citation frame emitted by the Ask SSE endpoint. */
export interface ResultCitation {
  doc: string;
  title: string;
  page: number;
  chunkId: string;
  text: string;
  version?: string;
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
  scope?: string;
  scenarioId?: ScenarioId;
  action?: ResultSceneAction;
}

export type ResultActionHandler = (action: ResultSceneAction) => void;

export const ACTION_KINDS = new Set<ResultSceneAction["kind"]>(["focus", "filter", "compare"]);

export function isSupportedResultAction(action: ResultSceneAction | undefined): action is ResultSceneAction {
  if (!action || !ACTION_KINDS.has(action.kind) || !action.id || !action.revision || !action.label) return false;
  if (action.geometry === "unavailable") return false;
  if (action.source === "fixture" && action.geometry !== "synthetic") return false;
  if (action.kind === "compare") return action.source === "server" && action.comparison !== undefined;
  return action.comparison === undefined;
}

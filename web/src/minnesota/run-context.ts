/**
 * Minnesota's browser state is deliberately smaller than the general scenario
 * UI. Gate 0 accepts aggregate metadata only: no Minnesota geometry, topology,
 * allocation, scenario result, or feature inspection contract exists yet.
 *
 * This module is the one owner of that state. It supplies an immutable
 * baseline and a versioned URL representation so later readers can extend the
 * shell without inventing a second source of truth.
 */
import type { RunIdentity } from "../ask/run-state/types";
import type { SceneContext } from "../chat/ask-contract";

export const MINNESOTA_BOOKMARK_VERSION = "v1";
export const MINNESOTA_AGGREGATE_SCENE_ID = "mn:coverage:aggregate:v1";
export const MINNESOTA_AGGREGATE_ARTIFACT_ID = "mn:aggregate:manifest:v1";

/** Server context identifiers for the persisted aggregate comparison endpoint. */
export const MINNESOTA_COMPARISON_CONTEXT_IDS = Object.freeze({
  baseline: "mn:baseline:v1",
  candidate: "mn:candidate:v1",
});

/** The one Minnesota scene this branch can identify without inventing geometry. */
export const MINNESOTA_AGGREGATE_SCENE = Object.freeze({
  id: MINNESOTA_AGGREGATE_SCENE_ID,
  geographyId: "mn" as const,
  mode: "aggregate" as const,
  artifactId: MINNESOTA_AGGREGATE_ARTIFACT_ID,
});

export interface MinnesotaRunContext {
  readonly version: typeof MINNESOTA_BOOKMARK_VERSION;
  readonly geographyId: "mn";
  readonly mode: "aggregate";
  readonly sceneId: typeof MINNESOTA_AGGREGATE_SCENE_ID;
  readonly artifactId: typeof MINNESOTA_AGGREGATE_ARTIFACT_ID;
  /**
   * The existing `/ask` contract is retained verbatim. Every field is null
   * because this shell has no server contract that can select a Minnesota
   * scenario, site, element, hour, or unit size.
   */
  readonly sceneContext: Readonly<SceneContext>;
}

/** The explicit shared-contract spelling used by dependent Minnesota surfaces. */
export type MinnesotaSceneRunContext = MinnesotaRunContext;

const emptySceneContext: Readonly<SceneContext> = Object.freeze({
  scenario_id: null,
  hour: null,
  selected_site_id: null,
  compare_site_id: null,
  selected_element_id: null,
  unit_mw: null,
});

/** The only state Gate 0 permits this client to make current. */
export const MINNESOTA_BASELINE_RUN_CONTEXT: Readonly<MinnesotaRunContext> = Object.freeze({
  version: MINNESOTA_BOOKMARK_VERSION,
  geographyId: "mn",
  mode: "aggregate",
  sceneId: MINNESOTA_AGGREGATE_SCENE_ID,
  artifactId: MINNESOTA_AGGREGATE_ARTIFACT_ID,
  sceneContext: emptySceneContext,
});

/** Explicit name for consumers that need the scene and run context as one contract. */
export const MINNESOTA_SCENE_RUN_CONTEXT = MINNESOTA_BASELINE_RUN_CONTEXT;

/** Reset is a stable reference, never a browser-generated approximation. */
export function resetMinnesotaRunContext(): Readonly<MinnesotaRunContext> {
  return MINNESOTA_BASELINE_RUN_CONTEXT;
}

export interface MinnesotaBookmark {
  readonly version: typeof MINNESOTA_BOOKMARK_VERSION;
  readonly context: Readonly<MinnesotaRunContext>;
}

export type MinnesotaBookmarkRead =
  | { readonly kind: "absent"; readonly context: Readonly<MinnesotaRunContext> }
  | { readonly kind: "valid"; readonly bookmark: MinnesotaBookmark }
  | { readonly kind: "invalid"; readonly message: string };

const BOOKMARK_KEYS = ["mn", "mode", "scene", "artifact"] as const;

/**
 * Serialize every baseline field, including mode, rather than relying on a
 * default that may acquire a different meaning in a later version.
 */
export function serializeMinnesotaBookmark(context: Readonly<MinnesotaRunContext>): string {
  if (context !== MINNESOTA_BASELINE_RUN_CONTEXT) {
    throw new Error("Minnesota v1 only serializes the immutable aggregate baseline.");
  }
  const params = new URLSearchParams();
  params.set("mn", MINNESOTA_BOOKMARK_VERSION);
  params.set("mode", context.mode);
  params.set("scene", context.sceneId);
  params.set("artifact", context.artifactId);
  return params.toString();
}

/** A relative URL that preserves the caller's path and fragment, but no stale query fields. */
export function minnesotaBookmarkUrl(
  context: Readonly<MinnesotaRunContext>,
  location: Pick<Location, "pathname" | "hash">,
): string {
  return `${location.pathname}?${serializeMinnesotaBookmark(context)}${location.hash}`;
}

function hasExactlyOne(params: URLSearchParams, key: string): boolean {
  return params.getAll(key).length === 1;
}

/**
 * Read a bookmark without silently repairing it. A malformed or future URL is
 * a named unavailable state; treating it as baseline would make a stale link
 * appear reproducible when it is not.
 */
export function readMinnesotaBookmark(search: string): MinnesotaBookmarkRead {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const present = BOOKMARK_KEYS.filter((key) => params.has(key));
  if (present.length === 0) return { kind: "absent", context: MINNESOTA_BASELINE_RUN_CONTEXT };
  if (present.length !== BOOKMARK_KEYS.length || BOOKMARK_KEYS.some((key) => !hasExactlyOne(params, key))) {
    return { kind: "invalid", message: "The Minnesota bookmark is incomplete or repeats a state field." };
  }
  for (const key of params.keys()) {
    if (!(BOOKMARK_KEYS as readonly string[]).includes(key)) {
      return { kind: "invalid", message: `The Minnesota bookmark contains unsupported field \"${key}\".` };
    }
  }
  if (
    params.get("mn") !== MINNESOTA_BOOKMARK_VERSION ||
    params.get("mode") !== "aggregate" ||
    params.get("scene") !== MINNESOTA_AGGREGATE_SCENE_ID ||
    params.get("artifact") !== MINNESOTA_AGGREGATE_ARTIFACT_ID
  ) {
    return { kind: "invalid", message: "This Minnesota bookmark does not name a supported aggregate baseline." };
  }
  return {
    kind: "valid",
    bookmark: { version: MINNESOTA_BOOKMARK_VERSION, context: MINNESOTA_BASELINE_RUN_CONTEXT },
  };
}

/** The revision is derived from the same versioned state that a reviewer can open. */
export function minnesotaContextRevision(context: Readonly<MinnesotaRunContext>): string {
  return `mn:${serializeMinnesotaBookmark(context)}`;
}

let identitySequence = 0;

/**
 * A RunIdentity remains a two-part identity. A changed attempt is not enough:
 * consumers must also compare the serialized context revision before applying
 * an asynchronous result.
 */
export function createMinnesotaRunIdentity(
  context: Readonly<MinnesotaRunContext>,
  now = Date.now(),
): Readonly<RunIdentity> {
  identitySequence += 1;
  return Object.freeze({
    attemptId: `mn-baseline-${now.toString(36)}-${identitySequence.toString(36)}`,
    contextRevision: minnesotaContextRevision(context),
  });
}

/** True only when both existing RunIdentity fields still name the same request. */
export function isCurrentMinnesotaRun(current: RunIdentity, candidate: RunIdentity): boolean {
  return current.attemptId === candidate.attemptId && current.contextRevision === candidate.contextRevision;
}

export interface MinnesotaRunResult<T> {
  readonly identity: RunIdentity;
  readonly value: T;
}

export type MinnesotaRunResultAcceptance<T> =
  | { readonly kind: "accepted"; readonly value: T }
  | { readonly kind: "stale" };

/**
 * Comparison is a server-owned result. Until that read contract exists, a
 * user action may name the missing dependency but cannot manufacture a delta,
 * ranking, or effect from the aggregate manifest.
 */
export interface MinnesotaComparisonUnavailable {
  readonly kind: "unavailable";
  readonly code: "mn_server_compare_contract_missing";
  readonly baseline: Readonly<MinnesotaRunContext>;
  readonly candidate: Readonly<MinnesotaRunContext>;
  readonly message: string;
}

export function unavailableMinnesotaComparison(
  baseline: Readonly<MinnesotaRunContext>,
  candidate: Readonly<MinnesotaRunContext>,
): MinnesotaComparisonUnavailable {
  return {
    kind: "unavailable",
    code: "mn_server_compare_contract_missing",
    baseline,
    candidate,
    message: "No server comparison contract supplies a Minnesota aggregate baseline, candidate, or effect.",
  };
}

/** Consumers use this seam before rendering any future server response. */
export function acceptMinnesotaRunResult<T>(
  current: RunIdentity,
  result: MinnesotaRunResult<T>,
): MinnesotaRunResultAcceptance<T> {
  return isCurrentMinnesotaRun(current, result.identity)
    ? { kind: "accepted", value: result.value }
    : { kind: "stale" };
}

/** Typed callback seam for later 368/369/396 components. */
export type MinnesotaRunContextChange = (
  context: Readonly<MinnesotaRunContext>,
  identity: Readonly<RunIdentity>,
) => void;

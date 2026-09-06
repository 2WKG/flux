/** Named, recoverable scene states.
 *
 * A large scene fails in a small number of specific ways: the WebGL context
 * is lost, a requested geometry never arrived, a stream stopped partway
 * through, or the assembled scene exceeds its triangle budget. Each is a
 * named state carrying what is missing and what to do next -- never a
 * silent skip, a zero, or an empty success. A lost context is recoverable: a
 * reset/retry transition always leads back to `healthy`, never to a dead end.
 */

import type { OverBudgetContributor, SceneBudgetReport } from "./scene-budget.js";

export type RecoverableState =
  | { readonly kind: "healthy" }
  | {
      readonly kind: "webgl_lost";
      readonly detail: string;
      readonly nextStep: "reset_context";
    }
  | {
      readonly kind: "geometry_missing";
      readonly archetypeId: string;
      readonly detail: string;
      readonly nextStep: "retry_fetch" | "report_unavailable";
    }
  | {
      readonly kind: "partial_load";
      readonly archetypeId: string;
      readonly loadedBytes: number;
      readonly expectedBytes: number;
      readonly detail: string;
      readonly nextStep: "resume_stream";
    }
  | {
      readonly kind: "over_budget";
      readonly totalTriangles: number;
      readonly sceneTriangleBudget: number;
      readonly overBudgetArchetypes: readonly OverBudgetContributor[];
      readonly nextStep: "reduce_lod_or_placements";
    };

export const HEALTHY_STATE: RecoverableState = { kind: "healthy" };

export function reportWebglLost(detail: string): RecoverableState {
  return { kind: "webgl_lost", detail, nextStep: "reset_context" };
}

/**
 * The WebGL context lost/restored transition. `webglcontextrestored` fires
 * after `webglcontextlost` on a recoverable loss (see
 * https://developer.mozilla.org/docs/Web/API/WebGL_API/WebGL_best_practices);
 * this function models that pair without touching a canvas itself. Restoring
 * from any state other than `webgl_lost` is a no-op -- there is nothing to
 * reset -- so the caller always gets a defined state back, never `undefined`.
 */
export function recoverFromWebglLost(state: RecoverableState): RecoverableState {
  return state.kind === "webgl_lost" ? HEALTHY_STATE : state;
}

/** A specific archetype's geometry never arrived (404, checksum mismatch,
 * decode failure). Retryable by default; a caller that has already retried
 * past its own limit should pass "report_unavailable" instead. */
export function reportGeometryMissing(
  archetypeId: string,
  detail: string,
  nextStep: "retry_fetch" | "report_unavailable" = "retry_fetch",
): RecoverableState {
  return { kind: "geometry_missing", archetypeId, detail, nextStep };
}

/** A stream stopped before delivering the full declared byte count. */
export function reportPartialLoad(
  archetypeId: string,
  loadedBytes: number,
  expectedBytes: number,
): RecoverableState {
  return {
    kind: "partial_load",
    archetypeId,
    loadedBytes,
    expectedBytes,
    detail: `${archetypeId}: received ${loadedBytes} of ${expectedBytes} declared bytes.`,
    nextStep: "resume_stream",
  };
}

/**
 * Derive a recoverable state directly from a scene budget report: `healthy`
 * when it fits, `over_budget` naming every contributing archetype when it
 * does not. Never re-sums triangles itself -- the report already did that.
 */
export function deriveBudgetState(report: SceneBudgetReport): RecoverableState {
  if (report.withinBudget) return HEALTHY_STATE;
  return {
    kind: "over_budget",
    totalTriangles: report.totalTriangles,
    sceneTriangleBudget: report.sceneTriangleBudget,
    overBudgetArchetypes: report.overBudgetArchetypes,
    nextStep: "reduce_lod_or_placements",
  };
}

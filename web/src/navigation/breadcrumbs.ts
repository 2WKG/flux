/** Focus and breadcrumb state: the deterministic trail from statewide down to
 * whatever is currently focused, and the walk back up it.
 *
 * The trail is never synthesized: focusing a target records exactly the path
 * taken (which may skip an intermediate scale, e.g. a search result focused
 * directly from statewide) rather than inventing a passed-through region that
 * was never actually visited. That mirrors the browser/server honesty rule in
 * `docs/specs/00-overview.md` and `web/src/scene/minnesota-adapter.ts`: this
 * module only ever records what the caller actually gave it.
 */

import { RESET_SCALE, type Scale, scaleIndex } from "./scale-ladder.js";

/** Something a user can focus: a named zone, region, or facility at a given scale. */
export interface FocusTarget {
  readonly scale: Scale;
  readonly id: string;
  readonly label: string | null;
}

/** The one stable target "return to a known statewide view" always resolves to. */
export const STATEWIDE_RESET_TARGET: FocusTarget = {
  scale: RESET_SCALE,
  id: "statewide",
  label: "Statewide",
};

export interface NavigationState {
  /** Root-first trail; index 0 is always `STATEWIDE_RESET_TARGET`. */
  readonly breadcrumbs: readonly FocusTarget[];
  readonly current: FocusTarget;
}

/** The stable starting/reset state. Calling this repeatedly always yields an equal value. */
export function createNavigationState(): NavigationState {
  return { breadcrumbs: [STATEWIDE_RESET_TARGET], current: STATEWIDE_RESET_TARGET };
}

export type FocusRejectionReason =
  | "unknown_scale"
  | "invalid_statewide_target";

export type FocusResult =
  | { readonly kind: "focused"; readonly state: NavigationState }
  | { readonly kind: "rejected"; readonly reason: FocusRejectionReason; readonly detail: string };

/**
 * Focus a target, pushing it onto the breadcrumb trail.
 *
 * The new trail keeps every existing breadcrumb strictly wider (shallower)
 * than the target's scale, then appends the target -- so focusing a region
 * from inside a facility truncates back to statewide before adding the new
 * region, and focusing a facility from statewide simply extends the trail.
 * This is the one rule that makes "walk back up the trail" deterministic:
 * a breadcrumb's position always matches its own scale's depth.
 */
export function focus(state: NavigationState, target: FocusTarget): FocusResult {
  const targetIndex = scaleIndex(target.scale);
  if (targetIndex < 0) {
    return { kind: "rejected", reason: "unknown_scale", detail: `Unknown scale "${target.scale}".` };
  }
  if (targetIndex === 0) {
    if (target.id !== STATEWIDE_RESET_TARGET.id) {
      return {
        kind: "rejected",
        reason: "invalid_statewide_target",
        detail: `"${target.id}" is not the named statewide reset target.`,
      };
    }
    return { kind: "focused", state: createNavigationState() };
  }
  const ancestors = state.breadcrumbs.filter((crumb) => scaleIndex(crumb.scale) < targetIndex);
  const breadcrumbs = [...ancestors, target];
  return { kind: "focused", state: { breadcrumbs, current: target } };
}

export type BreadcrumbNavigationResult =
  | { readonly kind: "navigated"; readonly state: NavigationState }
  | { readonly kind: "rejected"; readonly reason: "invalid_breadcrumb_index"; readonly detail: string };

/** Walk back (or to) a specific point on the trail by its index. Never invents a step in between. */
export function goToBreadcrumb(state: NavigationState, index: number): BreadcrumbNavigationResult {
  if (!Number.isInteger(index) || index < 0 || index >= state.breadcrumbs.length) {
    return {
      kind: "rejected",
      reason: "invalid_breadcrumb_index",
      detail: `Breadcrumb index ${index} is out of range for a trail of length ${state.breadcrumbs.length}.`,
    };
  }
  const breadcrumbs = state.breadcrumbs.slice(0, index + 1);
  return { kind: "navigated", state: { breadcrumbs, current: breadcrumbs[breadcrumbs.length - 1] } };
}

/** Return to the named, stable statewide reset target. Always the same result. */
export function resetToStatewide(): NavigationState {
  return createNavigationState();
}

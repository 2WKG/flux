/** Named navigation commands: the one set of transitions a pointer handler
 * and a keyboard handler both call.
 *
 * This file builds no DOM handler. It exists so that, later, a pointer click
 * and a keyboard shortcut can each dispatch the same command value through
 * the same function and get an identical, deterministic result -- there is
 * no second, pointer-only or keyboard-only code path to drift out of sync.
 *
 * Two independent channels, deliberately not merged:
 * - `ScaleCommand` steps the semantic-zoom scale itself (statewide/region/
 *   facility) -- a camera-level "zoom in/out" that never invents which
 *   region or facility to land on.
 * - `FocusCommand` changes what is focused and walks the breadcrumb trail.
 * A caller that wants "zoom into this specific facility" issues a `FOCUS`
 * command with a target it already has (e.g. from `search.ts`); this module
 * never synthesizes that target for a bare zoom step.
 */

import {
  type BreadcrumbNavigationResult,
  type FocusResult,
  type FocusTarget,
  type NavigationState,
  focus,
  goToBreadcrumb,
  resetToStatewide,
} from "./breadcrumbs.js";
import { type Scale, zoomInScale, zoomOutScale } from "./scale-ladder.js";

export type ScaleCommand = { readonly type: "ZOOM_IN" } | { readonly type: "ZOOM_OUT" };

/** Step the scale one level in the requested direction, clamped at the ladder's ends. */
export function applyScaleCommand(scale: Scale, command: ScaleCommand): Scale {
  switch (command.type) {
    case "ZOOM_IN":
      return zoomInScale(scale);
    case "ZOOM_OUT":
      return zoomOutScale(scale);
  }
}

export type FocusCommand =
  | { readonly type: "FOCUS"; readonly target: FocusTarget }
  | { readonly type: "GO_TO_BREADCRUMB"; readonly index: number }
  | { readonly type: "RESET_TO_STATEWIDE" };

export type FocusCommandResult =
  | { readonly kind: "applied"; readonly state: NavigationState }
  | { readonly kind: "rejected"; readonly reason: string; readonly detail: string };

function fromFocusResult(result: FocusResult): FocusCommandResult {
  return result.kind === "focused"
    ? { kind: "applied", state: result.state }
    : { kind: "rejected", reason: result.reason, detail: result.detail };
}

function fromBreadcrumbResult(result: BreadcrumbNavigationResult): FocusCommandResult {
  return result.kind === "navigated"
    ? { kind: "applied", state: result.state }
    : { kind: "rejected", reason: result.reason, detail: result.detail };
}

/** Apply one focus/breadcrumb command to the current navigation state. */
export function applyFocusCommand(state: NavigationState, command: FocusCommand): FocusCommandResult {
  switch (command.type) {
    case "RESET_TO_STATEWIDE":
      return { kind: "applied", state: resetToStatewide() };
    case "FOCUS":
      return fromFocusResult(focus(state, command.target));
    case "GO_TO_BREADCRUMB":
      return fromBreadcrumbResult(goToBreadcrumb(state, command.index));
  }
}

/**
 * The stable command table. A pointer handler and a keyboard handler each
 * call the same named function with the same arguments; neither owns its own
 * copy of the transition logic.
 */
export const NAVIGATION_COMMANDS = {
  zoomIn: (scale: Scale): Scale => applyScaleCommand(scale, { type: "ZOOM_IN" }),
  zoomOut: (scale: Scale): Scale => applyScaleCommand(scale, { type: "ZOOM_OUT" }),
  focusTarget: (state: NavigationState, target: FocusTarget): FocusCommandResult =>
    applyFocusCommand(state, { type: "FOCUS", target }),
  goToBreadcrumb: (state: NavigationState, index: number): FocusCommandResult =>
    applyFocusCommand(state, { type: "GO_TO_BREADCRUMB", index }),
  resetToStatewide: (state: NavigationState): FocusCommandResult =>
    applyFocusCommand(state, { type: "RESET_TO_STATEWIDE" }),
} as const;
